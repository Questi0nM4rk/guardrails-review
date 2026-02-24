# guardrails-review

LLM-powered PR reviewer with auto-approve and inline comments.

## Install

```bash
uv tool install guardrails-review
```

## Usage

```bash
# Review a PR (posts to GitHub + caches locally)
guardrails-review review --pr 53

# Dry-run (print review, don't post)
guardrails-review review --pr 53 --dry-run

# Query review findings (reads cache first)
guardrails-review comments --pr 53
guardrails-review comments --pr 53 --json

# Approve or request changes
guardrails-review approve --pr 53
guardrails-review approve --pr 53 --request-changes "Fix X"
```

## Configuration

Create `.guardrails-review.toml` in your project root:

```toml
[config]
model = "anthropic/claude-sonnet-4"  # REQUIRED

[review]
auto_approve = true
severity_threshold = "error"
extra_instructions = """
Focus on security and logic bugs.
"""
```

Set `OPENROUTER_KEY` environment variable for LLM access.

## GitHub Action

```yaml
- uses: Questi0nM4rk/guardrails-review@main
  with:
    pr-number: ${{ github.event.pull_request.number }}
    openrouter-key: ${{ secrets.OPENROUTER_KEY }}
```

## License

MIT
