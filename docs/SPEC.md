# guardrails-review Specification

## 1. Overview

guardrails-review is an AI-native PR review bot that acts as a merge gatekeeper.
It is **not** a human code review tool. The primary consumer is an AI coding agent
(such as Claude Code) that opens pull requests and iterates on feedback
programmatically.

The bot enforces a strict defect-only policy: bugs, security vulnerabilities,
resource leaks, and contract violations. No style, no nitpicks, no suggestions.
Everything is an error or it is silent.

**Key properties:**

- **Zero runtime dependencies.** Python 3.11+ stdlib only.
- **All GitHub operations via `gh` CLI.** No direct API calls, no PyGithub.
- **LLM-powered via OpenRouter.** Any model accessible through OpenRouter works.
- **Gatekeeper model.** Repos configure "require APPROVE to merge" branch
  protection. guardrails-review is the maintainer. It re-reviews the full diff
  on every push and only approves when the code is clean and all threads are
  resolved. No rubber-stamping — approval is a deliberate decision.
- **Commit status integration.** Sets `guardrails-review` commit status to
  `pending`, `success`, or `failure` alongside the review.

---

## 2. The Agent Loop

The core workflow is a CI-driven feedback loop between an AI coding agent and the
review bot.

```
1. Agent opens PR
2. CI runs: guardrails-review review --pr N
   -> Posts REQUEST_CHANGES with inline defect comments
   -> Sets commit status to "failure"
3. Agent runs: guardrails-review context --pr N
   -> Gets structured JSON of unresolved threads
4. Agent fixes defects, pushes
5. CI re-runs: guardrails-review review --pr N
   -> Auto-resolves stale threads (file deleted, outdated, line modified)
   -> Deduplicates comments against existing threads
   -> Posts new review
6. Repeat until: 0 new defects AND 0 unresolved threads
   -> Bot decides: code is clean, I approve this into my repo
   -> APPROVE + commit status "success"
7. Branch protection sees APPROVE + status "success" -> merge allowed
```

### Example CI workflow

```yaml
name: Review
on:
  pull_request:
    types: [opened, synchronize]

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      statuses: write
    steps:
      - uses: actions/checkout@v4
      - uses: Questi0nM4rk/guardrails-review@main
        with:
          pr-number: ${{ github.event.pull_request.number }}
          openrouter-key: ${{ secrets.OPENROUTER_KEY }}
```

### Example agent-side loop

```bash
# After CI posts REQUEST_CHANGES:
guardrails-review context --pr 42 > /tmp/review.json

# Agent reads review.json, fixes issues, pushes
# CI re-runs automatically on push
```

---

## 3. CLI Reference

### `review`

Run the LLM review pipeline on a PR. Posts a GitHub review with inline comments,
sets commit status.

```bash
guardrails-review review --pr <number> [--dry-run]
```

| Flag | Description |
|------|-------------|
| `--pr N` | Required. PR number. |
| `--dry-run` | Print review to stdout without posting to GitHub. |

**Behavior:**

1. Load config from `.guardrails-review.toml`
2. Fetch PR diff and metadata via `gh`
3. Send diff to LLM (agentic or oneshot mode based on config)
4. Validate comment line numbers against diff hunks
5. Deduplicate comments against existing unresolved threads
6. Auto-resolve stale threads from previous rounds
7. Check remaining unresolved guardrails-review threads
8. Post review (APPROVE or REQUEST_CHANGES)
9. Set commit status (`success` or `failure`)

**Verdict logic:** Any comments (valid or invalid-line) = `request_changes`.
Zero comments AND zero unresolved threads from prior rounds = `approve`.
Zero new comments BUT unresolved threads remain = `request_changes`.

**Exit code:** Always 0 on success (even if defects found). 1 on pipeline failure.

### `context`

Return structured JSON for AI agent prompt injection. This is the primary
interface for agents to understand what needs fixing.

```bash
guardrails-review context --pr <number> [--max-comments N]
```

| Flag | Description |
|------|-------------|
| `--pr N` | Required. PR number. |
| `--max-comments N` | Max unresolved comments to include (default: 20). |

**Output format:**

