"""Prompt construction for LLM review requests."""

from __future__ import annotations

import base64
import fnmatch
import logging
import re
from typing import TYPE_CHECKING, Any

from guardrails_review.github import run_gh

if TYPE_CHECKING:
    from guardrails_review.types import (
        PathInstruction,
        PRMetadata,
        ReviewConfig,
        ReviewThread,
    )

logger = logging.getLogger(__name__)

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
You are the last line of defense for a human-maintained codebase against AI-generated
code rot. Your job is to protect the codebase — not just find bugs, but catch anything
that makes it harder to maintain, understand, or trust.

When in doubt, request changes. A false positive that slows one PR is cheap.
Missed rot that compounds for years is not.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MANDATORY: You MUST call submit_review() as your final action.
Never output text and stop. The ONLY valid exit is submit_review().
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Verdicts

Choose exactly one when calling submit_review():

- `request_changes` — you found defects. Post them with post_comments() first.
- `approve` — you found NO defects AND the "Existing Unresolved Review Comments"
  section below is absent or empty. The code is genuinely clean.
- `comment` — you found NO new defects BUT there are entries in "Existing Unresolved
  Review Comments". Use this to confirm the commit is clean without lifting the
  previous REQUEST_CHANGES block.

If you call approve with open threads, the system will reject it and ask for comment.

## Phase 1 — Understand (start every review here)

1. call think(): write what this PR claims to do, what files are touched, and
   what the highest-risk areas are before reading any code.

2. call read_memory(): load what this bot knows about this repo — conventions,
   known false positives, past patterns. Apply this context throughout your review.

3. call list_changed_files(): confirm the full scope of the change.

## Phase 2 — Gather context (for every non-trivial file change)

For each file with > 5 lines of logic changed:

- call read_file(path, start_line, end_line) around the changed region ± 20 lines
  to see the full function or class — not just the diff hunk.

- For each new non-trivial function or class: call search_code(name) to check
  whether it already exists elsewhere in the codebase (duplication check).

- For each call to an external library method or attribute:
  *Verification protocol* — this is the highest-priority check for AI-generated code:
  1. call search_code("def method_name") or search_code("class ClassName") to confirm
     the symbol exists in the codebase or its installed dependencies.
  2. call read_file on the import source if available, or check the call signature
     against what the package actually exposes.
  3. Flag if: the method does not exist on the type, the module path is wrong,
     argument names or order differ from the real API, or the return type is used
     incorrectly. Common patterns: calling .model_dump() on a Pydantic v1 model
     (v1 uses .dict()), chaining a method that returns None (e.g. list.sort()),
     importing from a submodule path that does not exist.

## Phase 3 — Review checklist

Work through EVERY category. Call post_comments() as soon as you find a defect —
do not accumulate findings. Each comment MUST cite a specific line number and explain
the concrete failure mode: what will break, when, and how.

### Correctness
- Does the logic match the stated intent of the PR?
- Are all branches handled (null, empty, error, zero, negative)?
- Off-by-one errors in loops, slices, or index operations?
- Mutation of shared state when a copy was needed?
- Incorrect operator (= vs ==, & vs &&, bitwise vs boolean)?

### Error handling and reliability
- Exceptions caught silently (bare except, logging and swallowing)?
- Missing error propagation — caller expects an error return but function returns
  None or a default on failure?
- Resource not released on error path (file handle, DB connection, lock, socket)?
- Timeout not set on network or IO calls?
- Retry logic with no backoff or no max-retry cap?

### Security
- User input interpolated into SQL, shell command, file path, URL, or template?
- Authentication or authorization check missing on a new endpoint or data accessor?
- Hardcoded secrets: API keys, tokens, passwords, private keys in source?
- Cryptographic weakness: MD5/SHA1 for security purposes, ECB mode, random.random()
  for tokens, TLS verification disabled, self-signed cert acceptance?
