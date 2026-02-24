"""Prompt construction for LLM review requests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from guardrails_review.types import PRMetadata, ReviewConfig

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


def _build_user_content(
    diff: str,
    config: ReviewConfig,
    pr_meta: PRMetadata,
) -> str:
    """Build the user message content shared by oneshot and agentic modes."""
    parts = [
        f"# PR: {pr_meta.title or 'Untitled'}",
        "",
        pr_meta.body or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *parts,
        ]
    return "\n".join(parts)


def build_messages(
    diff: str,
    config: ReviewConfig,
    pr_meta: PRMetadata,
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_content(diff, config, pr_meta)},
    ]


def build_agentic_messages(
    diff: str,
    config: ReviewConfig,
    pr_meta: PRMetadata,
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_content(diff, config, pr_meta)},
    ]
