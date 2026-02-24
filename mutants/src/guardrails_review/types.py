"""Shared dataclasses for guardrails-review."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ReviewConfig:
    """Configuration loaded from .guardrails-review.toml."""

    model: str
    extra_instructions: str = ""
    auto_approve: bool = True
    severity_threshold: str = "error"
    max_diff_chars: int = 120_000
    agentic: bool = True
    max_iterations: int = 5


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
