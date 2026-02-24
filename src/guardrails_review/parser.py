"""Response parsing for LLM review output."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from guardrails_review.types import (
    REVIEW_MARKER,
    ReviewComment,
    ReviewResult,
)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_response(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"{REVIEW_MARKER}\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def parse_submit_review_args(arguments: str, model: str, pr: int) -> ReviewResult:
    """Parse the submit_review tool call arguments into a ReviewResult."""
    timestamp = datetime.now(tz=UTC).isoformat()
    parsed = json.loads(arguments)
    return _build_result_from_parsed(parsed, model, pr, timestamp)


def _build_result_from_parsed(
    parsed: dict[str, Any], model: str, pr: int, timestamp: str
) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=(
                f"{REVIEW_MARKER}\n{c.get('body', '')}"
                if REVIEW_MARKER not in c.get("body", "")
                else c.get("body", "")
            ),
            severity="error",
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if REVIEW_MARKER not in summary:
        summary = f"{REVIEW_MARKER}\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def _try_parse_json(raw: str) -> dict[str, Any] | None:
    """Attempt to parse JSON, trying raw first then extracting from code blocks."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    match = _JSON_BLOCK_RE.search(raw)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    return None
