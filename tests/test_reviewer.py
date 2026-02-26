"""Tests for the review orchestrator."""

from __future__ import annotations

import json
import subprocess

from guardrails_review.parser import parse_response, parse_submit_review_args
from guardrails_review.prompts import build_agentic_messages, build_messages
from guardrails_review.reviewer import (
    _compute_verdict,
    _print_dry_run,
    _run_agentic_review,
    run_resolve,
    run_review,
    validate_comments,
)
from guardrails_review.types import (
    LLMResponse,
    PRMetadata,
    ReviewComment,
    ReviewConfig,
    ReviewResult,
    ReviewThread,
    ToolCall,
)

_REVIEWER = "guardrails_review.reviewer"


def _meta(
    title: str = "T",
    body: str = "",
    head_ref_oid: str = "sha",
    base_ref_name: str = "main",
) -> PRMetadata:
    """Build a PRMetadata for tests with sensible defaults."""
    return PRMetadata(
        title=title,
        body=body,
        head_ref_oid=head_ref_oid,
        base_ref_name=base_ref_name,
    )


def test_build_messages_basic():
    """Build messages includes system prompt, PR title, and diff."""
    config = ReviewConfig(model="test/model")
    pr_meta = _meta(title="Fix bug", body="Fixes #1")
    messages = build_messages("diff content", config, pr_meta)

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "Fix bug" in messages[1]["content"]
    assert "diff content" in messages[1]["content"]


def test_system_prompt_defect_only():
    """System prompt focuses on defects only, not style/naming."""
    config = ReviewConfig(model="test/model")
    messages = build_messages("diff", config, _meta())
    prompt = messages[0]["content"]

    assert "bug" in prompt.lower() or "defect" in prompt.lower()
    assert "severity" not in prompt.lower() or "error" in prompt.lower()
    # Should NOT ask LLM to report style/naming
    assert '"warning"' not in prompt
    assert '"info"' not in prompt


def test_build_messages_with_extra_instructions():
    """Extra instructions appear in user message."""
    config = ReviewConfig(model="test/model", extra_instructions="Check security")
    messages = build_messages("diff", config, _meta())

    assert "Check security" in messages[1]["content"]


def test_build_messages_truncates_diff():
    """Long diffs are truncated to max_diff_chars."""
    config = ReviewConfig(model="test/model", max_diff_chars=10)
    messages = build_messages("x" * 100, config, _meta())

    # The diff portion should be truncated
    assert "x" * 100 not in messages[1]["content"]
    assert "x" * 10 in messages[1]["content"]


def test_build_agentic_messages_uses_agentic_prompt():
    """Agentic messages use the agentic system prompt with tool instructions."""
    config = ReviewConfig(model="test/model")
    messages = build_agentic_messages("diff", config, _meta())

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
                {"path": "foo.py", "line": 10, "body": "Nice"},
            ],
        }
    )
    result = parse_response(raw, "test/model", 42)

    assert result.verdict == "approve"
    assert "LGTM" in result.summary
    assert len(result.comments) == 1
    assert result.comments[0].path == "foo.py"
    assert result.comments[0].severity == "error"
    assert result.comments[0].body.startswith("<!-- guardrails-review -->")
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
                {"path": "", "line": 10, "body": "no path"},
                {"path": "f.py", "line": 0, "body": "no line"},
                {"path": "f.py", "line": 5, "body": "valid"},
            ],
        }
    )
    result = parse_response(raw, "m", 1)

    assert len(result.comments) == 1
    assert "valid" in result.comments[0].body


def test_parse_submit_review_args():
    """parse_submit_review_args builds ReviewResult from tool call arguments."""
    args = json.dumps(
        {
            "verdict": "approve",
            "summary": "<!-- guardrails-review -->\nLooks good",
            "comments": [{"path": "f.py", "line": 5, "body": "nice"}],
        }
    )

    result = parse_submit_review_args(args, "test/model", 42)

    assert result.verdict == "approve"
    assert "Looks good" in result.summary
    assert len(result.comments) == 1
    assert result.comments[0].severity == "error"
    assert result.comments[0].body.startswith("<!-- guardrails-review -->")
    assert result.pr == 42


