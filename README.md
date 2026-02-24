# guardrails-review

AI-native PR review bot that acts as a merge gatekeeper. Finds defects (bugs,
security, resource leaks, contract violations) and blocks merge until they are
fixed. No style, no nitpicks -- errors only.

**Primary consumer:** AI coding agents that open PRs and iterate on feedback
programmatically. The bot is the sole reviewer; it must approve for merge to
happen.

## The agent loop

```
1. Agent opens PR
2. CI runs:  guardrails-review review --pr N
             -> REQUEST_CHANGES + inline defect comments + status "failure"
3. Agent runs: guardrails-review context --pr N
               -> structured JSON of what needs fixing
4. Agent fixes, pushes
5. CI re-runs -> auto-resolves stale threads, deduplicates, posts new review
6. 0 defects + 0 unresolved threads
   -> Bot decides: clean code, approve into repo
   -> APPROVE + status "success" -> merge
```

## Install

```bash
uv tool install guardrails-review
# or
pip install guardrails-review
```

## Configure

Create `.guardrails-review.toml` in your project root:

```toml
[config]
model = "anthropic/claude-sonnet-4"  # REQUIRED — any OpenRouter model

[review]
extra_instructions = """
Focus on security and logic bugs.
"""
agentic = true          # tool-use mode (default: true)
max_iterations = 5      # agentic loop iterations (default: 5)
max_diff_chars = 120000 # diff truncation limit (default: 120000)
```

Set `OPENROUTER_KEY` environment variable for LLM access.

## Usage

```bash
# Run review (posts to GitHub + caches locally)
guardrails-review review --pr 53

# Dry-run (print review, don't post)
guardrails-review review --pr 53 --dry-run

# Agent context (structured JSON for prompt injection)
guardrails-review context --pr 53

# Query cached review findings
guardrails-review comments --pr 53
guardrails-review comments --pr 53 --json

# Auto-resolve stale threads
guardrails-review resolve --pr 53

# Manual approve/request-changes
guardrails-review approve --pr 53
guardrails-review approve --pr 53 --request-changes "Fix X"
```

## GitHub Action

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

### Branch protection setup

1. Require pull request reviews (1 approval)
2. Add `guardrails-review` as a required status check
3. The bot's APPROVE + passing status check gates merge

## Key properties

- **Zero runtime dependencies.** Python 3.11+ stdlib only.
- **All GitHub ops via `gh` CLI.** No direct API calls.
- **Defect-only policy.** Bugs, security, leaks, contract violations. Nothing else.
- **Agentic mode.** LLM can read files, search code, and list changes before reviewing.
- **Thread lifecycle.** Auto-resolves stale threads, deduplicates across rounds.
- **Commit status.** Sets `guardrails-review` status for branch protection integration.

## Full reference

See [docs/SPEC.md](docs/SPEC.md) for the complete specification including thread
lifecycle, auto-approve behavior, configuration reference, and architecture.

## License

MIT
