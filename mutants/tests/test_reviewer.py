"""Tests for the review orchestrator."""

from __future__ import annotations

import json
import subprocess

from guardrails_review.reviewer import (
    _compute_verdict,
    _run_agentic_review,
    build_agentic_messages,
    build_messages,
    parse_response,
    parse_submit_review_args,
    run_review,
    validate_comments,
)
from guardrails_review.types import LLMResponse, ReviewComment, ReviewConfig, ToolCall


def test_build_messages_basic():
    """Build messages includes system prompt, PR title, and diff."""
    config = ReviewConfig(model="test/model")
    pr_meta = {"title": "Fix bug", "body": "Fixes #1"}
    messages = build_messages("diff content", config, pr_meta)

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "code reviewer" in messages[0]["content"]
    assert "Fix bug" in messages[1]["content"]
    assert "diff content" in messages[1]["content"]


def test_build_messages_with_extra_instructions():
    """Extra instructions appear in user message."""
    config = ReviewConfig(model="test/model", extra_instructions="Check security")
    messages = build_messages("diff", config, {"title": "T", "body": ""})

    assert "Check security" in messages[1]["content"]


def test_build_messages_truncates_diff():
    """Long diffs are truncated to max_diff_chars."""
    config = ReviewConfig(model="test/model", max_diff_chars=10)
    messages = build_messages("x" * 100, config, {"title": "T", "body": ""})

    # The diff portion should be truncated
    assert "x" * 100 not in messages[1]["content"]
    assert "x" * 10 in messages[1]["content"]


def test_build_agentic_messages_uses_agentic_prompt():
    """Agentic messages use the agentic system prompt with tool instructions."""
    config = ReviewConfig(model="test/model")
    messages = build_agentic_messages("diff", config, {"title": "T", "body": ""})

    assert len(messages) == 2
    assert "tools" in messages[0]["content"].lower()
    assert "submit_review" in messages[0]["content"]


def test_parse_response_valid_json():
    """Valid JSON response parsed into ReviewResult."""
    raw = json.dumps(
        {
            "verdict": "approve",
            "summary": "LGTM",
            "comments": [
                {"path": "foo.py", "line": 10, "severity": "info", "body": "Nice"},
            ],
        }
    )
    result = parse_response(raw, "test/model", 42)

    assert result.verdict == "approve"
    assert "LGTM" in result.summary
    assert len(result.comments) == 1
    assert result.comments[0].path == "foo.py"
    assert result.pr == 42
    assert result.model == "test/model"


def test_parse_response_malformed_json():
    """Non-JSON response falls back to summary-only result."""
    result = parse_response("This is not JSON at all.", "test/model", 1)

    assert result.verdict == "request_changes"
    assert "non-JSON" in result.summary
    assert result.comments == []


def test_parse_response_json_in_code_block():
    """JSON wrapped in markdown code block is extracted."""
    raw = '```json\n{"verdict": "approve", "summary": "OK", "comments": []}\n```'
    result = parse_response(raw, "test/model", 1)

    assert result.verdict == "approve"
    assert "OK" in result.summary


def test_parse_response_invalid_verdict_defaults():
    """Unknown verdict string defaults to request_changes."""
    raw = json.dumps({"verdict": "maybe", "summary": "Hmm", "comments": []})
    result = parse_response(raw, "m", 1)

    assert result.verdict == "request_changes"


def test_parse_response_adds_html_marker():
    """Summary gets guardrails-review HTML comment if missing."""
    raw = json.dumps({"verdict": "approve", "summary": "Clean", "comments": []})
    result = parse_response(raw, "m", 1)

    assert "<!-- guardrails-review -->" in result.summary


def test_parse_response_skips_incomplete_comments():
    """Comments missing path or line are filtered out."""
    raw = json.dumps(
        {
            "verdict": "approve",
            "summary": "OK",
            "comments": [
                {"path": "", "line": 10, "severity": "info", "body": "no path"},
                {"path": "f.py", "line": 0, "severity": "info", "body": "no line"},
                {"path": "f.py", "line": 5, "severity": "info", "body": "valid"},
            ],
        }
    )
    result = parse_response(raw, "m", 1)

    assert len(result.comments) == 1
    assert result.comments[0].body == "valid"


