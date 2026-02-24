"""Tests for guardrails_review.threads module."""

from __future__ import annotations

from guardrails_review.threads import (
    deduplicate_comments,
    find_resolvable_threads,
    get_our_threads,
    get_review_threads,
)
from guardrails_review.types import ReviewComment, ReviewThread

# --- get_review_threads ---


def test_get_review_threads_parses_graphql(monkeypatch):
    """GraphQL response is parsed into ReviewThread list."""
    graphql_response = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                "id": "thread-1",
                                "isResolved": False,
                                "isOutdated": False,
                                "path": "src/main.py",
                                "line": 10,
                                "comments": {
                                    "nodes": [
                                        {
                                            "body": "<!-- guardrails-review -->\nBug here",
                                            "author": {"login": "github-actions[bot]"},
                                            "createdAt": "2024-01-01T00:00:00Z",
                                        }
                                    ]
                                },
                            },
                        ],
                    }
                }
            }
        }
    }

    monkeypatch.setattr(
        "guardrails_review.threads.graphql",
        lambda query, variables=None: graphql_response,
    )

    threads = get_review_threads(42, "owner", "repo")

    assert len(threads) == 1
    assert threads[0].thread_id == "thread-1"
    assert threads[0].path == "src/main.py"
    assert threads[0].line == 10
    assert threads[0].is_resolved is False
    assert "Bug here" in threads[0].body


def test_get_review_threads_paginates(monkeypatch):
    """Multiple pages of threads are fetched via cursor."""
    page1 = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                        "nodes": [
                            {
                                "id": "t1",
                                "isResolved": False,
                                "isOutdated": False,
                                "path": "a.py",
                                "line": 1,
                                "comments": {
                                    "nodes": [
                                        {
                                            "body": "<!-- guardrails-review -->\nFirst",
                                            "author": {"login": "bot"},
                                            "createdAt": "2024-01-01T00:00:00Z",
                                        }
                                    ]
                                },
                            },
                        ],
                    }
                }
            }
        }
    }
    page2 = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                "id": "t2",
                                "isResolved": False,
                                "isOutdated": False,
                                "path": "b.py",
                                "line": 2,
                                "comments": {
                                    "nodes": [
                                        {
                                            "body": "<!-- guardrails-review -->\nSecond",
                                            "author": {"login": "bot"},
                                            "createdAt": "2024-01-01T00:00:00Z",
                                        }
                                    ]
                                },
                            },
                        ],
                    }
                }
            }
        }
    }

    call_count = {"n": 0}

    def fake_graphql(query, variables=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return page1
        return page2

    monkeypatch.setattr("guardrails_review.threads.graphql", fake_graphql)

    threads = get_review_threads(42, "owner", "repo")

    assert len(threads) == 2
    assert call_count["n"] == 2


def test_get_review_threads_empty(monkeypatch):
    """Empty PR returns empty list."""
    response = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [],
                    }
                }
            }
        }
    }
    monkeypatch.setattr(
        "guardrails_review.threads.graphql",
        lambda query, variables=None: response,
    )

    assert get_review_threads(1, "o", "r") == []


# --- get_our_threads ---


def test_get_our_threads_filters_by_marker():
    """Only threads with guardrails-review marker are returned."""
    threads = [
        ReviewThread(
            thread_id="t1",
            path="a.py",
            line=1,
            body="<!-- guardrails-review -->\nOur comment",
            is_resolved=False,
            is_outdated=False,
            author="bot",
            created_at="2024-01-01T00:00:00Z",
        ),
        ReviewThread(
            thread_id="t2",
            path="b.py",
            line=2,
            body="Some other bot's comment",
            is_resolved=False,
            is_outdated=False,
            author="other-bot",
            created_at="2024-01-01T00:00:00Z",
        ),
    ]

    ours = get_our_threads(threads)

    assert len(ours) == 1
    assert ours[0].thread_id == "t1"


def test_get_our_threads_empty():
    """No threads with marker returns empty list."""
    threads = [
        ReviewThread(
            thread_id="t1",
            path="a.py",
            line=1,
            body="Not ours",
            is_resolved=False,
            is_outdated=False,
            author="bot",
            created_at="2024-01-01T00:00:00Z",
        ),
    ]
    assert get_our_threads(threads) == []


# --- find_resolvable_threads ---


def test_find_resolvable_file_deleted():
    """Thread on a deleted file is resolvable."""
    threads = [
        ReviewThread(
            thread_id="t1",
            path="deleted.py",
            line=5,
            body="<!-- guardrails-review -->\nBug",
            is_resolved=False,
            is_outdated=False,
            author="bot",
            created_at="2024-01-01T00:00:00Z",
        ),
    ]

    resolutions = find_resolvable_threads(
        threads,
        valid_lines={},
        deleted_files={"deleted.py"},
        head_sha="abc123",
    )

    assert len(resolutions) == 1
    assert resolutions[0].resolved is True
    assert "removed" in resolutions[0].reason.lower()


