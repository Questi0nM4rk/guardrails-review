"""Shared dataclasses and constants for guardrails-review."""

from __future__ import annotations

from dataclasses import dataclass, field

REVIEW_MARKER = "<!-- guardrails-review -->"


@dataclass(frozen=True)
class PRMetadata:
    """Pull request metadata from GitHub."""

    title: str
    body: str
    head_ref_oid: str
    base_ref_name: str


@dataclass(frozen=True)
class ReviewConfig:
    """Configuration loaded from .guardrails-review.toml."""

    model: str
    extra_instructions: str = ""
    max_diff_chars: int = 120_000
    agentic: bool = True
    max_iterations: int = 30


@dataclass(frozen=True)
class ToolCall:
    """A single tool call from the LLM response."""

    id: str
    name: str
    arguments: str  # raw JSON string


@dataclass(frozen=True)
class LLMResponse:
    """Structured response from the LLM, supporting both content and tool calls."""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewComment:
    """A single review comment targeting a specific file and line."""

    path: str
    line: int
    body: str
    severity: str
    start_line: int | None = None


@dataclass(frozen=True)
class ReviewResult:
    """Complete review output from the LLM."""

    verdict: str
    summary: str
    comments: list[ReviewComment] = field(default_factory=list)
    model: str = ""
    timestamp: str = ""
    pr: int = 0


@dataclass(frozen=True)
class ReviewThread:
    """A review thread fetched from GitHub GraphQL API."""

    thread_id: str
    path: str
    line: int | None
    body: str
    is_resolved: bool
    is_outdated: bool
    author: str
    created_at: str


@dataclass(frozen=True)
class ThreadResolution:
    """Result of checking whether a thread can be auto-resolved."""

    thread_id: str
    resolved: bool
    reason: str


@dataclass
class TokenBudget:
    """Track token usage across agentic loop iterations.

    ``last_prompt_tokens`` is the current context size (from the most recent
    request).  ``total_completion_tokens`` is cumulative across all iterations
    (for cost tracking).
    """

    max_tokens: int
    reserve_tokens: int = 0
    last_prompt_tokens: int = 0
    total_completion_tokens: int = 0

    @property
    def remaining(self) -> int:
        """Tokens remaining before hitting the budget ceiling."""
        return self.max_tokens - self.last_prompt_tokens

    def record(self, usage: dict[str, int] | None) -> None:
        """Update budget from an OpenRouter usage dict."""
        if usage:
            self.last_prompt_tokens = usage.get("prompt_tokens", 0)
            self.total_completion_tokens += usage.get("completion_tokens", 0)

    def can_continue(self, estimated_next: int = 20_000) -> bool:
        """Return True if there is room for another iteration."""
        return self.remaining > estimated_next + self.reserve_tokens

    def at_threshold(self, pct: float) -> bool:
        """Return True if prompt usage has reached *pct* of max_tokens."""
        return self.last_prompt_tokens >= self.max_tokens * pct