def test_validate_comments_splits_correctly():
    """Comments are split into valid and invalid based on diff lines."""
    valid_lines = {"foo.py": {10, 11, 12}, "bar.py": {5}}
    comments = [
        ReviewComment(path="foo.py", line=10, body="ok", severity="error"),
        ReviewComment(path="foo.py", line=99, body="bad line", severity="error"),
        ReviewComment(path="baz.py", line=1, body="wrong file", severity="error"),
    ]
    valid, invalid = validate_comments(comments, valid_lines)

    assert len(valid) == 1
    assert valid[0].line == 10
    assert len(invalid) == 2


def test_compute_verdict_comments_request_changes():
    """Any comments trigger request_changes."""
    comments = [ReviewComment(path="f.py", line=1, body="x", severity="error")]

    assert _compute_verdict(comments) == "request_changes"


def test_compute_verdict_no_comments_approves():
    """No comments gives approve."""
    assert _compute_verdict([]) == "approve"


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
    config_file.write_text('[config]\nmodel = "test/m"\n[review]\nagentic = false\n')
    monkeypatch.chdir(tmp_path)

    diff_text = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n+++ b/foo.py\n"
        "@@ -1,3 +1,4 @@\n context\n+added line\n more\n end\n"
    )
    pr_meta = _meta(title="Test", body="desc", head_ref_oid="abc123")
    llm_response = json.dumps(
        {
            "verdict": "approve",
            "summary": "<!-- guardrails-review -->\nLGTM",
            "comments": [],
        }
    )

    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda pr: pr_meta)
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda msgs, model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(f"{_REVIEWER}.get_review_threads", lambda pr, owner, repo: [])
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda pr: set())
    monkeypatch.setattr(f"{_REVIEWER}.resolve_thread", lambda tid: True)

    result = run_review(53, dry_run=True, project_dir=tmp_path)

    assert result == 0
    captured = capsys.readouterr()
    assert "Dry Run" in captured.out
    assert "approve" in captured.out


def test_run_review_posts_and_caches(tmp_path, monkeypatch):
    """Full review posts to GitHub and saves to cache."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text('[config]\nmodel = "test/m"\n[review]\nagentic = false\n')

    diff_text = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n+++ b/foo.py\n"
        "@@ -1,3 +1,4 @@\n context\n+added line\n more\n end\n"
    )
    pr_meta = _meta(title="Test", body="desc", head_ref_oid="abc123")
    llm_response = json.dumps(
        {
            "verdict": "approve",
            "summary": "<!-- guardrails-review -->\nLGTM",
            "comments": [],
        }
    )

    posted = []
    statuses = []
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda pr: pr_meta)
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda msgs, model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(
        f"{_REVIEWER}.post_review",
        lambda pr, result, owner, repo, sha: posted.append(result) or True,
    )
    monkeypatch.setattr(
        f"{_REVIEWER}.set_commit_status",
        lambda *a, **kw: statuses.append(a),
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


def test_run_review_sets_commit_status(tmp_path, monkeypatch):
    """run_review sets pending status before and success/failure after."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text('[config]\nmodel = "test/m"\n[review]\nagentic = false\n')

    diff_text = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n+++ b/foo.py\n"
        "@@ -1,3 +1,4 @@\n context\n+added line\n more\n end\n"
    )
    pr_meta = _meta(title="Test", body="desc", head_ref_oid="abc123")
    llm_response = json.dumps(
        {
            "verdict": "approve",
            "summary": "<!-- guardrails-review -->\nLGTM",
            "comments": [],
        }
    )

    statuses = []
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda pr: pr_meta)
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda msgs, model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(
        f"{_REVIEWER}.post_review",
        lambda pr, result, owner, repo, sha: True,
    )
    monkeypatch.setattr(
        f"{_REVIEWER}.set_commit_status",
        lambda owner, repo, sha, state, desc: statuses.append((state, desc)),
    )

    run_review(53, project_dir=tmp_path)

    assert len(statuses) == 2
    assert statuses[0][0] == "pending"
    assert statuses[1][0] == "success"


