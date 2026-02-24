"""Agent context builder: structured JSON for AI agent prompt injection."""

from __future__ import annotations

from guardrails_review.cache import load_all_reviews
from guardrails_review.github import get_repo_info
from guardrails_review.threads import get_our_threads, get_review_threads


def build_agent_context(pr: int, *, max_comments: int = 20) -> dict:
    """Build structured context for injection into AI agent prompts.

    Returns a dict with:
    - pr: PR number
    - review_rounds: number of cached review rounds
    - unresolved: list of unresolved thread dicts (capped at max_comments)
    - resolved: list of recently resolved thread dicts
    - total_unresolved: actual count before cap
    - shown: number of unresolved shown

    Args:
        pr: Pull request number.
        max_comments: Maximum unresolved comments to include.

    Returns:
        Structured dict ready for JSON serialization.
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
                "thread_id": t.thread_id,
            }
            for t in resolved
        ],
        "total_unresolved": total_unresolved,
        "shown": len(shown_threads),
    }
