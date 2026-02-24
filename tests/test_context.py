"""Tests for guardrails_review.context module."""

from __future__ import annotations

from guardrails_review.context import build_agent_context
from guardrails_review.types import ReviewThread


def _make_thread(**kwargs):
    defaults = {
        "thread_id": "t1",
        "path": "f.py",
        "line": 10,
        "body": "<!-- guardrails-review -->\nBug",
        "is_resolved": False,
        "is_outdated": False,
        "author": "bot",
        "created_at": "2024-01-01T00:00:00Z",
    }
    defaults.update(kwargs)
    return ReviewThread(**defaults)


def test_build_agent_context_basic(monkeypatch):
    """Returns structured dict with unresolved and resolved threads."""
    threads = [
        _make_thread(thread_id="t1", path="a.py", line=10, is_resolved=False),
        _make_thread(thread_id="t2", path="b.py", line=20, is_resolved=True),
        _make_thread(
            thread_id="t3",
            path="c.py",
            line=30,
            body="Other bot comment",
            is_resolved=False,
        ),
    ]

    monkeypatch.setattr(
        "guardrails_review.context.get_review_threads",
        lambda pr, owner, repo: threads,
    )
    monkeypatch.setattr(
        "guardrails_review.context.get_repo_info",
        lambda: ("owner", "repo"),
    )
    monkeypatch.setattr(
        "guardrails_review.context.load_all_reviews",
        lambda pr: [1, 2, 3],
    )

    result = build_agent_context(42)

    assert result["pr"] == 42
    assert result["review_rounds"] == 3
    assert result["total_unresolved"] == 1
    assert len(result["unresolved"]) == 1
    assert result["unresolved"][0]["path"] == "a.py"
    assert result["unresolved"][0]["thread_id"] == "t1"
    assert len(result["resolved"]) == 1
    assert result["resolved"][0]["path"] == "b.py"


def test_build_agent_context_empty(monkeypatch):
    """Empty PR returns zeros and empty lists."""
    monkeypatch.setattr(
        "guardrails_review.context.get_review_threads",
        lambda pr, owner, repo: [],
    )
    monkeypatch.setattr(
        "guardrails_review.context.get_repo_info",
        lambda: ("owner", "repo"),
    )
    monkeypatch.setattr(
        "guardrails_review.context.load_all_reviews",
        lambda pr: [],
    )

    result = build_agent_context(1)

    assert result["pr"] == 1
    assert result["review_rounds"] == 0
    assert result["total_unresolved"] == 0
    assert result["unresolved"] == []
    assert result["resolved"] == []


def test_build_agent_context_max_comments(monkeypatch):
    """Unresolved comments are capped at max_comments."""
    threads = [
        _make_thread(thread_id=f"t{i}", path=f"f{i}.py", line=i, is_resolved=False)
        for i in range(30)
    ]

    monkeypatch.setattr(
        "guardrails_review.context.get_review_threads",
        lambda pr, owner, repo: threads,
    )
    monkeypatch.setattr(
        "guardrails_review.context.get_repo_info",
        lambda: ("owner", "repo"),
    )
    monkeypatch.setattr(
        "guardrails_review.context.load_all_reviews",
        lambda pr: [],
    )

    result = build_agent_context(1, max_comments=5)

    assert result["total_unresolved"] == 30
    assert result["shown"] == 5
    assert len(result["unresolved"]) == 5


def test_build_agent_context_sorted_by_path(monkeypatch):
    """Unresolved comments are sorted by path."""
    threads = [
        _make_thread(thread_id="t1", path="z.py", line=1, is_resolved=False),
        _make_thread(thread_id="t2", path="a.py", line=1, is_resolved=False),
        _make_thread(thread_id="t3", path="m.py", line=1, is_resolved=False),
    ]

    monkeypatch.setattr(
        "guardrails_review.context.get_review_threads",
        lambda pr, owner, repo: threads,
    )
    monkeypatch.setattr(
        "guardrails_review.context.get_repo_info",
        lambda: ("owner", "repo"),
    )
    monkeypatch.setattr(
        "guardrails_review.context.load_all_reviews",
        lambda pr: [],
    )

    result = build_agent_context(1)

    paths = [c["path"] for c in result["unresolved"]]
    assert paths == ["a.py", "m.py", "z.py"]


def test_build_agent_context_shown_equals_total_when_under_cap(monkeypatch):
    """shown equals total_unresolved when under max_comments."""
    threads = [
        _make_thread(thread_id=f"t{i}", path=f"f{i}.py", line=i, is_resolved=False)
        for i in range(3)
    ]

    monkeypatch.setattr(
        "guardrails_review.context.get_review_threads",
        lambda pr, owner, repo: threads,
    )
    monkeypatch.setattr(
        "guardrails_review.context.get_repo_info",
        lambda: ("owner", "repo"),
    )
    monkeypatch.setattr(
        "guardrails_review.context.load_all_reviews",
        lambda pr: [],
    )

    result = build_agent_context(1, max_comments=20)

    assert result["total_unresolved"] == 3
    assert result["shown"] == 3
