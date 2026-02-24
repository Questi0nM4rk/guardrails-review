"""Core review orchestrator: diff -> LLM -> validate -> post."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from guardrails_review.cache import save_review
from guardrails_review.config import load_config
from guardrails_review.diff import parse_diff_hunks
from guardrails_review.github import get_pr_diff, get_pr_metadata, get_repo_info, post_review
from guardrails_review.llm import call_openrouter, call_openrouter_tools
from guardrails_review.tools import TOOL_DEFINITIONS, ToolContext, execute_tool
from guardrails_review.types import ReviewComment, ReviewConfig, ReviewResult

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a pedantic defect detector. Review the PR diff and return ONLY valid JSON:

{
  "verdict": "approve" | "request_changes",
  "summary": "1-2 sentence assessment",
  "comments": [
    {
      "path": "relative/file/path",
      "line": <line number in new file>,
      "body": "description of the defect"
    }
  ]
}

**ONLY report these defect categories:**
- Bugs and logic errors
- Security vulnerabilities
- Data races and concurrency issues
- Resource leaks (file handles, connections, memory)
- Unhandled error paths (missing error checks, swallowed exceptions)
- API contract violations (wrong types, missing required fields, broken invariants)

**Do NOT report:**
- Style, formatting, or naming
- "Consider doing X" suggestions
- Missing tests or documentation
- Performance unless it's a clear algorithmic bug (e.g. O(n^2) in a hot path)

Rules:
- Line numbers reference the new file (right side of diff, + or space-prefixed lines)
- Only comment on lines within diff hunks
- Empty comments + "approve" = no issues found
- Include a <!-- guardrails-review --> HTML comment at the start of the summary\
"""

_AGENTIC_SYSTEM_PROMPT = """\
You are a pedantic defect detector with tools to explore the codebase before submitting.

**Workflow:**
1. First, examine the diff to understand what changed
2. Use your tools to gather context:
   - read_file() to see full file context around changes
   - list_changed_files() to see all files in the PR
   - search_code() to find related code, callers, or tests
3. When you have enough context, call submit_review() with your findings

**ONLY report these defect categories:**
- Bugs and logic errors
- Security vulnerabilities
- Data races and concurrency issues
- Resource leaks (file handles, connections, memory)
- Unhandled error paths (missing error checks, swallowed exceptions)
- API contract violations (wrong types, missing required fields, broken invariants)

**Do NOT report:**
- Style, formatting, or naming
- "Consider doing X" suggestions
- Missing tests or documentation
- Performance unless it's a clear algorithmic bug

Rules:
- Line numbers reference the new file (right side of diff)
- Only comment on lines within diff hunks
- Include <!-- guardrails-review --> at the start of your summary\
"""

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def build_messages(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def build_agentic_messages(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def parse_response(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def parse_submit_review_args(arguments: str, model: str, pr: int) -> ReviewResult:
    """Parse the submit_review tool call arguments into a ReviewResult."""
    timestamp = datetime.now(tz=UTC).isoformat()
    parsed = json.loads(arguments)
    return _build_result_from_parsed(parsed, model, pr, timestamp)


def _build_result_from_parsed(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    _marker = "<!-- guardrails-review -->"
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=(
                f"{_marker}\n{c.get('body', '')}"
                if _marker not in c.get("body", "")
                else c.get("body", "")
            ),
            severity="error",
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def _try_parse_json(raw: str) -> dict | None:
    """Attempt to parse JSON, trying raw first then extracting from code blocks."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    match = _JSON_BLOCK_RE.search(raw)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    return None


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
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
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

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def _run_oneshot_review(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = build_messages(diff, config, pr_meta)
    raw_response = call_openrouter(messages, config.model)
    return parse_response(raw_response, config.model, pr)


def _run_agentic_review(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
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

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def _compute_verdict(comments: list[ReviewComment]) -> str:
    """Determine verdict: any comments = request_changes, none = approve."""
    if comments:
        return "request_changes"
    return "approve"


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
