"""Tests for guardrails_review.parser module."""

from __future__ import annotations

import json

from guardrails_review.parser import (
    _try_parse_json,
    parse_response,
    parse_submit_review_args,
)
from guardrails_review.types import REVIEW_MARKER


def test_try_parse_json_valid():
    """Valid JSON string parses successfully."""
    result = _try_parse_json('{"key": "value"}')
    assert result == {"key": "value"}


def test_try_parse_json_invalid():
    """Invalid JSON returns None."""
    result = _try_parse_json("not json at all")
    assert result is None


def test_try_parse_json_code_block():
    """JSON inside markdown code block is extracted."""
    raw = '```json\n{"verdict": "approve"}\n```'
    result = _try_parse_json(raw)
    assert result == {"verdict": "approve"}


def test_try_parse_json_code_block_no_lang():
    """JSON inside bare code block (no language tag) is extracted."""
    raw = '```\n{"verdict": "approve"}\n```'
    result = _try_parse_json(raw)
    assert result == {"verdict": "approve"}


def test_try_parse_json_code_block_invalid():
    """Invalid JSON inside code block returns None."""
    raw = "```json\nnot json\n```"
    result = _try_parse_json(raw)
    assert result is None


def test_parse_response_valid():
    """Valid JSON response produces correct ReviewResult."""
    raw = json.dumps({"verdict": "approve", "summary": "LGTM", "comments": []})
    result = parse_response(raw, "test/model", 42)

    assert result.verdict == "approve"
    assert REVIEW_MARKER in result.summary
    assert "LGTM" in result.summary
    assert result.model == "test/model"
    assert result.pr == 42


def test_parse_response_malformed():
    """Non-JSON response produces fallback result."""
    result = parse_response("garbage", "m", 1)

    assert result.verdict == "request_changes"
    assert "non-JSON" in result.summary
    assert result.comments == []


def test_parse_response_filters_incomplete_comments():
    """Comments missing path or line are filtered out."""
    raw = json.dumps(
        {
            "verdict": "approve",
            "summary": "OK",
            "comments": [
                {"path": "", "line": 10, "body": "no path"},
                {"path": "f.py", "line": 0, "body": "no line"},
                {"path": "f.py", "line": 5, "body": "valid"},
            ],
        }
    )
    result = parse_response(raw, "m", 1)

    assert len(result.comments) == 1
    assert "valid" in result.comments[0].body


def test_parse_response_adds_marker_to_summary():
    """Summary without marker gets marker prepended."""
    raw = json.dumps({"verdict": "approve", "summary": "Clean", "comments": []})
    result = parse_response(raw, "m", 1)

    assert result.summary.startswith(REVIEW_MARKER)


def test_parse_response_no_duplicate_marker():
    """Summary already containing marker does not get it duplicated."""
    raw = json.dumps({"verdict": "approve", "summary": f"{REVIEW_MARKER}\nClean", "comments": []})
    result = parse_response(raw, "m", 1)

    assert result.summary.count(REVIEW_MARKER) == 1


def test_parse_response_adds_marker_to_comment_body():
    """Comment bodies get the review marker prepended."""
    raw = json.dumps(
        {
            "verdict": "approve",
            "summary": "OK",
            "comments": [{"path": "f.py", "line": 1, "body": "Bug here"}],
        }
    )
    result = parse_response(raw, "m", 1)

    assert result.comments[0].body.startswith(REVIEW_MARKER)


def test_parse_response_invalid_verdict_defaults():
    """Unknown verdict defaults to request_changes."""
    raw = json.dumps({"verdict": "maybe", "summary": "Hmm", "comments": []})
    result = parse_response(raw, "m", 1)

    assert result.verdict == "request_changes"


def test_parse_response_sets_timestamp():
    """parse_response sets a non-empty ISO timestamp."""
    raw = json.dumps({"verdict": "approve", "summary": "OK", "comments": []})
    result = parse_response(raw, "m", 1)

    assert result.timestamp != ""
    assert "T" in result.timestamp


def test_parse_submit_review_args():
    """parse_submit_review_args builds ReviewResult from tool call JSON."""
    args = json.dumps(
        {
            "verdict": "approve",
            "summary": f"{REVIEW_MARKER}\nLooks good",
            "comments": [{"path": "f.py", "line": 5, "body": "nice"}],
        }
    )
    result = parse_submit_review_args(args, "test/model", 42)

    assert result.verdict == "approve"
    assert "Looks good" in result.summary
    assert len(result.comments) == 1
    assert result.comments[0].severity == "error"
    assert result.pr == 42