def test_parse_submit_review_args():
    """parse_submit_review_args builds ReviewResult from tool call arguments."""
    args = json.dumps(
        {
            "verdict": "approve",
            "summary": "<!-- guardrails-review -->\nLooks good",
            "comments": [{"path": "f.py", "line": 5, "severity": "info", "body": "nice"}],
        }
    )

    result = parse_submit_review_args(args, "test/model", 42)

    assert result.verdict == "approve"
    assert "Looks good" in result.summary
    assert len(result.comments) == 1
    assert result.pr == 42


def test_validate_comments_splits_correctly():
    """Comments are split into valid and invalid based on diff lines."""
    valid_lines = {"foo.py": {10, 11, 12}, "bar.py": {5}}
    comments = [
        ReviewComment(path="foo.py", line=10, body="ok", severity="info"),
        ReviewComment(path="foo.py", line=99, body="bad line", severity="error"),
        ReviewComment(path="baz.py", line=1, body="wrong file", severity="warning"),
    ]
    valid, invalid = validate_comments(comments, valid_lines)

    assert len(valid) == 1
    assert valid[0].line == 10
    assert len(invalid) == 2


def test_compute_verdict_error_blocks():
    """Error-severity comment triggers request_changes."""
    config = ReviewConfig(model="m", severity_threshold="error")
    comments = [ReviewComment(path="f.py", line=1, body="x", severity="error")]

    assert _compute_verdict(comments, config) == "request_changes"


def test_compute_verdict_warning_passes_default():
    """Warning-only comments approve when threshold is error."""
    config = ReviewConfig(model="m", severity_threshold="error", auto_approve=True)
    comments = [ReviewComment(path="f.py", line=1, body="x", severity="warning")]

    assert _compute_verdict(comments, config) == "approve"


def test_compute_verdict_warning_blocks_when_threshold():
    """Warning-severity comment blocks when threshold is warning."""
    config = ReviewConfig(model="m", severity_threshold="warning")
    comments = [ReviewComment(path="f.py", line=1, body="x", severity="warning")]

    assert _compute_verdict(comments, config) == "request_changes"


def test_compute_verdict_no_comments_auto_approve():
    """No comments with auto_approve=True gives approve."""
    config = ReviewConfig(model="m", auto_approve=True)

    assert _compute_verdict([], config) == "approve"


def test_compute_verdict_no_comments_no_auto_approve():
    """No comments with auto_approve=False gives request_changes."""
    config = ReviewConfig(model="m", auto_approve=False)

    assert _compute_verdict([], config) == "request_changes"


def _make_gh_mock(responses: dict[str, tuple[int, str]]):
    """Create a subprocess.run mock that maps command patterns to responses."""

    def mock_run(args, **kwargs):
        cmd = " ".join(str(a) for a in args)
        for pattern, (rc, stdout) in responses.items():
            if pattern in cmd:
                return subprocess.CompletedProcess(args, rc, stdout, "")
        return subprocess.CompletedProcess(args, 0, "", "")

    return mock_run


# --- Oneshot run_review tests (agentic=False) ---


