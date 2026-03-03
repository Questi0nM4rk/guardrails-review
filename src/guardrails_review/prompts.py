"""Prompt construction for LLM review requests."""

from __future__ import annotations

import fnmatch
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from guardrails_review.types import (
        PathInstruction,
        PRMetadata,
        ReviewConfig,
        ReviewThread,
    )

_SYSTEM_PROMPT = """\
You are a pedantic defect detector. Review the PR diff and return ONLY valid JSON:

{
  "verdict": "approve" | "request_changes",
  "summary": "1-2 sentence assessment",
  "comments": [
    {
      "path": "relative/file/path",
      "line": <end line number in new file>,
      "start_line": <start line for multi-line comments, optional>,
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
You are a pedantic defect detector and gatekeeper for AI-generated code. Your job is
to find real bugs before they reach the main branch — not to nitpick style, not to
suggest improvements, but to catch defects that will cause failures in production.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MANDATORY: You MUST call submit_review() as your final action.
Never output text and stop. Never say "LGTM" and return.
The ONLY valid exit from this review is calling submit_review().
If you find no issues, call submit_review(verdict="approve", ...).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Workflow

1. Call think() first. Write down: what changed, what the risk areas are, and what
   context you need to gather before you can form a verdict.

2. Read the diff. Line numbers are embedded as LINE_N: — use these exact numbers
   in your comments. Only comment on lines that appear in the diff hunks.

3. Gather context using your tools:
   - list_changed_files() — understand the scope of the PR
   - read_file(path, start_line, end_line) — see the full function/class around a change
   - search_code(query) — find callers, related code, or tests

4. Use at least 2-3 tool calls after think() before submitting, unless the diff is
   trivially small (< 20 lines with no logic changes).

5. Call submit_review() with your findings.

## Defect categories — standard

Report ONLY these. Each comment must cite a specific line and explain the concrete
failure mode (what will break, when, how).

- **Bugs and logic errors**: incorrect conditions, off-by-one, wrong operator, missing
  branch, incorrect algorithm
- **Security vulnerabilities**: injection (SQL, shell, path, LDAP), SSRF, XSS, CSRF,
  broken access control, unsafe deserialization, insecure direct object reference
- **Concurrency and data races**: unsynchronized shared state, TOCTOU, missing locks,
  double-checked locking broken without volatile/atomic
- **Resource leaks**: file handles, DB connections, sockets, memory not released on
  error paths
- **Unhandled error paths**: exceptions swallowed silently, missing null/None checks
  before dereference, missing error returns checked by callers
- **API contract violations**: wrong argument types, missing required fields, broken
  invariants, calling deprecated/removed methods

## Defect categories — AI-generated code (check these carefully)

AI agents produce characteristic failure patterns. Prioritize:

- **Hallucinated APIs**: calls to library methods, attributes, or modules that do not
  exist in the imported package version. Check: does this method/attribute actually
  exist? Is the import correct?
- **Unnecessary abstractions**: factory classes, plugin registries, base classes, or
  strategy patterns introduced for single-use cases. The right question: could this
  be a plain function? If yes, the abstraction is waste and increases failure surface.
- **Missing idempotency**: code that produces duplicate side effects on re-run —
  INSERT without ON CONFLICT, file creation without existence check, API calls without
  deduplication keys. AI code is often run multiple times during iteration.
- **Copy-paste insecurity**: SQL built by string concatenation, shell commands with
  f-string interpolation, template reuse from an insecure example. AI models
  pattern-match from training data that includes vulnerable examples.
- **Hardcoded secrets**: API keys, passwords, tokens, private keys, connection strings
  embedded literally in source. Grep the diff for anything that looks like a secret.
- **Weak or broken cryptography**: MD5/SHA1 for security-sensitive hashing, ECB mode,
  small key sizes, predictable RNG (random.random() for tokens), self-signed cert
  acceptance, disabled TLS verification.
- **Missing input validation at trust boundaries**: functions that accept user-supplied
  or external data without validating length, format, range, or type before use.
  AI models often omit validation when prototyping.
- **Over-scoped permissions**: requesting admin/root/wildcard permissions when a
  narrower scope would suffice. AI agents tend to request broad access for convenience.

## Do NOT report

- Style, formatting, naming, line length
- "Consider doing X instead" suggestions
- Missing tests or missing documentation
- Type annotation gaps (unless they mask a runtime bug)
- Performance, unless it is a clear algorithmic bug (e.g. O(n^2) in a hot loop with
  evidence this is a hot loop)
- Issues that already appear in "Existing Unresolved Review Comments" (see below)

## Line number rules

- The diff embeds right-side line numbers as LINE_N: prefixes
- Only use line numbers from the diff — do not invent or estimate line numbers
- For multi-line issues, use start_line (first line) and line (last line)
- Do not post comments on lines that are not in the diff hunks

## Summary format

Start your review summary with the HTML comment: <!-- guardrails-review -->
Then give a 1-3 sentence assessment of the PR risk level and what you found.\
"""


def _match_path_instructions(
    changed_files: list[str],
    path_instructions: list[PathInstruction],
) -> list[PathInstruction]:
    """Return path instructions whose glob matches at least one changed file."""
    return [
        pi for pi in path_instructions if any(fnmatch.fnmatch(f, pi.path) for f in changed_files)
    ]


def _build_user_content(  # noqa: PLR0913
    diff: str,
    config: ReviewConfig,
    pr_meta: PRMetadata,
    memory_context: str = "",
    previous_comments: list[ReviewThread] | None = None,
    changed_files: list[str] | None = None,
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

    # Inject matched path instructions before diff
    matched_pi = _match_path_instructions(
        changed_files or [],
        config.path_instructions,
    )
    if matched_pi:
        pi_lines = ["## Path-Specific Review Rules", ""]
        for pi in matched_pi:
            pi_lines.append(f"### Files matching `{pi.path}`")
            pi_lines.append(pi.instructions)
            pi_lines.append("")
        parts = [*pi_lines, *parts]

    # Inject previous unresolved comments before diff
    if previous_comments:
        marker = "<!-- guardrails-review -->"
        comment_lines = [
            "## Existing Unresolved Review Comments (do not repeat these)",
            "",
        ]
        for t in previous_comments:
            body_stripped = t.body.replace(marker, "").strip()
            body_short = body_stripped[:120]
            line_ref = f"{t.path}:{t.line}" if t.line is not None else t.path
            comment_lines.append(f"- `{line_ref}` — {body_short}")
        comment_lines.append("")
        parts = [*comment_lines, *parts]

    if config.extra_instructions:
        parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *parts,
        ]
    if memory_context:
        parts = [
            f"## Project Memory\n\n{memory_context}",
            "",
            *parts,
        ]
    return "\n".join(parts)


def build_messages(
    diff: str,
    config: ReviewConfig,
    pr_meta: PRMetadata,
    memory_context: str = "",
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _build_user_content(diff, config, pr_meta, memory_context),
        },
    ]


def build_agentic_messages(  # noqa: PLR0913
    diff: str,
    config: ReviewConfig,
    pr_meta: PRMetadata,
    memory_context: str = "",
    previous_comments: list[ReviewThread] | None = None,
    changed_files: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _build_user_content(
                diff,
                config,
                pr_meta,
                memory_context,
                previous_comments=previous_comments,
                changed_files=changed_files,
            ),
        },
    ]