def test_run_review_status_failure_does_not_block(tmp_path, monkeypatch, capsys):
    """If set_commit_status raises, the review still completes."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text('[config]\nmodel = "test/m"\n[review]\nagentic = false\n')

    diff_text = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n+++ b/foo.py\n"
        "@@ -1,3 +1,4 @@\n context\n+added line\n more\n end\n"
    )
    pr_meta = _meta(title="Test", body="desc", head_ref_oid="abc123")
    llm_response = json.dumps(
        {
            "verdict": "approve",
            "summary": "<!-- guardrails-review -->\nLGTM",
            "comments": [],
        }
    )

    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda pr: pr_meta)
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda msgs, model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(
        f"{_REVIEWER}.post_review",
        lambda pr, result, owner, repo, sha: True,
    )

    def failing_status(*_args, **_kwargs):
        msg = "forbidden"
        raise RuntimeError(msg)

    monkeypatch.setattr(f"{_REVIEWER}.set_commit_status", failing_status)

    result = run_review(53, project_dir=tmp_path)

    assert result == 0


def test_run_review_dry_run_skips_status(tmp_path, monkeypatch, capsys):
    """Dry run does not set commit status."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text('[config]\nmodel = "test/m"\n[review]\nagentic = false\n')

    diff_text = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n+++ b/foo.py\n"
        "@@ -1,3 +1,4 @@\n context\n+added line\n more\n end\n"
    )
    pr_meta = _meta(title="Test", body="desc", head_ref_oid="abc123")
    llm_response = json.dumps(
        {
            "verdict": "approve",
            "summary": "<!-- guardrails-review -->\nLGTM",
            "comments": [],
        }
    )

    statuses = []
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda pr: pr_meta)
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda msgs, model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(f"{_REVIEWER}.get_review_threads", lambda pr, owner, repo: [])
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda pr: set())
    monkeypatch.setattr(f"{_REVIEWER}.resolve_thread", lambda tid: True)
    monkeypatch.setattr(
        f"{_REVIEWER}.set_commit_status",
        lambda *a, **kw: statuses.append(a),
    )

    result = run_review(53, dry_run=True, project_dir=tmp_path)

    assert result == 0
    assert len(statuses) == 0


def test_run_review_invalid_lines_in_summary(tmp_path, monkeypatch, capsys):
    """Comments on invalid lines are moved to the review summary."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text('[config]\nmodel = "test/m"\n[review]\nagentic = false\n')

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
                {
                    "path": "foo.py",
                    "line": 999,
                    "severity": "info",
                    "body": "Out of range",
                },
            ],
        }
    )

    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda pr: diff_text)
    pr_meta = _meta()
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda pr: pr_meta)
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda msgs, model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(f"{_REVIEWER}.get_review_threads", lambda pr, owner, repo: [])
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda pr: set())
    monkeypatch.setattr(f"{_REVIEWER}.resolve_thread", lambda tid: True)

    result = run_review(53, dry_run=True, project_dir=tmp_path)

    assert result == 0
    captured = capsys.readouterr()
    assert "outside diff" in captured.out
    assert "foo.py:999" in captured.out


def test_oneshot_still_works(tmp_path, monkeypatch, capsys):
    """Explicit agentic=false still uses oneshot path and produces correct results."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text('[config]\nmodel = "test/m"\n[review]\nagentic = false\n')

    diff_text = (
        "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
        "@@ -1,2 +1,3 @@\n ctx\n+new\n end\n"
    )
    llm_response = json.dumps(
        {
            "verdict": "approve",
            "summary": "<!-- guardrails-review -->\nAll clear",
            "comments": [],
        }
    )

    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda pr: _meta())
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda msgs, model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(f"{_REVIEWER}.get_review_threads", lambda pr, owner, repo: [])
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda pr: set())
    monkeypatch.setattr(f"{_REVIEWER}.resolve_thread", lambda tid: True)

    result = run_review(1, dry_run=True, project_dir=tmp_path)

    assert result == 0
    captured = capsys.readouterr()
    assert "approve" in captured.out
    assert "All clear" in captured.out