```json
{
  "pr": 42,
  "review_rounds": 3,
  "unresolved": [
    {
      "path": "src/auth.py",
      "line": 15,
      "body": "<!-- guardrails-review -->\nSQL injection via unsanitized input",
      "thread_id": "PRRT_abc123"
    }
  ],
  "resolved": [
    {
      "path": "src/db.py",
      "line": 8,
      "body": "<!-- guardrails-review -->\nConnection not closed on error path"
    }
  ],
  "total_unresolved": 1,
  "shown": 1,
  "latest_verdict": "request_changes",
  "files_changed": ["src/auth.py"]
}
```

### `comments`

Query cached review findings from the local JSON cache.

```bash
guardrails-review comments --pr <number> [--json]
```

| Flag | Description |
|------|-------------|
| `--pr N` | Required. PR number. |
| `--json` | Output all cached reviews as JSON array. |

Without `--json`, prints the latest review in human-readable format.

### `approve`

Manually approve or request changes on a PR. Separate from the `review` pipeline.

```bash
guardrails-review approve --pr <number> [--request-changes MSG] [--dry-run]
```

| Flag | Description |
|------|-------------|
| `--pr N` | Required. PR number. |
| `--request-changes MSG` | Request changes instead of approving. |
| `--dry-run` | Print action without calling API. |

### `resolve`

Auto-resolve stale review threads without running a new review.

```bash
guardrails-review resolve --pr <number> [--dry-run]
```

| Flag | Description |
|------|-------------|
| `--pr N` | Required. PR number. |
| `--dry-run` | Print resolvable threads without resolving. |

**Resolution rules:**

1. File was deleted in the PR
2. GitHub marked the thread as outdated (code changed underneath)
3. Thread's line is no longer in the current diff

---

## 4. GitHub Action

### Setup

```yaml
- uses: Questi0nM4rk/guardrails-review@main
  with:
    pr-number: ${{ github.event.pull_request.number }}
    openrouter-key: ${{ secrets.OPENROUTER_KEY }}
```

The action is a composite action (not Docker-based). It installs Python 3.12,
pip-installs the package, and runs `guardrails-review review --pr N`.

### Required secrets

| Secret | Description |
|--------|-------------|
| `OPENROUTER_KEY` | API key for OpenRouter LLM access. |

`GH_TOKEN` is automatically provided by `${{ github.token }}`.

### Required permissions

```yaml
permissions:
  contents: read
  pull-requests: write
  statuses: write
```

### Branch protection configuration

To use guardrails-review as a merge gatekeeper:

1. Go to Settings > Branches > Branch protection rules
2. Enable "Require a pull request before merging"
3. Enable "Require approvals" (set to 1)
4. Under "Require status checks to pass before merging", add `guardrails-review`
5. The bot's approval + passing status check allows merge

---

## 5. Review Behavior

### What it flags (defect categories)

- Bugs and logic errors
- Security vulnerabilities
- Data races and concurrency issues
- Resource leaks (file handles, connections, memory)
- Unhandled error paths (missing error checks, swallowed exceptions)
- API contract violations (wrong types, missing required fields, broken invariants)

### What it ignores

- Style, formatting, naming
- "Consider doing X" suggestions
- Missing tests or documentation
- Performance (unless a clear algorithmic bug like O(n^2) in a hot path)

### Severity model

There is one severity level: `error`. Every comment is an error. There are no
warnings, no info-level comments, no configurable severity threshold. A defect
is reported or it is not.

### Review modes

**Agentic mode** (default, `agentic = true`):

The LLM has access to tools to explore the codebase before submitting its review:

| Tool | Description |
|------|-------------|
| `read_file(path, start_line?, end_line?)` | Read file contents at PR head commit |
| `list_changed_files()` | List all changed files with addition/deletion counts |
| `search_code(query)` | Search the repository for code patterns |
| `submit_review(verdict, summary, comments)` | Submit the final review (terminates the loop) |

The agentic loop runs up to `max_iterations` rounds (default: 5). On the final
iteration, the model is forced to call `submit_review`. If the tool-use API
fails, it falls back to oneshot mode.

**Oneshot mode** (`agentic = false`):

Single LLM call: diff in, JSON review out. No tool access. Faster but less
context-aware.

### Malformed response handling

1. Try to parse response as JSON directly
2. Try to extract JSON from markdown code blocks (` ```json ... ``` `)
3. If both fail, treat entire response as review body text
4. Verdict defaults to `request_changes` (fail-safe)

---

## 6. Thread Lifecycle

### Bot identification

