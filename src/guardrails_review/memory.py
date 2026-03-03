"""Per-repo memory for guardrails-review stored on a dedicated branch.

Memory is stored as ``memory.json`` on the ``guardrails-memory`` orphan branch
of the target repository. This uses only ``contents: write``, which the default
``GITHUB_TOKEN`` already has — no PAT or extra permissions needed.

Storage flow:
    1. load_memory(owner, repo)
       - GET /repos/{owner}/{repo}/contents/memory.json?ref=guardrails-memory
       - Decode base64 content, parse JSON, return Memory
       - On 404 (first run) or any error: return empty Memory

    2. (run review)

    3. update_from_review(mem, result, threads)
       - Update resolution stats from resolved threads
       - Returns new Memory instance

    4. save_memory(owner, repo, memory)
       - Prune false_positives to FALSE_POSITIVE_LIMIT (LRU by last_seen)
       - Warn if serialized size exceeds MEMORY_SIZE_WARN_BYTES
       - GET current file SHA (needed for update; 404 → create orphan branch first)
       - PUT /repos/{owner}/{repo}/contents/memory.json on guardrails-memory branch

Concurrent CI runs:
    Use ``concurrency: group`` in workflow YAML to serialize runs on the same PR.
    The branch approach is not atomic — concurrent writes can race. Serialization
    at the workflow level is the correct fix.

Fallback:
    All operations fall back gracefully. If load or save fails, the bot continues
    stateless — correct behaviour, just without memory.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from guardrails_review.github import run_gh

if TYPE_CHECKING:
    from guardrails_review.types import ReviewResult, ReviewThread

logger = logging.getLogger(__name__)

MEMORY_BRANCH = "guardrails-memory"
MEMORY_FILENAME = "memory.json"
FALSE_POSITIVE_LIMIT = 50
MEMORY_SIZE_WARN_BYTES = 100_000  # 100 KB


@dataclass
class FalsePositive:
    """A tracked false positive pattern for a project."""

    pattern: str
    rule: str
    file_pattern: str
    occurrences: int
    first_seen: str
    last_seen: str


@dataclass
class ResolutionStats:
    """Cumulative thread resolution statistics for a project."""

    total_threads: int
    fixed: int
    false_positive: int
    wont_fix: int
    avg_rounds_to_resolve: float


@dataclass
class Memory:
    """Per-repo memory stored on the guardrails-memory branch."""

    version: int
    repo: str
    false_positives: list[FalsePositive] = field(default_factory=list)
    conventions: list[str] = field(default_factory=list)
    resolution_stats: ResolutionStats = field(
        default_factory=lambda: ResolutionStats(
            total_threads=0,
            fixed=0,
            false_positive=0,
            wont_fix=0,
            avg_rounds_to_resolve=0.0,
        )
    )


def _empty_memory(owner: str, repo: str) -> Memory:
    """Return a fresh empty Memory for the given repo."""
    return Memory(version=1, repo=f"{owner}/{repo}")


def _dict_to_memory(data: dict) -> Memory:
    """Deserialize a dict into a Memory dataclass."""
    fp_list = [FalsePositive(**fp) for fp in data.get("false_positives", [])]
    stats_data = data.get("resolution_stats", {})
    stats = ResolutionStats(
        total_threads=stats_data.get("total_threads", 0),
        fixed=stats_data.get("fixed", 0),
        false_positive=stats_data.get("false_positive", 0),
        wont_fix=stats_data.get("wont_fix", 0),
        avg_rounds_to_resolve=stats_data.get("avg_rounds_to_resolve", 0.0),
    )
    return Memory(
        version=data.get("version", 1),
        repo=data.get("repo", ""),
        false_positives=fp_list,
        conventions=data.get("conventions", []),
        resolution_stats=stats,
    )


def _prune_memory(memory: Memory) -> Memory:
    """Prune false_positives to FALSE_POSITIVE_LIMIT, keeping most recent by last_seen."""
    fps = memory.false_positives
    if len(fps) <= FALSE_POSITIVE_LIMIT:
        return dataclasses.replace(memory)
    pruned = sorted(fps, key=lambda fp: fp.last_seen, reverse=True)[:FALSE_POSITIVE_LIMIT]
    return dataclasses.replace(memory, false_positives=pruned)


def _get_file_sha(owner: str, repo: str) -> str:
    """Fetch the current SHA of memory.json on the memory branch.

    Returns the SHA string if the file exists, empty string on 404.
    Raises RuntimeError on unexpected errors.
    """
    proc = run_gh(
        "api",
        f"repos/{owner}/{repo}/contents/{MEMORY_FILENAME}",
        "--method",
        "GET",
        "-H",
        f"X-GitHub-Ref: {MEMORY_BRANCH}",
        "-f",
        f"ref={MEMORY_BRANCH}",
    )
    data = json.loads(proc.stdout)
    return str(data.get("sha", ""))


def _read_file_content(owner: str, repo: str) -> str:
    """Fetch and decode memory.json content from the memory branch.

    Returns decoded JSON string. Raises RuntimeError if the file doesn't exist.
    """
    proc = run_gh(
        "api",
        f"repos/{owner}/{repo}/contents/{MEMORY_FILENAME}",
        "--method",
        "GET",
        "-f",
        f"ref={MEMORY_BRANCH}",
    )
    data = json.loads(proc.stdout)
    # GitHub returns content as base64 with possible newlines
    raw = data["content"].replace("\n", "")
    return base64.b64decode(raw).decode()


def _create_orphan_branch(owner: str, repo: str) -> None:
    """Create the guardrails-memory orphan branch via the Git refs API.

    Uses the repo's default branch HEAD as a base, then we overwrite the file.
    If the branch already exists, this is a no-op (ref creation returns 422).
    """
    # Get the default branch SHA to use as base (let RuntimeError propagate on failure)
    proc = run_gh(
        "api",
        f"repos/{owner}/{repo}",
        "--method",
        "GET",
        "-q",
        ".default_branch",
    )
    default_branch = proc.stdout.strip()
    ref_proc = run_gh(
        "api",
        f"repos/{owner}/{repo}/git/ref/heads/{default_branch}",
        "--method",
        "GET",
        "-q",
        ".object.sha",
    )
    base_sha = ref_proc.stdout.strip()

    try:
        run_gh(
            "api",
            f"repos/{owner}/{repo}/git/refs",
            "--method",
            "POST",
            "-f",
            f"ref=refs/heads/{MEMORY_BRANCH}",
            "-f",
            f"sha={base_sha}",
        )
    except RuntimeError as exc:
        # 422 = branch already exists, that's fine
        if "422" not in str(exc):
            raise


def _put_file(
    owner: str,
    repo: str,
    content_json: str,
    sha: str,
    commit_message: str,
) -> None:
    """Write memory.json to the memory branch via the Contents API."""
    content_b64 = base64.b64encode(content_json.encode()).decode()
    payload: dict = {
        "message": commit_message,
        "content": content_b64,
        "branch": MEMORY_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    run_gh(
        "api",
        f"repos/{owner}/{repo}/contents/{MEMORY_FILENAME}",
        "--method",
        "PUT",
        input_data=json.dumps(payload),
    )


def load_memory(owner: str, repo: str) -> Memory:
    """Load per-repo memory from the guardrails-memory branch.

    Falls back to an empty stateless Memory on any failure (404, network, etc.).

    Args:
        owner: GitHub repository owner.
        repo: GitHub repository name.

    Returns:
        Memory dataclass populated from branch (or empty on failure/first run).
    """
    try:
        content = _read_file_content(owner, repo)
        data = json.loads(content)
        return _dict_to_memory(data)
    except (RuntimeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Failed to load memory (running stateless): %s", exc)
        return _empty_memory(owner, repo)


def save_memory(memory: Memory) -> None:
    """Save memory to the guardrails-memory branch.

    Prunes false_positives before saving. Creates the branch on first run.
    Logs a warning (does not raise) if the save fails.

    Args:
        memory: The Memory to persist.
    """
    parts = memory.repo.split("/", 1)
    owner = parts[0] if len(parts) == 2 else "unknown"  # noqa: PLR2004
    repo = parts[1] if len(parts) == 2 else "unknown"  # noqa: PLR2004

    memory = _prune_memory(memory)
    content_json = json.dumps(dataclasses.asdict(memory), indent=2)

    size = len(content_json.encode())
    if size > MEMORY_SIZE_WARN_BYTES:
        logger.warning(
            "Memory size %d bytes exceeds %d byte threshold — consider pruning conventions",
            size,
            MEMORY_SIZE_WARN_BYTES,
        )

    try:
        # Try to get the current file SHA (needed to update an existing file)
        try:
            sha = _get_file_sha(owner, repo)
        except RuntimeError:
            # File (or branch) doesn't exist — create the branch first
            _create_orphan_branch(owner, repo)
            sha = ""

        _put_file(owner, repo, content_json, sha, "chore: update guardrails-review memory")
    except RuntimeError as exc:
        logger.warning("Failed to save memory to %s branch: %s", MEMORY_BRANCH, exc)


def update_from_review(
    memory: Memory,
    result: ReviewResult,  # noqa: ARG001
    threads: list[ReviewThread],
) -> Memory:
    """Update memory based on the outcome of a review round.

    Counts resolved threads and updates resolution stats.
    Returns a new Memory instance (does not mutate in place).

    Args:
        memory: Current memory state.
        result: The ReviewResult from this round (reserved for future use).
        threads: All review threads on the PR.

    Returns:
        Updated Memory instance.
    """
    resolved = [t for t in threads if t.is_resolved]
    n_fixed = len(resolved)

    if n_fixed == 0:
        return dataclasses.replace(memory)

    stats = memory.resolution_stats
    new_total = stats.total_threads + n_fixed
    new_fixed = stats.fixed + n_fixed

    if new_total > 0:
        new_avg = (stats.avg_rounds_to_resolve * stats.total_threads + n_fixed * 1.0) / new_total
    else:
        new_avg = 0.0

    new_stats = ResolutionStats(
        total_threads=new_total,
        fixed=new_fixed,
        false_positive=stats.false_positive,
        wont_fix=stats.wont_fix,
        avg_rounds_to_resolve=round(new_avg, 2),
    )
    return dataclasses.replace(memory, resolution_stats=new_stats)


def build_memory_context(memory: Memory) -> str:
    """Build a prompt context string from memory for injection into LLM prompts.

    Returns empty string when there is nothing useful to inject.

    Args:
        memory: Current project memory.

    Returns:
        Multi-line string summarising known false positives and conventions,
        or empty string if memory has no useful data.
    """
    parts: list[str] = []

    if memory.false_positives:
        parts.append("## Known False Positives (skip these patterns)")
        parts.extend(
            f"- [{fp.rule}] {fp.pattern} (in {fp.file_pattern}, seen {fp.occurrences}x)"
            for fp in memory.false_positives
        )

    if memory.conventions:
        parts.append("## Project Conventions")
        parts.extend(f"- {conv}" for conv in memory.conventions)

    return "\n".join(parts)
