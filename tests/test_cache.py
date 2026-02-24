"""Tests for the local JSON cache module."""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING

from guardrails_review.cache import load_all_reviews, load_latest_review, save_review

if TYPE_CHECKING:
    from pathlib import Path
from guardrails_review.types import ReviewComment, ReviewResult


def _make_result(
    pr: int = 42,
    verdict: str = "approve",
    summary: str = "Looks good",
    timestamp: str = "2026-02-24T12:00:00Z",
    model: str = "claude-opus-4-20250514",
) -> ReviewResult:
    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=[
            ReviewComment(
                path="src/main.py",
                line=10,
                body="Unused import",
                severity="warning",
                start_line=None,
            ),
        ],
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def test_save_review_creates_cache_dir(tmp_path: Path) -> None:
    """Cache directory is created if it does not exist."""
    result = _make_result()
    save_review(result, project_dir=tmp_path)

    cache_dir = tmp_path / ".guardrails-review" / "cache"
    assert cache_dir.is_dir()


def test_save_review_writes_json(tmp_path: Path) -> None:
    """Saved file contains valid JSON with all fields from ReviewResult."""
    result = _make_result()
    path = save_review(result, project_dir=tmp_path)

    data = json.loads(path.read_text())
    assert data["verdict"] == "approve"
    assert data["summary"] == "Looks good"
    assert data["model"] == "claude-opus-4-20250514"
    assert data["timestamp"] == "2026-02-24T12:00:00Z"
    assert data["pr"] == 42
    assert len(data["comments"]) == 1
    assert data["comments"][0]["path"] == "src/main.py"
    assert data["comments"][0]["line"] == 10
    assert data["comments"][0]["body"] == "Unused import"
    assert data["comments"][0]["severity"] == "warning"
    assert data["comments"][0]["start_line"] is None


def test_save_review_filename_format(tmp_path: Path) -> None:
    """Filename matches pr-{N}-{timestamp}.json pattern."""
    result = _make_result(pr=7)
    path = save_review(result, project_dir=tmp_path)

    assert re.match(r"^pr-7-\d{8}T\d{6}\.json$", path.name)


def test_save_review_returns_absolute_path(tmp_path: Path) -> None:
    """Returned path is absolute."""
    result = _make_result()
    path = save_review(result, project_dir=tmp_path)

    assert path.is_absolute()
    assert path.exists()


def test_load_latest_review_returns_most_recent(tmp_path: Path) -> None:
    """With multiple cached reviews, returns the most recent one."""
    old = _make_result(pr=5, summary="Old review")
    save_review(old, project_dir=tmp_path)

    # Small delay so timestamps differ in filenames
    time.sleep(0.01)

    new = _make_result(pr=5, summary="New review")
    save_review(new, project_dir=tmp_path)

    loaded = load_latest_review(pr=5, project_dir=tmp_path)
    assert loaded is not None
    assert loaded.summary == "New review"


def test_load_latest_review_no_cache(tmp_path: Path) -> None:
    """Returns None when no reviews are cached for the PR."""
    loaded = load_latest_review(pr=999, project_dir=tmp_path)
    assert loaded is None


def test_load_latest_review_no_cache_dir(tmp_path: Path) -> None:
    """Returns None when the cache directory does not exist."""
    loaded = load_latest_review(pr=1, project_dir=tmp_path)
    assert loaded is None


def test_load_all_reviews_sorted(tmp_path: Path) -> None:
    """Returns reviews sorted oldest to newest."""
    for i in range(3):
        r = _make_result(pr=10, summary=f"Review {i}")
        save_review(r, project_dir=tmp_path)
        time.sleep(0.01)

    reviews = load_all_reviews(pr=10, project_dir=tmp_path)
    assert len(reviews) == 3
    assert reviews[0].summary == "Review 0"
    assert reviews[1].summary == "Review 1"
    assert reviews[2].summary == "Review 2"


def test_load_all_reviews_empty(tmp_path: Path) -> None:
    """Returns empty list when no reviews exist for the PR."""
    reviews = load_all_reviews(pr=999, project_dir=tmp_path)
    assert reviews == []


def test_load_all_reviews_no_cache_dir(tmp_path: Path) -> None:
    """Returns empty list when cache directory does not exist."""
    reviews = load_all_reviews(pr=1, project_dir=tmp_path)
    assert reviews == []


def test_roundtrip(tmp_path: Path) -> None:
    """Save then load returns an equivalent ReviewResult."""
    original = _make_result(pr=3)
    save_review(original, project_dir=tmp_path)

    loaded = load_latest_review(pr=3, project_dir=tmp_path)
    assert loaded is not None
    assert loaded.verdict == original.verdict
    assert loaded.summary == original.summary
    assert loaded.model == original.model
    assert loaded.timestamp == original.timestamp
    assert loaded.pr == original.pr
    assert len(loaded.comments) == len(original.comments)
    assert loaded.comments[0].path == original.comments[0].path
    assert loaded.comments[0].line == original.comments[0].line
    assert loaded.comments[0].body == original.comments[0].body
    assert loaded.comments[0].severity == original.comments[0].severity
    assert loaded.comments[0].start_line == original.comments[0].start_line


def test_roundtrip_no_comments(tmp_path: Path) -> None:
    """Roundtrip works for a result with no comments."""
    original = ReviewResult(verdict="approve", summary="Clean", pr=8)
    save_review(original, project_dir=tmp_path)

    loaded = load_latest_review(pr=8, project_dir=tmp_path)
    assert loaded is not None
    assert loaded.comments == []
    assert loaded.verdict == "approve"


def test_load_filters_by_pr(tmp_path: Path) -> None:
    """Reviews for different PRs do not interfere."""
    save_review(_make_result(pr=1, summary="PR 1"), project_dir=tmp_path)
    save_review(_make_result(pr=2, summary="PR 2"), project_dir=tmp_path)

    loaded = load_latest_review(pr=1, project_dir=tmp_path)
    assert loaded is not None
    assert loaded.summary == "PR 1"

    all_pr2 = load_all_reviews(pr=2, project_dir=tmp_path)
    assert len(all_pr2) == 1
    assert all_pr2[0].summary == "PR 2"
