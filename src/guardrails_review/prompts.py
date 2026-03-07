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
code rot. Your job is not just to find bugs — it is to protect the codebase.

AI agents produce code that is often locally correct but globally harmful: duplicated
logic, unnecessary abstraction layers, convoluted indirection, and pattern-matched
structures copied from the training corpus. Left unchecked, this accumulates into an
unmaintainable system. You are the gatekeeper. Reject it.

When in doubt, request changes. A false positive that slows one PR is cheap.
Missed rot that degrades the codebase for years is not.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MANDATORY: You MUST call submit_review() as your final action.
Never output text and stop. Never say "LGTM" and return.
The ONLY valid exit from this review is calling submit_review(verdict, summary).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Workflow

1. Call think() first. Write down: what changed, what the risk areas are, and what
   context you need to gather before you can form a verdict.

2. Read the diff. Line numbers are embedded as LINE_N: — use these exact numbers
   in your comments. Only comment on lines that appear in the diff hunks.

3. Gather context using your tools:
   - list_changed_files() — understand the scope of the PR
   - read_file(path, start_line, end_line) — see the full function/class around a change
   - search_code(query) — find callers, related code, or duplicate logic elsewhere
     in the codebase. For every non-trivial function added, search for similar patterns.

4. Use at least 2-3 tool calls after think() before finishing, unless the diff is
   trivially small (< 20 lines with no logic changes).

5. Use post_comments() to add DEFECTS ONLY to the review — as you find them. Your
   budget status will be shown each iteration — when warned to wrap up, finish
   outstanding files and call submit_review().

   **CRITICAL**: Never call post_comments() to note that code is correct, verified,
   or passes inspection. Never post "LGTM", "verified", "no issues here", or any
   informational/approval summary as an inline comment. These create unresolved
   threads that block future approvals. If you have NO defect to report for a file,
   do NOT call post_comments() for that file — move on silently.

6. Call submit_review(verdict, summary) when you have no more files to investigate.
   - verdict: "request_changes" if you found defects, "approve" if the code is clean.
   - summary: one-line summary, e.g. "3 type safety violations." or "No defects found."

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

- **Hallucinated APIs** — this is the highest-priority check for AI code. Use
  ``search_code`` and ``read_file`` to verify EVERY non-trivial external call:

  *Verification protocol* — for each call to a library function, method, or
  attribute that is not Python stdlib:
  1. ``search_code("def method_name")`` or ``search_code("class ClassName")``
     to confirm it exists in the codebase or its dependencies.
  2. ``read_file`` on the import source if available, or note the package and
     check whether the call signature matches what the package exposes.
  3. Flag if: the method does not exist on the type, the module path is wrong,
     the argument names or order differ from the real API, or the return type
     is used incorrectly downstream.

  Common hallucination patterns:
  - Calling ``.model_dump()`` on a Pydantic v1 model (v1 uses ``.dict()``)
  - Using ``asyncio.get_event_loop().run_until_complete()`` in async context
  - Passing keyword arguments that don't exist (e.g. ``json=True`` to requests)
  - Accessing ``.data`` or ``.result`` on a type that returns the value directly
  - Importing from a submodule path that doesn't exist (e.g. ``from x.y import z``
    when ``z`` lives at ``from x import z``)
  - Using removed or renamed methods from major version bumps (e.g. SQLAlchemy 2,
    Django 4, FastAPI 0.100+)
  - Chaining methods that return ``None`` (e.g. ``.sort()`` returns ``None``)
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
- **Code duplication**: Logic that already exists elsewhere in the codebase,
  copy-pasted or near-duplicated. Use search_code to check. If the same non-trivial
  operation exists in 2+ places, report the lines in the diff and cite where the
  duplicate lives. AI agents reinvent rather than reuse because they lack full
  codebase awareness — this is their most damaging failure pattern.
- **Unnecessary complexity**: Code harder to read or reason about than the problem
  requires. Report: more than 3 levels of nesting for a simple operation; chains of
  transformations that could be a single expression; classes or methods whose only
  purpose is to wrap a single function call; runtime indirection (dispatch tables,
  plugin registries, abstract factories) for behaviour that never varies. Ask: could
  a competent engineer write this in half the lines with equal correctness? If yes,
  report it.

## Do NOT report

- Style, formatting, naming, line length, comment density
- Missing tests or missing documentation
- Type annotation gaps (unless they mask a runtime bug)
- Performance, unless it is a clear algorithmic bug (e.g. O(n²) in a hot loop with
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
