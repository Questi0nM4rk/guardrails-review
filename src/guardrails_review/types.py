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
