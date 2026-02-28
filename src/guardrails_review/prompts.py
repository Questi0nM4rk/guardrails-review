"""Prompt construction for LLM review requests."""

from __future__ import annotations

import base64
import logging
import re
from typing import TYPE_CHECKING, Any

from guardrails_review.github import run_gh

if TYPE_CHECKING:
    from guardrails_review.types import PRMetadata, ReviewConfig

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
You are a pedantic defect detector with tools to explore the codebase.

**Workflow:**
1. Start with list_changed_files() to see the scope
2. Read the diff carefully — most defects are visible in the diff alone
3. Use read_file() ONLY for files where you need surrounding context to confirm a bug
4. Use search_code() ONLY when you need to verify callers or contracts
5. Use post_comments() to post findings IMMEDIATELY as you find them — do not accumulate
6. Call finish_review() when you have no more files to investigate

**IMPORTANT:** Post findings as you go. Do not wait until the end. Each call to \
post_comments() posts inline comments to the PR immediately. Your budget status \
will be shown each iteration — when warned to wrap up, finish outstanding files \
and call finish_review().

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
- Include <!-- guardrails-review --> at the start of each comment body\
"""


def _build_user_content(
    diff: str,
    config: ReviewConfig,
    pr_meta: PRMetadata,
    *,
    ci_context: str = "",
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
    if ci_context:
        parts.append("")
        parts.append(f"## CI/CD context\n\n{ci_context}")
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
    *,
    ci_context: str = "",
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _build_user_content(
                diff, config, pr_meta, ci_context=ci_context
            ),
        },
    ]


def build_ci_context(owner: str, repo: str, commit_sha: str) -> str:
    """Extract CI/CD context from ``.pre-commit-config.yaml`` in the repo.

    Uses regex extraction (no YAML dependency).  Best-effort: returns
    empty string on any error.

    Args:
        owner: Repository owner.
        repo: Repository name.
        commit_sha: Commit SHA to read the file at.

    Returns:
        Formatted string of hook IDs and versions, or empty string.
    """
    try:
        proc = run_gh(
            "api",
            f"repos/{owner}/{repo}/contents/.pre-commit-config.yaml",
            "-q",
            ".content",
            "--method",
            "GET",
            "-f",
            f"ref={commit_sha}",
        )
        content = base64.b64decode(proc.stdout.strip()).decode(errors="replace")
    except (RuntimeError, ValueError, UnicodeDecodeError):
        return ""

    hook_ids = re.findall(r"- id: (\S+)", content)
    revs = re.findall(r"rev: (\S+)", content)

    if not hook_ids:
        return ""

    parts = ["Pre-commit hooks:"]
    for i, hook_id in enumerate(hook_ids):
        rev = revs[i] if i < len(revs) else "unknown"
        parts.append(f"  - {hook_id} ({rev})")

    return "\n".join(parts)