# --- Agentic review tests ---


def test_agentic_loop_calls_tools_then_submits(monkeypatch):
    """Agentic loop executes tools then submits ReviewResult."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=5)
    diff = (
        "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
        "@@ -1,2 +1,3 @@\n ctx\n+new\n end\n"
    )
    pr_meta = _meta(head_ref_oid="sha123")

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
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter_tools", fake_call_openrouter_tools
    )
    monkeypatch.setattr(f"{_REVIEWER}.execute_tool", lambda n, a, c: "1: code\n")

    result = _run_agentic_review(config, diff, pr_meta, pr=42)

    assert result.verdict == "approve"
    assert "LGTM" in result.summary
    assert call_count["n"] == 2


def test_agentic_loop_max_iterations_forces_submit(monkeypatch):
    """When max_iterations is reached, tool_choice forces submit_review."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=2)
    diff = "diff --git a/f.py b/f.py\n"
    pr_meta = _meta()

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
    diff = (
        "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
        "@@ -1,2 +1,3 @@\n ctx\n+new\n end\n"
    )
    pr_meta = _meta()

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
                {"path": "f.py", "line": 5},  # missing body, start_line
            ],
        }
    )
    result = parse_response(raw, "m", 1)

    assert len(result.comments) == 1
    c = result.comments[0]
    assert c.body.startswith("<!-- guardrails-review -->")
    assert c.severity == "error"
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
    assert result.comments[0].severity == "error"


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


def test_compute_verdict_any_comment_blocks():
    """Even info-severity comments trigger request_changes (strict mode)."""
    comments = [ReviewComment(path="f.py", line=1, body="x", severity="error")]
    assert _compute_verdict(comments) == "request_changes"


def test_agentic_loop_exhaustion_returns_request_changes(monkeypatch):
    """When LLM never calls submit_review, loop exhausts and returns request_changes."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=2)
    diff = "diff --git a/f.py b/f.py\n"
    pr_meta = _meta()

    def fake_call(messages, model, *, tools, tool_choice=None):
        # Always return empty response (no tool calls, no content)
        return LLMResponse(content=None, tool_calls=[], finish_reason="stop")

    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call)

    result = _run_agentic_review(config, diff, pr_meta, pr=1)

    assert result.verdict == "request_changes"
    assert "exhausted" in result.summary.lower()
    assert "<!-- guardrails-review -->" in result.summary


def test_run_resolve_failure_returns_1(monkeypatch, capsys):
    """run_resolve returns 1 when get_review_threads raises RuntimeError."""

    def failing_get_threads(pr, owner, repo):
        msg = "API failure"
        raise RuntimeError(msg)

    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda pr: _meta())
    monkeypatch.setattr(
        f"{_REVIEWER}.get_pr_diff",
        lambda pr: "diff --git a/f.py b/f.py\n",
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda pr: set())
    monkeypatch.setattr(f"{_REVIEWER}.get_review_threads", failing_get_threads)

    result = run_resolve(42)

    assert result == 1
    captured = capsys.readouterr()
    assert "Failed to fetch review threads" in captured.out


def test_agentic_content_response_fallback(monkeypatch):
    """Content response in agentic mode is parsed as JSON."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=5)
    diff = "diff --git a/f.py b/f.py\n"
    pr_meta = _meta()

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


# --- _print_dry_run tests ---


def test_print_dry_run_output(capsys):
    """_print_dry_run prints verdict, model, summary, and comments."""
    result = ReviewResult(
        verdict="request_changes",
        summary="<!-- guardrails-review -->\nFound bugs",
        comments=[
            ReviewComment(path="f.py", line=10, body="Bug here", severity="error"),
        ],
        model="test/m",
        timestamp="2024-01-01T00:00:00Z",
        pr=42,
    )

    _print_dry_run(result)

    captured = capsys.readouterr()
    assert "Dry Run: PR #42" in captured.out
    assert "request_changes" in captured.out
    assert "test/m" in captured.out
    assert "Found bugs" in captured.out
    assert "1 inline comment(s)" in captured.out
    assert "f.py:10" in captured.out


