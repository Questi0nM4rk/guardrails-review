"""Core review orchestrator: diff -> LLM -> validate -> post."""

from __future__ import annotations

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
from guardrails_review.types import ReviewResult

if TYPE_CHECKING:
    from pathlib import Path

    from guardrails_review.types import (
        LLMResponse,
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


def _build_final_result(
    result: ReviewResult,
    valid_lines: dict[str, set[int]],
    pr: int,
) -> tuple[ReviewResult, list[ReviewComment]]:
    """Validate comments and build the initial final ReviewResult.

    Returns:
        Tuple of (final ReviewResult with valid comments only, invalid comments).
    """
    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    summary = result.summary
    if invalid_comments:
        summary += (
            "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        )
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}`: {c.body}"

    verdict = _compute_verdict(valid_comments + invalid_comments)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )
    return final, invalid_comments


def _block_approval_if_unresolved(
    final: ReviewResult,
    our_existing: list[ReviewThread],
    auto_resolved_ids: set[str],
    pr: int,
) -> ReviewResult:
    """Block approval if unresolved threads remain from previous rounds."""
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
    return final


def _post_and_set_status(
    pr: int,
    final: ReviewResult,
    invalid_comments: list[ReviewComment],
    repo_info: tuple[str, str, str],
    project_dir: Path | None,
) -> int:
    """Post review to GitHub and set final commit status.

    Args:
        repo_info: Tuple of (owner, repo, commit_sha).

    Returns 0 on success, 1 on failure.
    """
    owner, repo, commit_sha = repo_info
    try:
        post_review(pr, final, owner, repo, commit_sha)
    except RuntimeError as exc:
        logger.exception("Failed to post review")
        print(f"Error posting review: {exc}")
        _try_set_status(owner, repo, commit_sha, "error", "Review post failed")
        return 1

    save_review(final, project_dir)

    n = len(final.comments) + len(invalid_comments)
    if final.verdict == "approve":
        _try_set_status(owner, repo, commit_sha, "success", "Approved")
    else:
        desc = f"{n} defect(s) found" if n > 0 else "Unresolved threads remain"
        _try_set_status(owner, repo, commit_sha, "failure", desc)

    print(f"Review posted for PR #{pr}: {final.verdict}")
    return 0


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

    final, invalid_comments = _build_final_result(result, valid_lines, pr)

    owner, repo = get_repo_info()
    commit_sha = pr_meta.head_ref_oid

    if not dry_run:
        _try_set_status(owner, repo, commit_sha, "pending", "Review in progress")

    final, our_existing = _try_dedup(pr, final, invalid_comments, owner, repo)
    auto_resolved_ids = _try_auto_resolve(pr, our_existing, valid_lines, commit_sha)
    final = _block_approval_if_unresolved(final, our_existing, auto_resolved_ids, pr)

    if dry_run:
        _print_dry_run(final)
        return 0

    return _post_and_set_status(
        pr, final, invalid_comments, (owner, repo, commit_sha), project_dir
    )


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


def _process_tool_calls(
    response: LLMResponse,
    messages: list[dict[str, Any]],
    tool_ctx: ToolContext,
    iteration: int,
    model_and_pr: tuple[str, int],
) -> ReviewResult | None:
    """Process tool calls from an agentic LLM response.

    Appends the assistant message and tool results to ``messages``.

    Args:
        model_and_pr: Tuple of (model name, PR number).

    Returns:
        A ReviewResult if submit_review was called, otherwise None.
    """
    model, pr = model_and_pr
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
            iter_num = iteration + 1
            print(f"[agentic] submit_review at iteration {iter_num}")
            return parse_submit_review_args(tc.arguments, model, pr)

        print(f"[agentic] tool: {tc.name}({tc.arguments[:100]}...)")
        tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_result,
            }
        )
    return None


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
    max_iters = config.max_iterations

    for iteration in range(max_iters):
        remaining = max_iters - iteration - 1
        print(f"[agentic] iteration {iteration + 1}/{max_iters}")

        # Force submit_review on the last 2 iterations
        tool_choice: dict[str, Any] | str | None = None
        if remaining <= 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        # Inject a nudge when running low on iterations
        nudge_threshold = 3
        if remaining == nudge_threshold:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "You have 3 iterations remaining. Start wrapping up your "
                        "investigation and prepare to call submit_review."
                    ),
                }
            )

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

        if response.tool_calls:
            submit_result = _process_tool_calls(
                response, messages, tool_ctx, iteration, (config.model, pr)
            )
            if submit_result is not None:
                return submit_result
            continue

        # No tool calls -- model returned content directly (fallback parse)
        if response.content:
            iter_num = iteration + 1
            print(f"[agentic] content response at iteration {iter_num}")
            return parse_response(response.content, config.model, pr)

        # Empty response -- shouldn't happen, but handle gracefully
        print(f"[agentic] empty response at iteration {iteration + 1}")
        break

    # Max iterations exhausted — fall back to oneshot review
    print(f"[agentic] exhausted {max_iters} iterations, falling back to oneshot")
    logger.warning(
        "Agentic loop exhausted %d iterations, falling back to oneshot",
        max_iters,
    )
    return _run_oneshot_review(config, diff, pr_meta, pr)


def _compute_verdict(comments: list[ReviewComment]) -> str:
    """Determine verdict: any comments = request_changes, none = approve."""
    if comments:
        return "request_changes"
    return "approve"


def _fetch_resolve_context(
    pr: int,
) -> tuple[dict[str, set[int]], str, set[str]]:
    """Fetch diff, metadata, and deleted files for resolve operation.

    Returns:
        Tuple of (valid_lines, head_sha, deleted_files).
    """
    pr_meta = get_pr_metadata(pr)
    diff = get_pr_diff(pr)
    valid_lines = parse_diff_hunks(diff)
    head_sha = pr_meta.head_ref_oid

    try:
        deleted = get_deleted_files(pr)
    except RuntimeError:
        logger.warning("Failed to fetch deleted files, assuming none")
        deleted = set()

    return valid_lines, head_sha, deleted


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
    valid_lines, head_sha, deleted = _fetch_resolve_context(pr)

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
