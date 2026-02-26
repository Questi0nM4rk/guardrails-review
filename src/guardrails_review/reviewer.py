"""Core review orchestrator: diff -> LLM -> validate -> post."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING, Any

from guardrails_review.cache import save_review
from guardrails_review.config import load_config
from guardrails_review.diff import parse_diff_hunks
from guardrails_review.github import (
    get_deleted_files,
    get_pr_diff,
    get_pr_metadata,
    get_repo_info,
    post_review,
    resolve_thread,
    set_commit_status,
)
from guardrails_review.llm import call_openrouter, call_openrouter_tools
from guardrails_review.parser import parse_response, parse_submit_review_args
from guardrails_review.prompts import build_agentic_messages, build_messages
from guardrails_review.threads import (
    deduplicate_comments,
    find_resolvable_threads,
    get_our_threads,
    get_review_threads,
)
from guardrails_review.tools import TOOL_DEFINITIONS, ToolContext, execute_tool
from guardrails_review.types import (
    REVIEW_MARKER,
    ReviewResult,
)

if TYPE_CHECKING:
    from pathlib import Path

    from guardrails_review.types import (
        PRMetadata,
        ReviewComment,
        ReviewConfig,
        ReviewThread,
    )

logger = logging.getLogger(__name__)


def validate_comments(
    comments: list[ReviewComment],
    valid_lines: dict[str, set[int]],
) -> tuple[list[ReviewComment], list[ReviewComment]]:
    """Split comments into valid (on diff lines) and invalid (outside diff).

    Returns:
        Tuple of (valid_comments, invalid_comments).
    """
    valid: list[ReviewComment] = []
    invalid: list[ReviewComment] = []
    for c in comments:
        file_lines = valid_lines.get(c.path, set())
        if c.line in file_lines:
            valid.append(c)
        else:
            invalid.append(c)
    return valid, invalid


def _try_set_status(
    owner: str, repo: str, sha: str, state: str, description: str
) -> None:
    """Set commit status, logging but not raising on failure."""
    try:
        set_commit_status(owner, repo, sha, state, description)
    except RuntimeError:
        logger.warning("Failed to set %s commit status (non-fatal)", state)


def _try_dedup(
    pr: int,
    final: ReviewResult,
    invalid_comments: list[ReviewComment],
    owner: str,
    repo: str,
) -> tuple[ReviewResult, list[ReviewThread]]:
    """Deduplicate comments against existing threads."""
    our_existing: list[ReviewThread] = []
    try:
        existing_threads = get_review_threads(pr, owner, repo)
        our_existing = get_our_threads(existing_threads)
        deduped = deduplicate_comments(final.comments, our_existing)
        if len(deduped) != len(final.comments):
            logger.info(
                "Deduplication removed %d comment(s)",
                len(final.comments) - len(deduped),
            )
            verdict = _compute_verdict(deduped + invalid_comments)
            final = ReviewResult(
                verdict=verdict,
                summary=final.summary,
                comments=deduped,
                model=final.model,
                timestamp=final.timestamp,
                pr=pr,
            )
    except RuntimeError:
        logger.warning("Failed to fetch threads for deduplication (non-fatal)")

    return final, our_existing


def _try_auto_resolve(
    pr: int,
    our_existing: list[ReviewThread],
    valid_lines: dict[str, set[int]],
    commit_sha: str,
) -> set[str]:
    """Auto-resolve stale threads, logging failures.

    Returns set of thread IDs that were successfully resolved.
    """
    resolved_ids: set[str] = set()
    try:
        deleted = get_deleted_files(pr)
        unresolved = [t for t in our_existing if not t.is_resolved]
        resolutions = find_resolvable_threads(
            unresolved, valid_lines, deleted, commit_sha
        )
        for r in resolutions:
            if resolve_thread(r.thread_id):
                resolved_ids.add(r.thread_id)
                logger.info("Auto-resolved %s: %s", r.thread_id, r.reason)
    except RuntimeError:
        logger.warning("Failed to auto-resolve threads (non-fatal)")
    return resolved_ids


def _check_unresolved_threads(
    our_threads: list[ReviewThread],
    auto_resolved_ids: set[str],
) -> list[ReviewThread]:
    """Return guardrails-review threads still unresolved after auto-resolve.

    Args:
        our_threads: All threads with the guardrails-review marker.
        auto_resolved_ids: Thread IDs that were just auto-resolved.

    Returns:
        List of threads that are still unresolved.
    """
    return [
        t
        for t in our_threads
        if not t.is_resolved and t.thread_id not in auto_resolved_ids
    ]


def run_review(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += (
            "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        )
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}`: {c.body}"

    # Determine final verdict: any comments = request_changes, none = approve
    verdict = _compute_verdict(valid_comments + invalid_comments)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    owner, repo = get_repo_info()
    commit_sha = pr_meta.head_ref_oid

    if not dry_run:
        _try_set_status(owner, repo, commit_sha, "pending", "Review in progress")

    # Deduplicate comments against existing threads
    final, our_existing = _try_dedup(pr, final, invalid_comments, owner, repo)

    # Auto-resolve stale threads before posting
    auto_resolved_ids = _try_auto_resolve(pr, our_existing, valid_lines, commit_sha)

    # Check remaining unresolved guardrails-review threads
    still_unresolved = _check_unresolved_threads(our_existing, auto_resolved_ids)
    if final.verdict == "approve" and still_unresolved:
        n_unresolved = len(still_unresolved)
        msg = (
            f"\n\n---\n**{n_unresolved} unresolved thread(s) "
            f"from previous review rounds remain open.**"
        )
        final = ReviewResult(
            verdict="request_changes",
            summary=final.summary + msg,
            comments=final.comments,
            model=final.model,
            timestamp=final.timestamp,
            pr=pr,
        )
        logger.info(
            "Approval blocked: %d unresolved thread(s) from previous rounds",
            n_unresolved,
        )

    if dry_run:
        _print_dry_run(final)
        return 0

    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)

    # Set final commit status
    n = len(final.comments) + len(invalid_comments)
    if final.verdict == "approve":
        _try_set_status(owner, repo, commit_sha, "success", "Approved")
    else:
        desc = f"{n} defect(s) found" if n > 0 else "Unresolved threads remain"
        _try_set_status(owner, repo, commit_sha, "failure", desc)

    print(f"Review posted for PR #{pr}: {final.verdict}")
    return 0


def _run_oneshot_review(
    config: ReviewConfig,
    diff: str,
    pr_meta: PRMetadata,
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff -> LLM JSON -> result)."""
    messages = build_messages(diff, config, pr_meta)
    raw_response = call_openrouter(messages, config.model)
    return parse_response(raw_response, config.model, pr)