def test_run_review_dry_run(tmp_path, monkeypatch, capsys):
    """Dry run prints result without posting to GitHub."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text(
        '[config]\nmodel = "test/m"\n[review]\nauto_approve = true\nagentic = false\n'
    )
    monkeypatch.chdir(tmp_path)

    diff_text = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n+++ b/foo.py\n"
        "@@ -1,3 +1,4 @@\n context\n+added line\n more\n end\n"
    )
    pr_meta = {
        "title": "Test",
        "body": "desc",
        "headRefOid": "abc123",
        "baseRefName": "main",
    }
    llm_response = json.dumps(
        {
            "verdict": "approve",
            "summary": "<!-- guardrails-review -->\nLGTM",
            "comments": [],
        }
    )

    monkeypatch.setattr("guardrails_review.reviewer.get_pr_diff", lambda pr: diff_text)
    monkeypatch.setattr("guardrails_review.reviewer.get_pr_metadata", lambda pr: pr_meta)
    monkeypatch.setattr(
        "guardrails_review.reviewer.call_openrouter", lambda msgs, model: llm_response
    )

    result = run_review(53, dry_run=True, project_dir=tmp_path)

    assert result == 0
    captured = capsys.readouterr()
    assert "Dry Run" in captured.out
    assert "approve" in captured.out


def test_run_review_posts_and_caches(tmp_path, monkeypatch):
    """Full review posts to GitHub and saves to cache."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text(
        '[config]\nmodel = "test/m"\n[review]\nauto_approve = true\nagentic = false\n'
    )

    diff_text = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n+++ b/foo.py\n"
        "@@ -1,3 +1,4 @@\n context\n+added line\n more\n end\n"
    )
    pr_meta_dict = {"title": "Test", "body": "desc", "headRefOid": "abc123", "baseRefName": "main"}
    llm_response = json.dumps(
        {
            "verdict": "approve",
            "summary": "<!-- guardrails-review -->\nLGTM",
            "comments": [],
        }
    )

    posted = []
    monkeypatch.setattr("guardrails_review.reviewer.get_pr_diff", lambda pr: diff_text)
    monkeypatch.setattr("guardrails_review.reviewer.get_pr_metadata", lambda pr: pr_meta_dict)
    monkeypatch.setattr(
        "guardrails_review.reviewer.call_openrouter", lambda msgs, model: llm_response
    )
    monkeypatch.setattr("guardrails_review.reviewer.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(
        "guardrails_review.reviewer.post_review",
        lambda pr, result, owner, repo, sha: posted.append(result) or True,
    )

    result = run_review(53, project_dir=tmp_path)

    assert result == 0
    assert len(posted) == 1
    assert posted[0].verdict == "approve"

    # Verify cache was written
    cache_dir = tmp_path / ".guardrails-review" / "cache"
    assert cache_dir.exists()
    cache_files = list(cache_dir.glob("pr-53-*.json"))
    assert len(cache_files) == 1


def test_run_review_invalid_lines_in_summary(tmp_path, monkeypatch, capsys):
    """Comments on invalid lines are moved to the review summary."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text(
        '[config]\nmodel = "test/m"\n[review]\nauto_approve = true\nagentic = false\n'
    )

    diff_text = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n+++ b/foo.py\n"
        "@@ -1,2 +1,3 @@\n context\n+new\n end\n"
    )
    llm_response = json.dumps(
        {
            "verdict": "approve",
            "summary": "<!-- guardrails-review -->\nLooks good",
            "comments": [
                {"path": "foo.py", "line": 999, "severity": "info", "body": "Out of range"},
            ],
        }
    )

    monkeypatch.setattr("guardrails_review.reviewer.get_pr_diff", lambda pr: diff_text)
    pr_meta = {"title": "T", "body": "", "headRefOid": "sha", "baseRefName": "main"}
    monkeypatch.setattr("guardrails_review.reviewer.get_pr_metadata", lambda pr: pr_meta)
    monkeypatch.setattr(
        "guardrails_review.reviewer.call_openrouter", lambda msgs, model: llm_response
    )

    result = run_review(53, dry_run=True, project_dir=tmp_path)

    assert result == 0
    captured = capsys.readouterr()
    assert "outside diff" in captured.out
    assert "foo.py:999" in captured.out


def test_oneshot_still_works(tmp_path, monkeypatch, capsys):
    """Explicit agentic=false still uses oneshot path and produces correct results."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text(
        '[config]\nmodel = "test/m"\n[review]\nauto_approve = true\nagentic = false\n'
    )

    diff_text = (
        "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -1,2 +1,3 @@\n ctx\n+new\n end\n"
    )
    llm_response = json.dumps(
        {
            "verdict": "approve",
            "summary": "<!-- guardrails-review -->\nAll clear",
            "comments": [],
        }
    )

    monkeypatch.setattr("guardrails_review.reviewer.get_pr_diff", lambda pr: diff_text)
    monkeypatch.setattr(
        "guardrails_review.reviewer.get_pr_metadata",
        lambda pr: {
            "title": "T",
            "body": "",
            "headRefOid": "sha",
            "baseRefName": "main",
        },
    )
    monkeypatch.setattr(
        "guardrails_review.reviewer.call_openrouter", lambda msgs, model: llm_response
    )

    result = run_review(1, dry_run=True, project_dir=tmp_path)

    assert result == 0
    captured = capsys.readouterr()
    assert "approve" in captured.out
    assert "All clear" in captured.out


