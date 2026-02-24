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
