"""Core review orchestrator: diff -> LLM -> validate -> post."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from typing import TYPE_CHECKING, Any

from guardrails_review.cache import save_review
from guardrails_review.config import load_config
from guardrails_review.diff import format_diff_with_lines, parse_diff_hunks
from guardrails_review.github import (
    DiffTooLargeError,
    enable_auto_merge,
    get_deleted_files,
    get_pr_diff,
    get_pr_metadata,
    get_repo_info,
    post_inline_comments,
    post_review,
    resolve_thread,
    set_commit_status,
)
from guardrails_review.llm import call_openrouter, call_openrouter_tools
from guardrails_review.memory import (
    build_memory_context,
    load_memory,
    save_memory,
    update_from_review,
)
from guardrails_review.models import get_model_context_length
from guardrails_review.parser import parse_response
from guardrails_review.prompts import (
    build_agentic_messages,
    build_ci_context,
    build_messages,
)
from guardrails_review.threads import (
    deduplicate_comments,
    find_resolvable_threads,
    get_our_threads,
    get_review_threads,
)
from guardrails_review.tools import TOOL_DEFINITIONS, ToolContext, execute_tool
from guardrails_review.types import (
    REVIEW_MARKER,
    ReviewComment,
    ReviewResult,
    TokenBudget,
)

if TYPE_CHECKING:
    from pathlib import Path

    from guardrails_review.types import (
        LLMResponse,
        PRMetadata,
        ReviewConfig,
        ReviewThread,
        ToolCall,
    )

logger = logging.getLogger(__name__)

_MAX_TIMEOUT_RETRIES = 2
_PREMATURE_SUBMIT_MIN_TOOLS = 2
_PREMATURE_SUBMIT_DIFF_THRESHOLD = 100
_NO_PROGRESS_LIMIT = 2


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
        end_line_ok = c.line in file_lines
        start_line_ok = c.start_line is None or c.start_line in file_lines
        if end_line_ok and start_line_ok:
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
    our_existing: list[ReviewThread],
) -> ReviewResult:
    """Deduplicate comments against existing threads."""
    try:
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
        logger.warning("Failed to deduplicate comments (non-fatal)")

    return final


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


def run_review(  # noqa: PLR0915
    pr: int,
    *,
    dry_run: bool = False,
    verbose: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    try:
        diff = get_pr_diff(pr)
    except DiffTooLargeError as exc:
        logger.warning("%s", exc)
        owner, repo = get_repo_info()
        pr_meta = get_pr_metadata(pr)
        set_commit_status(owner, repo, pr_meta.head_ref_oid, "success", str(exc))
        return 0
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    owner, repo = get_repo_info()
    memory = load_memory(owner, repo)
    memory_context = build_memory_context(memory)

    # Fetch threads once — used for both previous_comments injection and dedup
    our_existing: list[ReviewThread] = []
    try:
        all_threads = get_review_threads(pr, owner, repo)
        our_existing = get_our_threads(all_threads)
    except RuntimeError:
        logger.warning("Failed to fetch review threads (non-fatal)")

    previous_comments = [t for t in our_existing if not t.is_resolved]

    if config.agentic:
        result = _run_agentic_review(
            config,
            diff,
            pr_meta,
            pr,
            owner=owner,
            repo=repo,
            memory_context=memory_context,
            previous_comments=previous_comments,
            valid_lines=valid_lines,
            verbose=verbose,
        )
    else:
        result = _run_oneshot_review(
            config, diff, pr_meta, pr, memory_context=memory_context
        )

    final, invalid_comments = _build_final_result(result, valid_lines, pr)

    commit_sha = pr_meta.head_ref_oid

    if not dry_run:
        _try_set_status(owner, repo, commit_sha, "pending", "Review in progress")

    # Deduplicate comments against pre-fetched threads
    final = _try_dedup(pr, final, invalid_comments, our_existing)

    # Auto-resolve stale threads before posting
    auto_resolved_ids = _try_auto_resolve(pr, our_existing, valid_lines, commit_sha)
    final = _block_approval_if_unresolved(final, our_existing, auto_resolved_ids, pr)

    if dry_run:
        _print_dry_run(final)
        return 0

    try:
        post_review(pr, final, owner, repo, commit_sha)
    except RuntimeError as exc:
        logger.exception("Failed to post review")
        print(f"Error posting review: {exc}")
        _try_set_status(owner, repo, commit_sha, "error", "Review post failed")
        return 1

    save_review(final, project_dir)

    # Update and persist memory after review
    updated_memory = update_from_review(memory, final, our_existing)
    save_memory(updated_memory)

    # Set final commit status
    n = len(final.comments) + len(invalid_comments)
    if final.verdict == "approve":
        _try_set_status(owner, repo, commit_sha, "success", "Approved")
        if config.auto_merge and not dry_run:
            enable_auto_merge(pr, merge_method=config.merge_method)
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
    memory_context: str = "",
) -> ReviewResult:
    """Run the original single-shot review (diff -> LLM JSON -> result)."""
    messages = build_messages(diff, config, pr_meta, memory_context=memory_context)
    raw_response = call_openrouter(messages, config.model)
    return parse_response(raw_response, config.model, pr)


def _nudge_empty_stop() -> dict[str, str]:
    return {
        "role": "user",
        "content": (
            "You stopped without calling submit_review(). "
            "You MUST call submit_review() to complete the review. "
            "If the code looks clean, call submit_review(verdict='approve', ...). "
            "Please submit your review now."
        ),
    }


def _nudge_premature_submit(tool_use_count: int, diff_lines: int) -> dict[str, str]:
    return {
        "role": "user",
        "content": (
            f"You called submit_review() after only {tool_use_count} tool use(s) "
            f"on a diff with {diff_lines} lines. "
            "Please investigate more thoroughly — use read_file() to examine the "
            "changed functions in full context, or search_code() to check callers. "
            "You may call submit_review() again when ready."
        ),
    }


def _count_diff_lines(diff: str) -> int:
    """Count right-side lines (additions + context) in a unified diff."""
    return sum(
        1
        for line in diff.splitlines()
        if line.startswith((" ", "+")) and not line.startswith("+++")
    )


def _print_iteration(iteration: int, response: LLMResponse) -> None:
    """Print a human-readable summary of one agentic loop iteration to stdout."""
    import json as _json  # noqa: PLC0415

    tool_names = [tc.name for tc in response.tool_calls]
    print(
        f"\n[iter {iteration}] finish={response.finish_reason!r} "
        f"tools={tool_names} content_len={len(response.content or '')}",
        flush=True,
    )
    if response.content:
        print(f"  reasoning: {response.content[:500]}", flush=True)
    for tc in response.tool_calls:
        if tc.name == "think":
            args = _json.loads(tc.arguments)
            reasoning = args.get("reasoning", "")
            print(f"  [think] {reasoning[:800]}", flush=True)
        elif tc.name != "submit_review":
            print(f"  [{tc.name}] {tc.arguments[:200]}", flush=True)
        else:
            print("  [submit_review] (verdict in output below)", flush=True)


def _validate_and_post(
    raw_arguments: str,
    valid_lines: dict[str, set[int]],
    existing_threads: list[ReviewThread],
    all_posted: list[ReviewComment],
    tool_ctx: ToolContext,
) -> tuple[list[ReviewComment], str]:
    """Validate, deduplicate, and post a batch of inline comments.

    Args:
        raw_arguments: JSON string with ``comments`` array from the LLM.
        valid_lines: Mapping of file path to set of valid diff line numbers.
        existing_threads: Existing review threads for deduplication.
        all_posted: Comments already posted this session.
        tool_ctx: GitHub context (pr, owner, repo, commit_sha).

    Returns:
        Tuple of (newly posted comments, tool result message for LLM).
    """
    args = json.loads(raw_arguments)
    raw_comments = args.get("comments", [])

    # Build ReviewComment objects with the marker
    candidates: list[ReviewComment] = []
    for c in raw_comments:
        path = c.get("path", "")
        line = c.get("line", 0)
        body = c.get("body", "")
        if not path or not line:
            continue
        if REVIEW_MARKER not in body:
            body = f"{REVIEW_MARKER}\n{body}"
        candidates.append(
            ReviewComment(
                path=path,
                line=line,
                body=body,
                severity="error",
                start_line=c.get("start_line"),
            )
        )

    # Validate against diff lines
    valid, invalid = validate_comments(candidates, valid_lines)

    # Deduplicate against existing threads + already-posted
    already_posted_set = {(c.path, c.line) for c in all_posted}
    existing_set = {(t.path, t.line) for t in existing_threads if not t.is_resolved}
    deduped = [
        c
        for c in valid
        if (c.path, c.line) not in already_posted_set
        and (c.path, c.line) not in existing_set
    ]

    if deduped:
        post_inline_comments(
            tool_ctx.pr, deduped, tool_ctx.owner, tool_ctx.repo, tool_ctx.commit_sha
        )

    # Build feedback message for the LLM
    parts = [f"Posted {len(deduped)} comment(s)."]
    if invalid:
        dropped = [f"{c.path}:{c.line}" for c in invalid]
        parts.append(f"Dropped {len(invalid)} comment(s) on invalid lines: {dropped}")
    if len(valid) - len(deduped) > 0:
        parts.append(f"Skipped {len(valid) - len(deduped)} duplicate(s).")
    return deduped, " ".join(parts)


@dataclass
class _AgenticState:
    """Mutable state for the agentic review loop."""

    messages: list[dict[str, Any]]
    valid_lines: dict[str, set[int]]
    existing_threads: list[ReviewThread]
    all_posted: list[ReviewComment]
    tool_ctx: ToolContext
    budget: TokenBudget
    no_progress_streak: int = 0
    budget_warning_sent: bool = False


def _dispatch_tool_call(
    tc: ToolCall,
    state: _AgenticState,
    iteration: int,
) -> bool:
    """Dispatch a single tool call and append tool result to messages.

    Returns True if ``finish_review`` was requested.
    """
    if tc.name == "finish_review":
        print(f"[agentic] finish_review at iteration {iteration + 1}")
        state.messages.append(
            {"role": "tool", "tool_call_id": tc.id, "content": "Review complete."}
        )
        return True

    if tc.name == "post_comments":
        new, feedback = _validate_and_post(
            tc.arguments,
            state.valid_lines,
            state.existing_threads,
            state.all_posted,
            state.tool_ctx,
        )
        state.all_posted.extend(new)
        n_total = len(state.all_posted)
        print(f"[agentic] posted {len(new)} comment(s) (total: {n_total})")
        state.messages.append(
            {"role": "tool", "tool_call_id": tc.id, "content": feedback}
        )
        return False

    # think, read_file, search_code, list_changed_files
    print(f"[agentic] tool: {tc.name}({tc.arguments[:80]}...)")
    tool_result = execute_tool(tc.name, tc.arguments, state.tool_ctx)
    state.messages.append(
        {"role": "tool", "tool_call_id": tc.id, "content": tool_result}
    )
    return False


def _inject_budget_messages(state: _AgenticState) -> None:
    """Inject budget status (and optional wrap-up warning) into messages."""
    budget = state.budget
    budget_msg = (
        f"[Budget: {budget.last_prompt_tokens:,} / {budget.max_tokens:,} "
        f"tokens. Remaining: ~{budget.remaining:,}]"
    )
    state.messages.append({"role": "user", "content": budget_msg})

    if budget.at_threshold(0.85) and not state.budget_warning_sent:
        state.messages.append(
            {
                "role": "user",
                "content": (
                    "You are at 85% of your token budget. Wrap up your "
                    "investigation. Post any remaining findings and call "
                    "finish_review()."
                ),
            }
        )
        state.budget_warning_sent = True


def _run_agentic_review(  # noqa: PLR0913, PLR0912, PLR0915, C901
    config: ReviewConfig,
    diff: str,
    pr_meta: PRMetadata,
    pr: int,
    owner: str = "",
    repo: str = "",
    memory_context: str = "",
    previous_comments: list[ReviewThread] | None = None,
    valid_lines: dict[str, set[int]] | None = None,
    verbose: bool = False,  # noqa: FBT001, FBT002
) -> ReviewResult:
    """Run the agentic tool-use review loop with incremental posting.

    Inline comments are posted to GitHub as they are found via post_comments().
    Falls back to oneshot on tool-use API errors or repeated timeouts.
    The returned ReviewResult has comments=[] because they are already posted.
    """
    if not owner or not repo:
        owner, repo = get_repo_info()
    commit_sha = pr_meta.head_ref_oid
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    changed_files = list(valid_lines.keys()) if valid_lines else []
    diff_lines = _count_diff_lines(diff)
    formatted_diff = format_diff_with_lines(diff)

    ctx_length = get_model_context_length(config.model)
    budget = TokenBudget(
        max_tokens=int(ctx_length * 0.80),
        reserve_tokens=int(ctx_length * 0.15),
    )

    existing_threads: list[ReviewThread] = []
    try:
        all_threads = get_review_threads(pr, owner, repo)
        existing_threads = get_our_threads(all_threads)
    except RuntimeError:
        logger.warning("Failed to fetch threads for dedup (non-fatal)")

    ci_context = build_ci_context(owner, repo, commit_sha)
    messages: list[dict[str, Any]] = build_agentic_messages(
        formatted_diff,
        config,
        pr_meta,
        memory_context=memory_context,
        previous_comments=previous_comments,
        changed_files=changed_files,
        ci_context=ci_context,
    )

    state = _AgenticState(
        messages=messages,
        valid_lines=valid_lines or parse_diff_hunks(diff),
        existing_threads=existing_threads,
        all_posted=[],
        tool_ctx=tool_ctx,
        budget=budget,
    )

    timeout_retries = 0
    tool_use_count = 0
    premature_submit_warned = False
    no_progress_streak = 0

    for iteration in range(config.max_iterations):
        if not state.budget.can_continue():
            print(f"[agentic] budget exhausted at iteration {iteration + 1}")
            break

        _inject_budget_messages(state)
        print(f"[agentic] iteration {iteration + 1}/{config.max_iterations}")

        try:
            response = call_openrouter_tools(
                state.messages,
                config.model,
                tools=TOOL_DEFINITIONS,
            )
            timeout_retries = 0
            if verbose:
                _print_iteration(iteration, response)
        except TimeoutError:
            timeout_retries += 1
            logger.warning(
                "Agentic API timeout (attempt %d/%d)",
                timeout_retries,
                _MAX_TIMEOUT_RETRIES,
            )
            if timeout_retries > _MAX_TIMEOUT_RETRIES:
                logger.warning("Too many timeouts, falling back to oneshot review")
                return _run_oneshot_review(
                    config, diff, pr_meta, pr, memory_context=memory_context
                )
            continue
        except RuntimeError:
            if state.all_posted:
                logger.warning(
                    "Agentic API call failed mid-loop; returning partial result"
                )
                verdict = "request_changes"
                summary = _build_agentic_summary(state.all_posted, state.budget)
                return ReviewResult(
                    verdict=verdict,
                    summary=summary,
                    comments=[],
                    model=config.model,
                    pr=pr,
                )
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(
                config, diff, pr_meta, pr, memory_context=memory_context
            )

        state.budget.record(response.usage)

        # No tool calls — model returned content or nothing
        if not response.tool_calls:
            if response.content:
                if response.finish_reason == "stop":
                    logger.info(
                        "Iter %d: content+stop without finish_review, nudging",
                        iteration,
                    )
                    state.messages.append(
                        {"role": "assistant", "content": response.content}
                    )
                    state.messages.append(_nudge_empty_stop())
                    continue
            else:
                # Truly empty response (no content, no tool calls)
                no_progress_streak += 1
                logger.info(
                    "Iter %d: empty response (finish_reason=%s), nudging (streak=%d)",
                    iteration,
                    response.finish_reason,
                    no_progress_streak,
                )
                if no_progress_streak >= _NO_PROGRESS_LIMIT:
                    logger.warning(
                        "No progress after %d consecutive empty"
                        " iterations; terminating",
                        no_progress_streak,
                    )
                    break
                state.messages.append(_nudge_empty_stop())
            continue

        _append_assistant_tool_msg(state.messages, response)
        no_progress_streak = 0

        done = False
        for tc in response.tool_calls:
            if tc.name == "finish_review":
                print(f"[agentic] finish_review at iteration {iteration + 1}")
                state.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": "Review complete.",
                    }
                )
                done = True
                break

            if tc.name == "post_comments":
                # Check for premature finish (too few tool uses on large diff)
                if (
                    not premature_submit_warned
                    and tool_use_count < _PREMATURE_SUBMIT_MIN_TOOLS
                    and diff_lines > _PREMATURE_SUBMIT_DIFF_THRESHOLD
                    and not state.all_posted
                ):
                    premature_submit_warned = True
                    logger.info(
                        "Premature post_comments after %d tool use(s)"
                        " on %d-line diff; nudging",
                        tool_use_count,
                        diff_lines,
                    )
                    state.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": (
                                "Please investigate more thoroughly before posting. "
                                "Use read_file() or search_code() first."
                            ),
                        }
                    )
                    state.messages.append(
                        _nudge_premature_submit(tool_use_count, diff_lines)
                    )
                    break

                new, feedback = _validate_and_post(
                    tc.arguments,
                    state.valid_lines,
                    state.existing_threads,
                    state.all_posted,
                    state.tool_ctx,
                )
                state.all_posted.extend(new)
                n_total = len(state.all_posted)
                print(f"[agentic] posted {len(new)} comment(s) (total: {n_total})")
                state.messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": feedback}
                )
                continue

            tool_use_count += 1
            tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
            state.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result,
                }
            )

        if done:
            break

    verdict = "request_changes" if state.all_posted else "approve"
    summary = _build_agentic_summary(state.all_posted, state.budget)
    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=[],
        model=config.model,
        pr=pr,
    )


def _append_assistant_tool_msg(
    messages: list[dict[str, Any]],
    response: LLMResponse,
) -> None:
    """Append the assistant message with tool_calls to the conversation."""
    assistant_msg: dict[str, Any] = {
        "role": "assistant",
        "content": response.content,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": tc.arguments,
                },
            }
            for tc in response.tool_calls
        ],
    }
    messages.append(assistant_msg)


def _build_agentic_summary(
    all_posted: list[ReviewComment],
    budget: TokenBudget,
) -> str:
    """Build a summary for the final agentic review."""
    parts = [REVIEW_MARKER]
    n = len(all_posted)
    if n > 0:
        parts.append(f"\n{n} defect(s) found and posted as inline comments.")
    else:
        parts.append("\nNo defects found.")
    parts.append(
        f"\n\n*Budget: {budget.last_prompt_tokens:,} / "
        f"{budget.max_tokens:,} tokens used.*"
    )
    return "".join(parts)


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