# --- Agentic review tests ---


_REVIEWER = "guardrails_review.reviewer"


def test_agentic_loop_calls_tools_then_submits(monkeypatch):
    """Agentic loop executes tools then processes submit_review to produce ReviewResult."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=5)
    diff = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -1,2 +1,3 @@\n ctx\n+new\n end\n"
    pr_meta = {"title": "T", "body": "", "headRefOid": "sha123", "baseRefName": "main"}

    call_count = {"n": 0}

    def fake_call_openrouter_tools(messages, model, *, tools, tool_choice=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="c1", name="read_file", arguments='{"path": "f.py"}'),
                ],
                finish_reason="tool_calls",
            )
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="c2",
                    name="submit_review",
                    arguments=json.dumps(
                        {
                            "verdict": "approve",
                            "summary": "<!-- guardrails-review -->\nLGTM",
                            "comments": [],
                        }
                    ),
                )
            ],
            finish_reason="tool_calls",
        )

    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call_openrouter_tools)
    monkeypatch.setattr(f"{_REVIEWER}.execute_tool", lambda n, a, c: "1: code\n")

    result = _run_agentic_review(config, diff, pr_meta, pr=42)

    assert result.verdict == "approve"
    assert "LGTM" in result.summary
    assert call_count["n"] == 2


def test_agentic_loop_max_iterations_forces_submit(monkeypatch):
    """When max_iterations is reached, tool_choice forces submit_review."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=2)
    diff = "diff --git a/f.py b/f.py\n"
    pr_meta = {
        "title": "T",
        "body": "",
        "headRefOid": "sha",
        "baseRefName": "main",
    }

    call_count = {"n": 0}
    captured_tool_choice = {"val": None}

    def fake_call(messages, model, *, tools, tool_choice=None):
        call_count["n"] += 1
        captured_tool_choice["val"] = tool_choice
        if call_count["n"] == 1:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="c1", name="read_file", arguments='{"path": "f.py"}'),
                ],
                finish_reason="tool_calls",
            )
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id="c2",
                    name="submit_review",
                    arguments=json.dumps(
                        {
                            "verdict": "request_changes",
                            "summary": "<!-- guardrails-review -->\nNeeds work",
                            "comments": [],
                        }
                    ),
                )
            ],
            finish_reason="tool_calls",
        )

    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call)
    monkeypatch.setattr(f"{_REVIEWER}.execute_tool", lambda n, a, c: "content")

    result = _run_agentic_review(config, diff, pr_meta, pr=1)

    assert result.verdict == "request_changes"
    assert call_count["n"] == 2
    assert captured_tool_choice["val"] is not None
    assert captured_tool_choice["val"]["function"]["name"] == "submit_review"


