# ADR-002: LLM Prompt Design

## Status

Accepted

## Context

The reviewer sends PR diffs to an LLM and expects structured review comments back.
The response must be machine-parseable for posting to GitHub's review API.

## Decisions

### Structured JSON output

The LLM returns a JSON object with `verdict`, `summary`, and `comments` array.
We use `response_format: {"type": "json_object"}` on OpenRouter for reliability.

### Line number validation

GitHub's pull request review API returns 422 for comments on lines outside the diff.
After LLM response, we validate each comment's `line` against parsed diff hunks.
Invalid-line comments are moved to the review body as text (not silently dropped).

### Severity levels

Three levels: `error` (must fix), `warning` (should fix), `info` (suggestion).
Only `error` triggers `request_changes` by default (configurable via `severity_threshold`).

### Malformed response fallback

If the LLM returns non-JSON or missing fields:
1. Try to extract JSON from markdown code blocks
2. If still invalid, treat entire response as a single review body comment
3. Verdict defaults to `request_changes` (fail-safe)

### Prompt constraints

- Do NOT flag style/formatting (handled by linters)
- Do NOT flag missing tests unless critical path has zero coverage
- Include `<!-- guardrails-review -->` HTML comment for bot detection
- Line numbers reference new file (right side of diff)
