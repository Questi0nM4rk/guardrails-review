"""Local JSON cache for review results.

Stores reviews as append-only JSON files in `.guardrails-review/cache/`
relative to the project root. Files are named `pr-{N}-{timestamp}.json`.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path

from guardrails_review.types import ReviewComment, ReviewResult

_CACHE_SUBDIR = Path(".guardrails-review") / "cache"


def _cache_dir(project_dir: Path | None) -> Path:
    base = project_dir if project_dir is not None else Path.cwd()
    return base / _CACHE_SUBDIR


def save_review(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def _glob_for_pr(pr: int, project_dir: Path | None) -> list[Path]:
    """Return cached review files for a PR, sorted oldest to newest by name."""
    cache = _cache_dir(project_dir)
    if not cache.is_dir():
        return []
    return sorted(cache.glob(f"pr-{pr}-*.json"))


def _load_file(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def load_latest_review(pr: int, project_dir: Path | None = None) -> ReviewResult | None:
    """Load the most recent cached review for a PR.

    Returns None if no cached reviews exist.
    """
    files = _glob_for_pr(pr, project_dir)
    if not files:
        return None
    return _load_file(files[-1])


def load_all_reviews(pr: int, project_dir: Path | None = None) -> list[ReviewResult]:
    """Load all cached reviews for a PR, sorted oldest to newest."""
    files = _glob_for_pr(pr, project_dir)
    return [_load_file(f) for f in files]