def _run_agentic_review(
    config: ReviewConfig,
    diff: str,
    pr_meta: PRMetadata,
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta.head_ref_oid
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls -- model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response -- shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review
    logger.warning(
        "Agentic loop exhausted %d iterations without conclusion",
        config.max_iterations,
    )
    return ReviewResult(
        verdict="request_changes",
        summary=(
            f"{REVIEW_MARKER}\n"
            f"Review loop exhausted after {config.max_iterations} "
            f"iterations without reaching a conclusion."
        ),
        comments=[],
        model=config.model,
        timestamp=datetime.now(tz=UTC).isoformat(),
        pr=pr,
    )


def _compute_verdict(comments: list[ReviewComment]) -> str:
    """Determine verdict: any comments = request_changes, none = approve."""
    if comments:
        return "request_changes"
    return "approve"


def run_resolve(
    pr: int,
    *,
    dry_run: bool = False,
) -> int:
    """Auto-resolve stale review threads on a PR.

    Fetches our review threads, checks which can be resolved,
    and resolves them via GitHub GraphQL API.

    Args:
        pr: Pull request number.
        dry_run: If True, print resolvable threads without resolving.

    Returns:
        0 on success, 1 on failure.
    """
    owner, repo = get_repo_info()
    pr_meta = get_pr_metadata(pr)
    diff = get_pr_diff(pr)
    valid_lines = parse_diff_hunks(diff)
    head_sha = pr_meta.head_ref_oid

    try:
        deleted = get_deleted_files(pr)
    except RuntimeError:
        logger.warning("Failed to fetch deleted files, assuming none")
        deleted = set()

    try:
        all_threads = get_review_threads(pr, owner, repo)
    except RuntimeError:
        logger.warning("Failed to fetch review threads")
        print("Failed to fetch review threads")
        return 1

    our_threads = get_our_threads(all_threads)
    unresolved = [t for t in our_threads if not t.is_resolved]
    resolutions = find_resolvable_threads(unresolved, valid_lines, deleted, head_sha)

    if dry_run:
        print(f"=== Resolve Dry Run: PR #{pr} ===")
        print(f"Our threads: {len(our_threads)} ({len(unresolved)} unresolved)")
        print(f"Resolvable: {len(resolutions)}")
        for r in resolutions:
            print(f"  {r.thread_id}: {r.reason}")
        return 0

    resolved_count = 0
    for r in resolutions:
        if resolve_thread(r.thread_id):
            resolved_count += 1
            logger.info("Resolved %s: %s", r.thread_id, r.reason)
        else:
            logger.warning("Failed to resolve %s", r.thread_id)

    print(f"Resolved {resolved_count}/{len(resolutions)} stale threads on PR #{pr}")
    return 0


def _print_dry_run(result: ReviewResult) -> None:
    """Print review result to stdout without posting."""
    print(f"=== Dry Run: PR #{result.pr} ===")
    print(f"Verdict: {result.verdict}")
    print(f"Model: {result.model}")
    print(f"\n{result.summary}")
    if result.comments:
        print(f"\n--- {len(result.comments)} inline comment(s) ---")
        for c in result.comments:
            print(f"  {c.path}:{c.line} — {c.body}")