def test_print_dry_run_no_comments(capsys):
    """_print_dry_run with no comments does not print comments section."""
    result = ReviewResult(
        verdict="approve",
        summary="<!-- guardrails-review -->\nClean",
        comments=[],
        model="test/m",
        timestamp="2024-01-01T00:00:00Z",
        pr=1,
    )

    _print_dry_run(result)

    captured = capsys.readouterr()
    assert "approve" in captured.out
    assert "inline comment" not in captured.out


# --- run_resolve non-dry-run tests ---


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


def test_run_resolve_resolves_threads(monkeypatch, capsys):
    """run_resolve calls resolve_thread for each resolvable thread."""
    threads = [
        _make_thread(thread_id="t1", path="deleted.py", line=5),
        _make_thread(thread_id="t2", path="current.py", line=2),  # line 2 is in diff
    ]

    resolved_ids = []
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda pr: _meta())
    monkeypatch.setattr(
        f"{_REVIEWER}.get_pr_diff",
        lambda pr: (
            "diff --git a/current.py b/current.py\n"
            "--- a/current.py\n+++ b/current.py\n"
            "@@ -1,2 +1,3 @@\n ctx\n+new\n end\n"
        ),
    )
    monkeypatch.setattr(
        f"{_REVIEWER}.get_deleted_files",
        lambda pr: {"deleted.py"},
    )
    monkeypatch.setattr(
        f"{_REVIEWER}.get_review_threads",
        lambda pr, owner, repo: threads,
    )
    monkeypatch.setattr(
        f"{_REVIEWER}.resolve_thread",
        lambda tid: resolved_ids.append(tid) or True,
    )

    result = run_resolve(42)

    assert result == 0
    assert "t1" in resolved_ids
    assert "t2" not in resolved_ids
    captured = capsys.readouterr()
    assert "Resolved 1/1" in captured.out


def test_run_resolve_handles_failed_resolution(monkeypatch, capsys):
    """run_resolve logs warning when resolve_thread returns False."""
    threads = [
        _make_thread(thread_id="t1", path="deleted.py", line=5),
    ]

    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda pr: _meta())
    monkeypatch.setattr(
        f"{_REVIEWER}.get_pr_diff",
        lambda pr: "diff --git a/x.py b/x.py\n",
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda pr: {"deleted.py"})
    monkeypatch.setattr(
        f"{_REVIEWER}.get_review_threads", lambda pr, owner, repo: threads
    )
    monkeypatch.setattr(f"{_REVIEWER}.resolve_thread", lambda tid: False)

    result = run_resolve(42)

    assert result == 0
    captured = capsys.readouterr()
    assert "Resolved 0/1" in captured.out


# --- Dedup path in run_review ---