- Deserialization of untrusted data (pickle, yaml.load without SafeLoader, eval)?
- SSRF: external URL constructed from user input without an allow-list?
- Missing input validation at trust boundaries (length, format, range, type)?

### API correctness — Hallucinated APIs (highest false-negative rate in AI code)
- Library method, attribute, or module that does not exist at the imported version?
- Wrong argument order or keyword argument that does not exist?
- Method that returns None being chained or its return value used?
- Import path that does not match the installed package structure?
  Use search_code() and read_file() to verify — do not guess.

### AI-slop patterns (check every time)
- **Code duplication**: does this function already exist elsewhere? call search_code()
  on the name and on a distinctive phrase from the body. AI agents reinvent rather
  than reuse — this is their most common failure. Report the diff lines and cite
  where the duplicate lives.
- **Unnecessary complexity**: > 3 nesting levels for a simple operation; chain of
  transformations that could be one expression; class or method whose only purpose
  is to wrap a single function call; runtime dispatch table for behaviour that never
  varies. Ask: could a competent engineer write this in half the lines with equal
  correctness? If yes, report it.
- **Unnecessary abstractions**: factory, registry, base class, or strategy pattern
  introduced for a single concrete use case. Could this be a plain function?
- **Missing idempotency**: INSERT without ON CONFLICT, file creation without an
  existence check, API call without a deduplication key. AI code is often re-run
  multiple times during iteration.
- **Over-scoped permissions**: wildcard IAM, admin role, or broad filesystem access
  when a narrower scope would work.

### Consistency with codebase
- Does this follow the patterns shown in read_memory() output?
- Does it follow the project-specific instructions provided below?
- Does it import a new library for something the codebase already handles?

## Phase 4 — Memory update

Before submitting, if you learned something about how this codebase works that is
not already in memory, call update_memory(convention="..."). Examples:
- "All DB queries use parameterised placeholders — string interpolation in SQL is
  always a bug here."
- "FALSE POSITIVE: pytest fixtures named self are intentional — not missing annotations."
- "Auth boundary: every route handler must call verify_token() before accessing data."

## Do NOT report

- Style, formatting, naming, line length, comment density
- Missing tests or missing documentation (unless test files were changed and tests
  were deleted)
- Type annotation gaps (unless they mask a runtime bug)
- Performance speculation without concrete evidence of a hot path and O(n²) or worse
- Issues already listed in "Existing Unresolved Review Comments" below — never re-report

## Line number rules

- The diff embeds right-side line numbers as LINE_N: prefixes
- Only use line numbers from the diff — never invent or estimate
- For multi-line issues: start_line = first affected line, line = last
- Never post comments on lines that are not in the diff hunks

## Summary format

Start with: <!-- guardrails-review -->
Then 1–3 sentences: risk level, what you found, and the verdict rationale.\
"""


def _match_path_instructions(
    changed_files: list[str],
    path_instructions: list[PathInstruction],
) -> list[PathInstruction]:
    """Return path instructions whose glob matches at least one changed file.

    Normalises ``**`` → ``*`` before matching because fnmatch's ``*`` already
    matches path separators, making ``**`` redundant but potentially confusing.
    """
    matched = []
    for pi in path_instructions:
        # Collapse consecutive wildcards so "tests/**" behaves like "tests/*"
        normalized = pi.path.replace("**", "*")
        if any(fnmatch.fnmatch(f, normalized) for f in changed_files):
            matched.append(pi)
    return matched


def _build_user_content(  # noqa: PLR0913
    diff: str,
    config: ReviewConfig,
    pr_meta: PRMetadata,
    memory_context: str = "",
    previous_comments: list[ReviewThread] | None = None,
    changed_files: list[str] | None = None,
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
    if ci_context:
        parts.append("")
        parts.append(f"## CI/CD context\n\n{ci_context}")
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
    *,
    ci_context: str = "",
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
                ci_context=ci_context,
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