All review comments and summaries include the HTML marker `<!-- guardrails-review -->`.
This marker is used to identify which threads belong to this bot versus human
reviewers or other bots.

### Deduplication

Before posting a new review, the bot fetches existing threads and removes
comments that would duplicate an existing unresolved thread. Matching is on
`(path, line)` only -- LLM output is non-deterministic so body matching is
unreliable.

If deduplication removes all new comments, the verdict is recomputed (may become
`approve`).

### Auto-resolve rules

During `review --pr N` (after posting the new review) and `resolve --pr N`, the
bot checks unresolved guardrails-review threads against three rules:

1. **File deleted.** The file no longer exists in the PR.
2. **Outdated.** GitHub flagged the thread as outdated (the code underneath changed).
3. **Line no longer in diff.** The thread's line number is not in the current diff hunks.

All three rules are conservative. When in doubt, the thread stays open.

### Agent thread resolution

The AI agent (or human) is responsible for resolving threads after fixing issues.
This can be done via:

- `ai-guardrails comments --resolve` (from the ai-guardrails CLI)
- GitHub UI (resolve conversation button)
- GitHub API (resolveReviewThread mutation)

The bot does NOT resolve threads just because a new review found no issues at
that location. It only auto-resolves based on the three structural rules above.

---

## 7. Approval Gate

### Design principle

The bot is the **maintainer** of the repository. It does not rubber-stamp clean
diffs. Approval is a deliberate decision: "I have reviewed this code. There are
no defects and no unresolved threads. I want this merged into my repo."

This is NOT auto-approve. The bot re-reviews the full diff on every push. If
the new review finds zero defects AND there are zero unresolved guardrails-review
threads, then — and only then — the bot approves.

### Approval conditions (all must be true)

1. **Zero new defects** in the current review round
2. **Zero unresolved guardrails-review threads** from any previous round
3. **Review actually ran** (not a skip or error)

If any condition fails, the bot posts REQUEST_CHANGES (or COMMENT if no new
defects but threads remain).

### Current behavior

`review --pr N` computes the verdict as:

- **Any comments** (valid-line or invalid-line) -> `request_changes`
- **Zero comments AND zero unresolved threads** -> `approve`
- **Zero new comments BUT unresolved threads remain** -> `request_changes`

The unresolved thread check runs after auto-resolve, so stale threads
(deleted files, outdated code, modified lines) are cleaned up first. Only
threads that genuinely remain open block approval.

When approval is blocked by unresolved threads, the summary includes a
message like "N unresolved thread(s) from previous review rounds remain
open" and the commit status is set to `failure` with description
"Unresolved threads remain".

---

## 8. Configuration

Configuration is loaded from `.guardrails-review.toml` in the project root.

### Full format

```toml
[config]
model = "anthropic/claude-sonnet-4"  # REQUIRED — OpenRouter model identifier

[review]
extra_instructions = """
Focus on security vulnerabilities in authentication code.
Ignore changes to test files.
"""
max_diff_chars = 120000    # Truncate diff beyond this (default: 120000)
agentic = true             # Enable agentic tool-use mode (default: true)
max_iterations = 5         # Max agentic loop iterations (default: 5)
```

### Fields

| Section | Field | Type | Default | Description |
|---------|-------|------|---------|-------------|
| `[config]` | `model` | string | (required) | OpenRouter model ID |
| `[review]` | `extra_instructions` | string | `""` | Injected into the LLM prompt as project-specific instructions |
| `[review]` | `max_diff_chars` | int | `120000` | Maximum diff characters sent to LLM |
| `[review]` | `agentic` | bool | `true` | Enable agentic mode with tool use |
| `[review]` | `max_iterations` | int | `5` | Maximum tool-use loop iterations |

### Environment variables

| Variable | Description |
|----------|-------------|
| `OPENROUTER_KEY` | Required. API key for OpenRouter. |
| `GH_TOKEN` / `GITHUB_TOKEN` | Required. Used by `gh` CLI for GitHub API access. |

---

## 9. Agent Integration

### Full agent workflow