def test_agentic_fallback_to_oneshot(monkeypatch):
    """When agentic API call raises RuntimeError, falls back to oneshot."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=5)
    diff = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -1,2 +1,3 @@\n ctx\n+new\n end\n"
    pr_meta = {
        "title": "T",
        "body": "",
        "headRefOid": "sha",
        "baseRefName": "main",
    }

    _api_err = "API error 400: tools not supported"

    def fake_call_tools(messages, model, *, tools, tool_choice=None):
        raise RuntimeError(_api_err)

    def fake_call(messages, model):
        return json.dumps(
            {
                "verdict": "approve",
                "summary": "<!-- guardrails-review -->\nFallback review",
                "comments": [],
            }
        )

    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call_tools)
    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter", fake_call)

    result = _run_agentic_review(config, diff, pr_meta, pr=1)

    assert result.verdict == "approve"
    assert "Fallback review" in result.summary


def test_parse_response_comment_defaults():
    """Comments with missing optional fields get correct defaults."""
    raw = json.dumps(
        {
            "verdict": "approve",
            "summary": "<!-- guardrails-review -->\nOK",
            "comments": [
                {"path": "f.py", "line": 5},  # missing body, severity, start_line
            ],
        }
    )
    result = parse_response(raw, "m", 1)

    assert len(result.comments) == 1
    c = result.comments[0]
    assert c.body == ""
    assert c.severity == "info"
    assert c.start_line is None


def test_parse_response_timestamp_is_set():
    """parse_response sets a non-empty timestamp."""
    raw = json.dumps({"verdict": "approve", "summary": "OK", "comments": []})
    result = parse_response(raw, "m", 1)
    assert result.timestamp != ""
    assert "T" in result.timestamp  # ISO format


def test_parse_response_preserves_existing_html_marker():
    """If the summary already has the marker, it should not be duplicated."""
    raw = json.dumps(
        {
            "verdict": "approve",
            "summary": "<!-- guardrails-review -->\nAlready there",
            "comments": [],
        }
    )
    result = parse_response(raw, "m", 1)
    # Marker appears exactly once
    assert result.summary.count("<!-- guardrails-review -->") == 1


def test_parse_response_with_start_line():
    """Comments with start_line preserve it correctly."""
    raw = json.dumps(
        {
            "verdict": "approve",
            "summary": "OK",
            "comments": [
                {
                    "path": "f.py",
                    "line": 10,
                    "severity": "warning",
                    "body": "multi-line issue",
                    "start_line": 7,
                },
            ],
        }
    )
    result = parse_response(raw, "m", 1)

    assert len(result.comments) == 1
    assert result.comments[0].start_line == 7
    assert result.comments[0].line == 10


def test_build_result_verdict_default_when_missing():
    """Missing verdict defaults to request_changes."""
    raw = json.dumps({"summary": "No verdict key", "comments": []})
    result = parse_response(raw, "m", 1)
    assert result.verdict == "request_changes"


def test_build_result_summary_default_when_missing():
    """Missing summary gets a default value."""
    raw = json.dumps({"verdict": "approve", "comments": []})
    result = parse_response(raw, "m", 1)
    assert "No summary provided" in result.summary or result.summary != ""


def test_compute_verdict_info_only_approves():
    """Info-only comments approve regardless of threshold."""
    config = ReviewConfig(model="m", severity_threshold="error", auto_approve=True)
    comments = [ReviewComment(path="f.py", line=1, body="x", severity="info")]
    assert _compute_verdict(comments, config) == "approve"


def test_agentic_content_response_fallback(monkeypatch):
    """Model returning content instead of tool calls in agentic mode is parsed as JSON."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=5)
    diff = "diff --git a/f.py b/f.py\n"
    pr_meta = {
        "title": "T",
        "body": "",
        "headRefOid": "sha",
        "baseRefName": "main",
    }

    def fake_call(messages, model, *, tools, tool_choice=None):
        return LLMResponse(
            content=json.dumps(
                {
                    "verdict": "approve",
                    "summary": "<!-- guardrails-review -->\nDirect content",
                    "comments": [],
                }
            ),
            tool_calls=[],
            finish_reason="stop",
        )

    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call)

    result = _run_agentic_review(config, diff, pr_meta, pr=1)

    assert result.verdict == "approve"
    assert "Direct content" in result.summary