def test_find_resolvable_outdated():
    """Thread marked outdated by GitHub is resolvable."""
    threads = [
        ReviewThread(
            thread_id="t1",
            path="changed.py",
            line=5,
            body="<!-- guardrails-review -->\nBug",
            is_resolved=False,
            is_outdated=True,
            author="bot",
            created_at="2024-01-01T00:00:00Z",
        ),
    ]

    resolutions = find_resolvable_threads(
        threads,
        valid_lines={"changed.py": {10, 11}},
        deleted_files=set(),
        head_sha="abc123",
    )

    assert len(resolutions) == 1
    assert resolutions[0].resolved is True
    assert "outdated" in resolutions[0].reason.lower()


def test_find_resolvable_line_no_longer_in_diff():
    """Thread on a line no longer in the diff is resolvable."""
    threads = [
        ReviewThread(
            thread_id="t1",
            path="f.py",
            line=5,
            body="<!-- guardrails-review -->\nBug",
            is_resolved=False,
            is_outdated=False,
            author="bot",
            created_at="2024-01-01T00:00:00Z",
        ),
    ]

    resolutions = find_resolvable_threads(
        threads,
        valid_lines={"f.py": {10, 11}},
        deleted_files=set(),
        head_sha="abc123",
    )

    assert len(resolutions) == 1
    assert resolutions[0].resolved is True
    assert "abc123" in resolutions[0].reason


def test_find_resolvable_still_valid():
    """Thread on a line still in the diff is NOT resolvable."""
    threads = [
        ReviewThread(
            thread_id="t1",
            path="f.py",
            line=10,
            body="<!-- guardrails-review -->\nBug",
            is_resolved=False,
            is_outdated=False,
            author="bot",
            created_at="2024-01-01T00:00:00Z",
        ),
    ]

    resolutions = find_resolvable_threads(
        threads,
        valid_lines={"f.py": {10, 11}},
        deleted_files=set(),
        head_sha="abc123",
    )

    assert len(resolutions) == 0


def test_find_resolvable_skips_already_resolved():
    """Already resolved threads are skipped."""
    threads = [
        ReviewThread(
            thread_id="t1",
            path="deleted.py",
            line=5,
            body="<!-- guardrails-review -->\nBug",
            is_resolved=True,
            is_outdated=False,
            author="bot",
            created_at="2024-01-01T00:00:00Z",
        ),
    ]

    resolutions = find_resolvable_threads(
        threads,
        valid_lines={},
        deleted_files={"deleted.py"},
        head_sha="abc123",
    )

    assert len(resolutions) == 0


# --- deduplicate_comments ---


def test_deduplicate_removes_exact_match():
    """Comment with same path+line+body as existing thread is removed."""
    new_comments = [
        ReviewComment(
            path="f.py",
            line=10,
            body="<!-- guardrails-review -->\nBug here",
            severity="error",
        ),
        ReviewComment(
            path="f.py",
            line=20,
            body="<!-- guardrails-review -->\nNew finding",
            severity="error",
        ),
    ]
    existing = [
        ReviewThread(
            thread_id="t1",
            path="f.py",
            line=10,
            body="<!-- guardrails-review -->\nBug here",
            is_resolved=False,
            is_outdated=False,
            author="bot",
            created_at="2024-01-01T00:00:00Z",
        ),
    ]

    deduped = deduplicate_comments(new_comments, existing)

    assert len(deduped) == 1
    assert deduped[0].line == 20


def test_deduplicate_ignores_resolved():
    """Resolved threads don't count for deduplication."""
    new_comments = [
        ReviewComment(
            path="f.py",
            line=10,
            body="<!-- guardrails-review -->\nBug here",
            severity="error",
        ),
    ]
    existing = [
        ReviewThread(
            thread_id="t1",
            path="f.py",
            line=10,
            body="<!-- guardrails-review -->\nBug here",
            is_resolved=True,
            is_outdated=False,
            author="bot",
            created_at="2024-01-01T00:00:00Z",
        ),
    ]

    deduped = deduplicate_comments(new_comments, existing)

    assert len(deduped) == 1


def test_deduplicate_no_existing():
    """No existing threads means all comments pass through."""
    new_comments = [
        ReviewComment(path="f.py", line=10, body="Bug", severity="error"),
    ]

    deduped = deduplicate_comments(new_comments, [])

    assert len(deduped) == 1