```bash
# 1. Agent opens PR and pushes code
git push origin feature-branch
gh pr create --title "Add auth middleware" --body "..."

# 2. CI runs guardrails-review (automatic via workflow)
# Bot posts REQUEST_CHANGES with 2 inline comments, sets status to "failure"

# 3. Agent fetches structured context
guardrails-review context --pr 42
# Returns JSON with unresolved threads, file paths, verdict

# 4. Agent fixes issues based on context JSON
# Edit files, commit, push

# 5. CI re-runs guardrails-review (automatic)
# Bot auto-resolves stale threads, deduplicates, re-reviews full diff
# If 0 defects AND 0 unresolved threads: bot approves -> merge allowed
```

### Reading context output

The `context` command returns a flat JSON object. Key fields for agents:

- `unresolved[].path` + `unresolved[].line`: Where the defect is
- `unresolved[].body`: Description of the defect (strip the HTML marker)
- `total_unresolved`: How many open issues remain
- `latest_verdict`: Current review state (`approve` or `request_changes`)
- `files_changed`: Which files have open issues

### Local cache

Reviews are cached as JSON files in `.guardrails-review/cache/pr-{N}-{timestamp}.json`.
The `comments` command reads from cache first (fast, no API calls). Cache is
append-only -- all review rounds are preserved for history.

---

## 10. Planned Features

### Unresolved thread check before approve

**Status:** Implemented.

Before approving, `run_review()`:

1. Fetches all review threads on the PR (reuses dedup fetch)
2. Filters to guardrails-review threads (by `<!-- guardrails-review -->` marker)
3. Auto-resolves stale threads (deleted files, outdated, line no longer in diff)
4. Checks remaining unresolved threads
5. If unresolved threads exist, posts REQUEST_CHANGES with message
   "N unresolved thread(s) from previous review rounds remain open"

This is a gate, not a convenience. The bot is the maintainer. It does not
approve code with open defect threads.

### Per-repo memory

**Status:** Not implemented. Planned.

The bot should learn per-project patterns over time:

- **False positive patterns.** Track which defect comments get resolved as false
  positives. Suppress similar comments in future reviews.
- **Project conventions.** Learn project-specific patterns that the
  `extra_instructions` field captures manually today.
- **Resolution history.** Track how long threads stay open, which types of
  defects recur, and agent fix rates.

Storage would be a local JSON or TOML file (`.guardrails-review/memory.json`)
that persists across review rounds and is committed to the repo.

### Multi-line comment support

**Status:** Partially implemented.

The `ReviewComment` dataclass has a `start_line` field. The `submit_review` tool
schema includes `start_line` as an optional parameter. The `post_review` function
sends `start_line`/`start_side` when present. However, oneshot mode does not
prompt the LLM for multi-line ranges, and validation does not check `start_line`
against diff hunks.

---

## 11. Architecture

See [ADR-001](./ADR-001-architecture.md) for full architecture decisions.

### Module overview

```
cli.py          CLI entry point. Parses args, dispatches to handlers.
reviewer.py     Core orchestrator. Diff -> LLM -> validate -> post.
config.py       Loads .guardrails-review.toml into ReviewConfig dataclass.
diff.py         Unified diff parser. Extracts valid line numbers per file.
llm.py          OpenRouter HTTP client via urllib.request. Zero deps.
github.py       gh CLI wrapper. All GitHub operations go through here.
threads.py      Thread lifecycle: fetch, filter, resolve, deduplicate.
context.py      Agent context builder. Structured JSON for prompt injection.
cache.py        Local JSON cache. Append-only review history.
tools.py        Tool definitions and execution for agentic review loop.
types.py        Shared dataclasses: ReviewConfig, ReviewComment, ReviewResult, etc.
```

### Data flow

```
review --pr N
  |
  v
load_config() -> ReviewConfig
  |
  v
get_pr_diff(N) -> diff string
get_pr_metadata(N) -> {title, body, headRefOid, baseRefName}
parse_diff_hunks(diff) -> {path: {line_numbers}}
  |
  v
[agentic mode]                    [oneshot mode]
build_agentic_messages()          build_messages()
  |                                 |
  v                                 v
call_openrouter_tools() loop      call_openrouter()
  |  read_file()                    |
  |  list_changed_files()           v
  |  search_code()                parse_response() -> ReviewResult
  |  submit_review() -> exit
  |
  v
validate_comments(result, valid_lines)
  -> (valid_comments, invalid_comments)
  |
  v
deduplicate_comments(valid, existing_threads)
  |
  v
post_review(pr, final_result, owner, repo, sha)
save_review(final_result)
  |
  v
auto_resolve stale threads
set_commit_status(success | failure)
```
