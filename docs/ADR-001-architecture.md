# ADR-001: Architecture

## Status

Accepted

## Context

ai-guardrails needs an LLM-powered PR reviewer with auto-approve capability.
PR-Agent (Qodo Merge OSS) has auto-approve disabled in source (Pro-only).
Rather than forking, we build a standalone lightweight alternative.

## Decisions

### Standalone project

guardrails-review is a separate repo/package, not embedded in ai-guardrails.
ai-guardrails orchestrates *which* tools run; guardrails-review *is* the reviewer.
Clean separation of concerns. Each can version independently.

### Zero runtime dependencies

Python 3.11+ provides everything needed:
- `tomllib` for config parsing
- `urllib.request` for OpenRouter HTTP calls
- `json` for structured data
- `subprocess` for `gh` CLI

No requests, no httpx, no click, no rich. Minimal install footprint.

### gh CLI over PyGithub

- `gh` handles auth automatically (GITHUB_TOKEN, gh auth)
- No OAuth token management in our code
- JSON output parsing is trivial
- Already available in GitHub Actions runners

### Local JSON cache

Reviews are saved as `.guardrails-review/cache/pr-{N}-{timestamp}.json`.
AI agents read cache first (fast, no API calls), fall back to GitHub API.
Append-only: preserves review history for trend analysis.

### Composite GitHub Action

Not Docker-based. Composite action uses `setup-python` + `pip install`.
Faster startup, simpler debugging, no container overhead.

## Module architecture

```
cli.py → reviewer.py → [config.py, diff.py, llm.py, github.py] → cache.py
                                                                → types.py
```

- `types.py`: Shared dataclasses (ReviewConfig, ReviewComment, ReviewResult)
- `config.py`: TOML config loader
- `diff.py`: Unified diff parser (hunk → valid line numbers)
- `llm.py`: OpenRouter HTTP client
- `github.py`: gh CLI wrapper
- `reviewer.py`: Orchestrator (diff → LLM → validate → post)
- `cache.py`: Local JSON cache
- `cli.py`: Entry point with three subcommands (review, comments, approve)