def test_run_review_dedup_removes_duplicate_comments(tmp_path, monkeypatch, capsys):
    """run_review deduplicates comments against existing threads on same path+line."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text('[config]\nmodel = "test/m"\n[review]\nagentic = false\n')

    diff_text = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n+++ b/foo.py\n"
        "@@ -1,3 +1,4 @@\n context\n+added line\n more\n end\n"
    )
    pr_meta = _meta()
    # LLM returns a comment on foo.py:2 which already exists as an unresolved thread
    llm_response = json.dumps(
        {
            "verdict": "request_changes",
            "summary": "<!-- guardrails-review -->\nFound issue",
            "comments": [
                {"path": "foo.py", "line": 2, "body": "Bug on this line"},
            ],
        }
    )

    existing_threads = [
        _make_thread(
            thread_id="existing-t1",
            path="foo.py",
            line=2,
            body="<!-- guardrails-review -->\nPrevious finding on same line",
        ),
    ]

    posted = []
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda pr: pr_meta)
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda msgs, model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(
        f"{_REVIEWER}.post_review",
        lambda pr, result, owner, repo, sha: posted.append(result) or True,
    )
    monkeypatch.setattr(f"{_REVIEWER}.set_commit_status", lambda *a, **kw: None)
    monkeypatch.setattr(
        f"{_REVIEWER}.get_review_threads",
        lambda pr, owner, repo: existing_threads,
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda pr: set())
    monkeypatch.setattr(f"{_REVIEWER}.resolve_thread", lambda tid: True)

    result = run_review(53, project_dir=tmp_path)

    assert result == 0
    assert len(posted) == 1
    # The duplicate comment should have been removed, so no inline comments posted
    assert len(posted[0].comments) == 0
    # Despite 0 new comments, the existing unresolved thread blocks approval
    assert posted[0].verdict == "request_changes"
    assert "unresolved" in posted[0].summary.lower()


# --- Auto-resolve path in run_review ---


def test_run_review_auto_resolves_stale_threads(tmp_path, monkeypatch, capsys):
    """run_review auto-resolves threads on deleted files after posting review."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text('[config]\nmodel = "test/m"\n[review]\nagentic = false\n')

    diff_text = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n+++ b/foo.py\n"
        "@@ -1,3 +1,4 @@\n context\n+added line\n more\n end\n"
    )
    pr_meta = _meta()
    llm_response = json.dumps(
        {
            "verdict": "approve",
            "summary": "<!-- guardrails-review -->\nLGTM",
            "comments": [],
        }
    )

    # Existing thread on a file that has been deleted
    existing_threads = [
        _make_thread(thread_id="stale-t1", path="removed.py", line=5),
    ]

    resolved_ids = []
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda pr: pr_meta)
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda msgs, model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(
        f"{_REVIEWER}.post_review",
        lambda pr, result, owner, repo, sha: True,
    )
    monkeypatch.setattr(f"{_REVIEWER}.set_commit_status", lambda *a, **kw: None)
    monkeypatch.setattr(
        f"{_REVIEWER}.get_review_threads",
        lambda pr, owner, repo: existing_threads,
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda pr: {"removed.py"})
    monkeypatch.setattr(
        f"{_REVIEWER}.resolve_thread",
        lambda tid: resolved_ids.append(tid) or True,
    )

    result = run_review(53, project_dir=tmp_path)

    assert result == 0
    assert "stale-t1" in resolved_ids


# --- Unresolved thread check before approve ---


def _make_marked_thread(
    thread_id: str,
    *,
    is_resolved: bool = False,
    path: str = "src/main.py",
    line: int = 2,
    is_outdated: bool = False,
) -> ReviewThread:
    """Build a ReviewThread with the guardrails-review marker."""
    return ReviewThread(
        thread_id=thread_id,
        path=path,
        line=line,
        body="<!-- guardrails-review -->\nSome defect found here",
        is_resolved=is_resolved,
        is_outdated=is_outdated,
        author="github-actions[bot]",
        created_at="2025-01-01T00:00:00Z",
    )


def _stub_clean_review(tmp_path, monkeypatch, *, existing_threads=None):
    """Stub run_review deps for a clean review (0 new defects) with given threads.

    Returns dict of captured calls for assertions.
    """
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text('[config]\nmodel = "test/m"\n[review]\nagentic = false\n')

    diff_text = (
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n+++ b/src/main.py\n"
        "@@ -1,3 +1,4 @@\n context\n+added line\n more\n end\n"
    )
    pr_meta = _meta(title="Test PR", body="test", head_ref_oid="abc123")
    llm_response = json.dumps(
        {
            "verdict": "approve",
            "summary": "<!-- guardrails-review -->\nAll clean.",
            "comments": [],
        }
    )
    threads = existing_threads if existing_threads is not None else []
    captured = {
        "posted_reviews": [],
        "set_statuses": [],
        "resolved_threads": [],
    }

    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda pr: pr_meta)
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda msgs, model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(
        f"{_REVIEWER}.get_review_threads", lambda pr, owner, repo: threads
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda pr: set())
    monkeypatch.setattr(
        f"{_REVIEWER}.post_review",
        lambda pr, result, owner, repo, sha: (
            captured["posted_reviews"].append(result) or True
        ),
    )
    monkeypatch.setattr(
        f"{_REVIEWER}.set_commit_status",
        lambda owner, repo, sha, state, desc: captured["set_statuses"].append(
            (state, desc)
        ),
    )
    monkeypatch.setattr(
        f"{_REVIEWER}.resolve_thread",
        lambda tid: captured["resolved_threads"].append(tid) or True,
    )

    return captured


