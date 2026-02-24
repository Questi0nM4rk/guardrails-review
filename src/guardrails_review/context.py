"""Agent context builder: structured JSON for AI agent prompt injection."""

from __future__ import annotations

from typing import TypedDict

from guardrails_review.cache import load_all_reviews
from guardrails_review.github import get_repo_info
from guardrails_review.threads import get_our_threads, get_review_threads


class ThreadInfo(TypedDict):
    """Unresolved thread info for agent context."""

    path: str
    line: int | None
    body: str
    thread_id: str


class ResolvedThreadInfo(TypedDict):
    """Resolved thread info for agent context."""

    path: str
    line: int | None
    body: str


class AgentContext(TypedDict):
    """Structured context dict for AI agent prompt injection."""

    pr: int
    review_rounds: int
    unresolved: list[ThreadInfo]
    resolved: list[ResolvedThreadInfo]
    total_unresolved: int
    shown: int
    latest_verdict: str | None
    files_changed: list[str]


def build_agent_context(pr: int, *, max_comments: int = 20) -> AgentContext:
    """Build structured context for injection into AI agent prompts.

    Args:
        pr: Pull request number.
        max_comments: Maximum unresolved comments to include.

    Returns:
        AgentContext dict with pr info, threads, verdict, and affected files.
    """
    owner, repo = get_repo_info()
    all_threads = get_review_threads(pr, owner, repo)
    our_threads = get_our_threads(all_threads)

    reviews = load_all_reviews(pr)

    unresolved = sorted(
        [t for t in our_threads if not t.is_resolved],
        key=lambda t: (t.path, t.line or 0),
    )
    resolved = [t for t in our_threads if t.is_resolved]

    total_unresolved = len(unresolved)
    shown_threads = unresolved[:max_comments]

    latest_verdict: str | None = reviews[-1].verdict if reviews else None
    files_changed = sorted({t.path for t in unresolved})

    return {
        "pr": pr,
        "review_rounds": len(reviews),
        "unresolved": [
            {
                "path": t.path,
                "line": t.line,
                "body": t.body,
                "thread_id": t.thread_id,
            }
            for t in shown_threads
        ],
        "resolved": [
            {
                "path": t.path,
                "line": t.line,
                "body": t.body,
            }
            for t in resolved
        ],
        "total_unresolved": total_unresolved,
        "shown": len(shown_threads),
        "latest_verdict": latest_verdict,
        "files_changed": files_changed,
    }
