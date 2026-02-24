"""Core review orchestrator: diff -> LLM -> validate -> post."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from guardrails_review.cache import save_review
from guardrails_review.config import load_config
from guardrails_review.diff import parse_diff_hunks
from guardrails_review.github import get_pr_diff, get_pr_metadata, get_repo_info, post_review
from guardrails_review.llm import call_openrouter
from guardrails_review.types import ReviewComment, ReviewConfig, ReviewResult

if TYPE_CHECKING:
    from pathlib import Path

_SYSTEM_PROMPT = """\
You are a code reviewer. Review the PR diff and return ONLY valid JSON:

{
  "verdict": "approve" | "request_changes",
  "summary": "1-2 sentence assessment",
  "comments": [
    {
      "path": "relative/file/path",
      "line": <line number in new file>,
      "severity": "error" | "warning" | "info",
      "body": "review comment"
    }
  ]
}

Rules:
- Line numbers reference the new file (right side of diff, + or space-prefixed lines)
- Only comment on lines within diff hunks
- "error" = must fix before merge, "warning" = should fix, "info" = suggestion
- Empty comments + "approve" = no issues found
- Do NOT flag style/formatting (handled by linters and pre-commit hooks)
- Do NOT flag missing tests unless a critical code path has zero coverage
- Include a <!-- guardrails-review --> HTML comment at the start of the summary\
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

    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
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

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    messages = build_messages(diff, config, pr_meta)
    raw_response = call_openrouter(messages, config.model)
    result = parse_response(raw_response, config.model, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

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


def _compute_verdict(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = {"error"}
    if config.severity_threshold == "warning":
        blocking.add("warning")

    has_blocking = any(c.severity in blocking for c in comments)

    if has_blocking:
        return "request_changes"
    if config.auto_approve:
        return "approve"
    return "request_changes"


def _print_dry_run(result: ReviewResult) -> None:
    """Print review result to stdout without posting."""
    print(f"=== Dry Run: PR #{result.pr} ===")
    print(f"Verdict: {result.verdict}")
    print(f"Model: {result.model}")
    print(f"\n{result.summary}")
    if result.comments:
        print(f"\n--- {len(result.comments)} inline comment(s) ---")
        for c in result.comments:
            print(f"  [{c.severity}] {c.path}:{c.line} — {c.body}")