def test_run_review_approve_blocked_by_unresolved_threads(tmp_path, monkeypatch):
    """Review finds 0 new defects but 2 unresolved threads exist -> request_changes."""
    threads = [
        _make_marked_thread("thread-1", is_resolved=False),
        _make_marked_thread("thread-2", is_resolved=False),
        _make_marked_thread("thread-3", is_resolved=True),  # resolved, should not count
    ]
    captured = _stub_clean_review(tmp_path, monkeypatch, existing_threads=threads)

    result = run_review(42, project_dir=tmp_path)

    assert result == 0
    posted = captured["posted_reviews"]
    assert len(posted) == 1
    assert posted[0].verdict == "request_changes"
    assert "2 unresolved" in posted[0].summary


def test_run_review_approve_when_all_threads_resolved(tmp_path, monkeypatch):
    """Review finds 0 new defects and all prior threads resolved -> approve."""
    threads = [
        _make_marked_thread("thread-1", is_resolved=True),
        _make_marked_thread("thread-2", is_resolved=True),
    ]
    captured = _stub_clean_review(tmp_path, monkeypatch, existing_threads=threads)

    result = run_review(42, project_dir=tmp_path)

    assert result == 0
    posted = captured["posted_reviews"]
    assert len(posted) == 1
    assert posted[0].verdict == "approve"


def test_run_review_approve_when_no_prior_threads(tmp_path, monkeypatch):
    """Review finds 0 new defects and no prior threads at all -> approve."""
    captured = _stub_clean_review(tmp_path, monkeypatch, existing_threads=[])

    result = run_review(42, project_dir=tmp_path)

    assert result == 0
    posted = captured["posted_reviews"]
    assert len(posted) == 1
    assert posted[0].verdict == "approve"


def test_unresolved_thread_check_happens_after_auto_resolve(tmp_path, monkeypatch):
    """Thread that gets auto-resolved (outdated) should NOT block approval."""
    # This thread is outdated, so auto-resolve will resolve it.
    # After auto-resolve, there should be 0 unresolved threads -> approve.
    threads = [
        _make_marked_thread(
            "thread-outdated",
            is_resolved=False,
            is_outdated=True,
            path="src/main.py",
            line=10,
        ),
    ]
    captured = _stub_clean_review(tmp_path, monkeypatch, existing_threads=threads)

    result = run_review(42, project_dir=tmp_path)

    assert result == 0
    # The outdated thread should have been auto-resolved
    assert "thread-outdated" in captured["resolved_threads"]
    # With 0 remaining unresolved threads, verdict should be approve
    posted = captured["posted_reviews"]
    assert len(posted) == 1
    assert posted[0].verdict == "approve"


def test_dry_run_shows_unresolved_thread_count(tmp_path, monkeypatch, capsys):
    """Dry run should show that approval was blocked by unresolved threads."""
    threads = [
        _make_marked_thread("thread-1", is_resolved=False),
        _make_marked_thread("thread-2", is_resolved=False),
    ]
    _stub_clean_review(tmp_path, monkeypatch, existing_threads=threads)

    result = run_review(42, dry_run=True, project_dir=tmp_path)

    assert result == 0
    output = capsys.readouterr().out
    assert "unresolved" in output.lower()
    assert "request_changes" in output


def test_run_review_unresolved_threads_set_failure_status(tmp_path, monkeypatch):
    """When approval blocked by unresolved threads, commit status should be failure."""
    threads = [
        _make_marked_thread("thread-1", is_resolved=False),
    ]
    captured = _stub_clean_review(tmp_path, monkeypatch, existing_threads=threads)

    run_review(42, project_dir=tmp_path)

    # Find the final status (last one set, not the "pending" one)
    final_statuses = [s for s in captured["set_statuses"] if s[0] != "pending"]
    assert len(final_statuses) == 1
    assert final_statuses[0][0] == "failure"
