# guardrails-review — Agent Instructions

## Build & Test

- `uv run pytest tests/ -v` — run all tests
- `uv run pytest tests/test_X.py -v` — run single file
- `uv run ruff check src/` — lint
- `uv run ruff format --check src/` — format check

## Architecture

CLI tool + GitHub Action. See docs/ADR-001-architecture.md
Source: src/guardrails_review/ | Tests: tests/

## Key Constraints

- Python 3.11+, `from __future__ import annotations` in all files
- ZERO runtime dependencies (stdlib only)
- All GitHub operations via `gh` CLI, never direct API
- All HTTP via `urllib.request`, never requests/httpx
- 85%+ test coverage

## DONTs

- NEVER add runtime dependencies
- NEVER call GitHub API directly (use gh CLI)
- NEVER hardcode a default model
- NEVER post comments on lines outside diff hunks
- NEVER `except Exception: pass` — catch specific exceptions
- NEVER use dict[str, Any] across module boundaries — use dataclasses

## AI Guardrails - Code Standards

This project uses [ai-guardrails](https://github.com/Questi0nM4rk/ai-guardrails) for pedantic code enforcement.
Pre-commit hooks auto-fix formatting, then run security scans, linting, and type checks.
guardrails-review auto-reviews every PR push. CodeRabbit is optional (off by default).

### Tools

```bash
ai-guardrails comments --pr <N>                                    # List unresolved review threads
ai-guardrails comments --pr <N> --bot claude                       # Filter by bot
ai-guardrails comments --pr <N> --resolve <THREAD_ID> "Fixed."     # Resolve a thread with reply
ai-guardrails comments --pr <N> --resolve-all --bot <BOT>          # Batch resolve by bot
guardrails-review context --pr <N>                                    # Structured review state for AI agents
```

Use `ai-guardrails comments` to check PR status instead of raw `gh api` calls — the tool
handles pagination, filtering, and formatting.

### Review Bot Rules for AI Agents

guardrails-review auto-reviews on every push. It posts REQUEST_CHANGES with inline
defect comments, auto-resolves stale threads on new pushes, and sets commit status
for branch protection. CodeRabbit is optional and triggered manually.

**Fix every review comment that is not a false positive. Even nitpicks. Even style.**

- Use `ai-guardrails comments` to check and resolve threads.
- Fix ALL findings locally, then push once. One push per review round.
- Ask the human before pushing. Explain what changed.
- Wait for all bots (~5 min) before acting on feedback.

**Do not:**

- **Never dismiss a review comment because it's "just a nitpick."**
  Nitpicks are how code quality compounds. A style fix takes 30 seconds. Ignoring
  it means the next reviewer wastes time on the same thing. Fix it and move on.

- **Never resolve a thread without fixing it or explaining why it's a false positive.**
  Resolving a thread means "this is handled." If it's not handled, it's lying to the
  reviewer. If you disagree with a finding, reply with a reason — don't silently resolve.

- **Never batch-resolve threads you haven't read.**
  Each thread exists because a reviewer flagged something. Read it, decide if it's real
  or false positive, then act. `--resolve-all` is for documented false positives you've
  already triaged (e.g. a bot that always flags pytest `self`), not for blindly closing.

- **Never push after each individual fix.**
  Every push triggers all bots. Fixing 5 comments in 5 pushes creates 5 full review
  cycles of noise. Fix everything locally, push once.

- **Never skip a false positive without documenting it.**
  If a bot repeatedly flags something that's wrong, that's useful information for tuning
  the bot's config. Log it so it can be fixed upstream. Resolve with a reference to
  where it's documented.

### Pre-commit Workflow

```
auto-fix → re-stage → checks → commit
```

1. `format-and-stage` auto-fixes formatting and re-stages (local only, skipped in CI)
2. Security scans (gitleaks, detect-secrets, semgrep, bandit)
3. Linting (check-only — already fixed above)
4. Type checking (strict mode)
5. Git hygiene (no commits to main, no large files)

### When Pre-commit Fails

Most formatting is auto-fixed. If it still fails, read the error — it's a real issue
(missing docstring, type error, security problem). Fix it, stage, commit again.
