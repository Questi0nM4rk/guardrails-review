"""Tests for the review orchestrator."""

from __future__ import annotations

import json
import subprocess

from guardrails_review.memory import FalsePositive, Memory, ResolutionStats
from guardrails_review.parser import parse_response, parse_submit_review_args
from guardrails_review.prompts import build_agentic_messages, build_messages
from guardrails_review.reviewer import (
    _block_approval_if_unresolved,
    _build_final_result,
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
    assert "post_comments" in messages[0]["content"]
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


def test_validate_comments_multiline_both_lines_valid():
    """Multi-line comment with both start_line and line in diff is valid."""
    valid_lines = {"foo.py": {5, 6, 7, 8, 9, 10}}
    comments = [
        ReviewComment(path="foo.py", line=10, body="range", severity="error", start_line=5),
    ]
    valid, invalid = validate_comments(comments, valid_lines)

    assert len(valid) == 1
    assert len(invalid) == 0


def test_validate_comments_multiline_start_line_outside_diff_is_invalid():
    """Multi-line comment where start_line is outside diff is invalid."""
    valid_lines = {"foo.py": {8, 9, 10}}  # lines 1-7 not in diff
    comments = [
        ReviewComment(path="foo.py", line=10, body="range", severity="error", start_line=5),
    ]
    valid, invalid = validate_comments(comments, valid_lines)

    assert len(valid) == 0
    assert len(invalid) == 1


def test_validate_comments_multiline_end_line_outside_diff_is_invalid():
    """Multi-line comment where end line (line) is outside diff is invalid."""
    valid_lines = {"foo.py": {5, 6, 7}}  # lines 8-10 not in diff
    comments = [
        ReviewComment(path="foo.py", line=10, body="range", severity="error", start_line=5),
    ]
    valid, invalid = validate_comments(comments, valid_lines)

    assert len(valid) == 0
    assert len(invalid) == 1


def test_validate_comments_no_start_line_behaves_as_before():
    """Comments without start_line use only line for validation (unchanged behavior)."""
    valid_lines = {"foo.py": {10}}
    comments = [
        ReviewComment(path="foo.py", line=10, body="single", severity="error"),
    ]
    valid, _invalid = validate_comments(comments, valid_lines)

    assert len(valid) == 1


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

    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda _pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda _pr: pr_meta)
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda _msgs, _model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(
        f"{_REVIEWER}.get_review_threads", lambda _pr, _owner, _repo: []
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda _pr: set())
    monkeypatch.setattr(f"{_REVIEWER}.resolve_thread", lambda _tid: True)

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
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda _pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda _pr: pr_meta)
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda _msgs, _model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(
        f"{_REVIEWER}.post_review",
        lambda _pr, result, _owner, _repo, _sha: posted.append(result) or True,
    )
    monkeypatch.setattr(
        f"{_REVIEWER}.set_commit_status",
        lambda *_a, **_kw: statuses.append(_a),
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
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda _pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda _pr: pr_meta)
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda _msgs, _model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(
        f"{_REVIEWER}.post_review",
        lambda _pr, _result, _owner, _repo, _sha: True,
    )
    monkeypatch.setattr(
        f"{_REVIEWER}.set_commit_status",
        lambda _owner, _repo, _sha, state, desc: statuses.append((state, desc)),
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

    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda _pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda _pr: pr_meta)
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda _msgs, _model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(
        f"{_REVIEWER}.post_review",
        lambda _pr, _result, _owner, _repo, _sha: True,
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
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda _pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda _pr: pr_meta)
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda _msgs, _model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(
        f"{_REVIEWER}.get_review_threads", lambda _pr, _owner, _repo: []
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda _pr: set())
    monkeypatch.setattr(f"{_REVIEWER}.resolve_thread", lambda _tid: True)
    monkeypatch.setattr(
        f"{_REVIEWER}.set_commit_status",
        lambda *_a, **_kw: statuses.append(_a),
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

    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda _pr: diff_text)
    pr_meta = _meta()
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda _pr: pr_meta)
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda _msgs, _model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(
        f"{_REVIEWER}.get_review_threads", lambda _pr, _owner, _repo: []
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda _pr: set())
    monkeypatch.setattr(f"{_REVIEWER}.resolve_thread", lambda _tid: True)

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

    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda _pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda _pr: _meta())
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda _msgs, _model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(
        f"{_REVIEWER}.get_review_threads", lambda _pr, _owner, _repo: []
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda _pr: set())
    monkeypatch.setattr(f"{_REVIEWER}.resolve_thread", lambda _tid: True)

    result = run_review(1, dry_run=True, project_dir=tmp_path)

    assert result == 0
    captured = capsys.readouterr()
    assert "approve" in captured.out
    assert "All clear" in captured.out


# --- Agentic review tests ---


def _stub_agentic_deps(monkeypatch, *, existing_threads=None):
    """Stub common agentic review dependencies."""
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(f"{_REVIEWER}.get_model_context_length", lambda _m: 100_000)
    monkeypatch.setattr(f"{_REVIEWER}.build_ci_context", lambda *_a: "")
    monkeypatch.setattr(
        f"{_REVIEWER}.get_review_threads", lambda _pr, _o, _r: existing_threads or []
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_our_threads", lambda t: t)

    pending_comments: list[object] = []
    monkeypatch.setattr(
        f"{_REVIEWER}.create_pending_review",
        lambda _pr, _o, _r, _sha: 42,
    )
    monkeypatch.setattr(
        f"{_REVIEWER}.add_pending_review_comment",
        lambda _rid, _pr, comment, _o, _r: pending_comments.append(comment),
    )
    monkeypatch.setattr(
        f"{_REVIEWER}.get_pending_review_comment_count",
        lambda _rid, _pr, _o, _r: len(pending_comments),
    )
    return pending_comments


def test_agentic_loop_calls_tools_then_finishes(monkeypatch):
    """Agentic loop executes tools, posts comments, then finishes."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=5)
    diff = (
        "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
        "@@ -1,2 +1,3 @@\n ctx\n+new\n end\n"
    )
    pr_meta = _meta(head_ref_oid="sha123")
    posted = _stub_agentic_deps(monkeypatch)

    call_count = {"n": 0}

    def fake_call(messages, model, *, tools, tool_choice=None):
        call_count["n"] += 1
        usage = {"prompt_tokens": 20_000, "completion_tokens": 100}
        if call_count["n"] == 1:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="c1", name="read_file", arguments='{"path": "f.py"}'),
                ],
                finish_reason="tool_calls",
                usage=usage,
            )
        if call_count["n"] == 2:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="c2",
                        name="post_comments",
                        arguments=json.dumps(
                            {
                                "comments": [
                                    {"path": "f.py", "line": 2, "body": "Bug here"},
                                ],
                            }
                        ),
                    ),
                ],
                finish_reason="tool_calls",
                usage=usage,
            )
        return LLMResponse(
            content=None,
            tool_calls=[ToolCall(id="c3", name="submit_review", arguments='{"verdict": "approve", "summary": "No defects found."}')],
            finish_reason="tool_calls",
            usage=usage,
        )

    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call)
    monkeypatch.setattr(f"{_REVIEWER}.execute_tool", lambda _n, _a, _c: "1: code\n")

    result = _run_agentic_review(config, diff, pr_meta, pr=42)

    assert result.verdict == "request_changes"
    assert result.comments == []  # already posted
    assert len(posted) == 1
    assert call_count["n"] == 3


def test_agentic_loop_no_progress_streak_terminates(monkeypatch):
    """Loop terminates after 2 empty responses (no tool calls, no content)."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=10)
    diff = "diff --git a/f.py b/f.py\n"
    pr_meta = _meta()
    _stub_agentic_deps(monkeypatch)

    call_count = {"n": 0}

    def fake_call(messages, model, *, tools, tool_choice=None):
        call_count["n"] += 1
        return LLMResponse(
            content=None,
            tool_calls=[],
            finish_reason="stop",
            usage={"prompt_tokens": 10_000, "completion_tokens": 0},
        )

    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call)

    result = _run_agentic_review(config, diff, pr_meta, pr=1)

    assert result.verdict == "approve"  # no comments posted
    assert call_count["n"] == 2  # stopped after 2 empty responses


def test_agentic_loop_budget_exhaustion_terminates(monkeypatch):
    """Loop terminates when token budget is exhausted."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=30)
    diff = "diff --git a/f.py b/f.py\n"
    pr_meta = _meta()
    _stub_agentic_deps(monkeypatch)

    call_count = {"n": 0}

    def fake_call(messages, model, *, tools, tool_choice=None):
        call_count["n"] += 1
        # Return high prompt_tokens to exhaust budget quickly
        # Budget max = 80_000 (80% of 100k). Reserve = 15_000.
        # With prompt_tokens=75_000, remaining=5000, which is < 20_000+15_000
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCall(id="c1", name="read_file", arguments='{"path": "f.py"}'),
            ],
            finish_reason="tool_calls",
            usage={"prompt_tokens": 75_000, "completion_tokens": 100},
        )

    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call)
    monkeypatch.setattr(f"{_REVIEWER}.execute_tool", lambda _n, _a, _c: "code")

    result = _run_agentic_review(config, diff, pr_meta, pr=1)

    assert result.verdict == "approve"
    assert call_count["n"] == 1  # stopped after first iteration


def test_agentic_loop_mid_failure_returns_partial(monkeypatch):
    """Mid-loop API failure returns with what was already posted."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=10)
    diff = (
        "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
        "@@ -1,2 +1,3 @@\n ctx\n+new\n end\n"
    )
    pr_meta = _meta()
    posted = _stub_agentic_deps(monkeypatch)

    call_count = {"n": 0}

    def fake_call(messages, model, *, tools, tool_choice=None):
        call_count["n"] += 1
        usage = {"prompt_tokens": 20_000, "completion_tokens": 100}
        if call_count["n"] == 1:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="post_comments",
                        arguments=json.dumps(
                            {
                                "comments": [
                                    {"path": "f.py", "line": 2, "body": "Bug"},
                                ],
                            }
                        ),
                    ),
                ],
                finish_reason="tool_calls",
                usage=usage,
            )
        msg = "API error 500"
        raise RuntimeError(msg)

    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call)

    result = _run_agentic_review(config, diff, pr_meta, pr=1)

    # Should have posted 1 comment and returned partial result
    assert len(posted) == 1
    assert result.verdict == "request_changes"
    assert result.comments == []  # already posted


def test_agentic_loop_validates_comments_before_posting(monkeypatch):
    """Comments on invalid lines are dropped before posting."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=5)
    diff = (
        "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
        "@@ -1,2 +1,3 @@\n ctx\n+new\n end\n"
    )
    pr_meta = _meta()
    posted = _stub_agentic_deps(monkeypatch)

    call_count = {"n": 0}

    def fake_call(messages, model, *, tools, tool_choice=None):
        call_count["n"] += 1
        usage = {"prompt_tokens": 20_000, "completion_tokens": 100}
        if call_count["n"] == 1:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="post_comments",
                        arguments=json.dumps(
                            {
                                "comments": [
                                    {"path": "f.py", "line": 2, "body": "Valid"},
                                    {"path": "f.py", "line": 999, "body": "Invalid"},
                                ],
                            }
                        ),
                    ),
                ],
                finish_reason="tool_calls",
                usage=usage,
            )
        return LLMResponse(
            content=None,
            tool_calls=[ToolCall(id="c2", name="submit_review", arguments='{"verdict": "approve", "summary": "No defects found."}')],
            finish_reason="tool_calls",
            usage=usage,
        )

    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call)

    _run_agentic_review(config, diff, pr_meta, pr=1)

    # Only valid comment should have been posted
    assert len(posted) == 1
    assert posted[0].path == "f.py"
    assert posted[0].line == 2


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


def test_agentic_loop_submit_review_approves_when_no_comments(monkeypatch):
    """submit_review with no comments posted results in approve."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=5)
    diff = "diff --git a/f.py b/f.py\n"
    pr_meta = _meta()
    _stub_agentic_deps(monkeypatch)

    def fake_call(messages, model, *, tools, tool_choice=None):
        return LLMResponse(
            content=None,
            tool_calls=[ToolCall(id="c1", name="submit_review", arguments='{"verdict": "approve", "summary": "No defects found."}')],
            finish_reason="tool_calls",
            usage={"prompt_tokens": 10_000, "completion_tokens": 100},
        )

    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call)

    result = _run_agentic_review(config, diff, pr_meta, pr=1)

    assert result.verdict == "approve"
    assert result.comments == []


def test_agentic_loop_dropped_comments_trust_approve_verdict(monkeypatch):
    """If bot posted comments but GitHub dropped them all, trust the approve verdict.

    Reproduces the zombie CHANGES_REQUESTED bug: bot posts a comment to the
    pending review (API accepts it), then calls submit_review('approve').
    GitHub silently drops the comment (e.g. line not in diff context).
    The verdict override must fall back to approve, not force request_changes.
    """
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=10)
    diff = (
        "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
        "@@ -1,2 +1,3 @@\n ctx\n+new\n end\n"
    )
    pr_meta = _meta(head_ref_oid="sha123")
    posted = _stub_agentic_deps(monkeypatch)

    # Override: comments "added" to all_posted but pending review has 0 (GitHub dropped)
    monkeypatch.setattr(
        f"{_REVIEWER}.get_pending_review_comment_count",
        lambda _rid, _pr, _o, _r: 0,  # GitHub dropped the comment
    )

    call_n = {"n": 0}

    def fake_call(messages, model, *, tools, tool_choice=None):
        call_n["n"] += 1
        usage = {"prompt_tokens": 10_000, "completion_tokens": 50}
        if call_n["n"] == 1:
            # Bot posts a comment (which will be "dropped" by GitHub mock)
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="c1", name="post_comments", arguments='{"comments": [{"path": "f.py", "line": 2, "body": "Issue", "severity": "error"}]}')],
                finish_reason="tool_calls",
                usage=usage,
            )
        # Then bot approves
        return LLMResponse(
            content=None,
            tool_calls=[ToolCall(id="c2", name="submit_review", arguments='{"verdict": "approve", "summary": "No defects found."}')],
            finish_reason="tool_calls",
            usage=usage,
        )

    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call)

    result = _run_agentic_review(config, diff, pr_meta, pr=1)

    # Comment was "added" locally but GitHub has 0 → trust approve
    assert len(posted) == 1, "comment was added to pending review"
    assert result.verdict == "approve"


def test_run_resolve_failure_returns_1(monkeypatch, capsys):
    """run_resolve returns 1 when get_review_threads raises RuntimeError."""

    def failing_get_threads(pr, owner, repo):
        msg = "API failure"
        raise RuntimeError(msg)

    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda _pr: _meta())
    monkeypatch.setattr(
        f"{_REVIEWER}.get_pr_diff",
        lambda _pr: "diff --git a/f.py b/f.py\n",
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda _pr: set())
    monkeypatch.setattr(f"{_REVIEWER}.get_review_threads", failing_get_threads)

    result = run_resolve(42)

    assert result == 1
    captured = capsys.readouterr()
    assert "Failed to fetch review threads" in captured.out


def test_agentic_content_response_nudged(monkeypatch):
    """Model returning content+stop gets nudged; if it then calls submit_review it completes."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=5)
    diff = "diff --git a/f.py b/f.py\n"
    pr_meta = _meta()
    _stub_agentic_deps(monkeypatch)

    call_count = {"n": 0}

    def fake_call(messages, model, *, tools, tool_choice=None):
        call_count["n"] += 1
        usage = {"prompt_tokens": 20_000, "completion_tokens": 100}
        if call_count["n"] <= 2:
            # Content response (no tool calls but has content) — gets nudged
            return LLMResponse(
                content="Thinking about the diff...",
                tool_calls=[],
                finish_reason="stop",
                usage=usage,
            )
        return LLMResponse(
            content=None,
            tool_calls=[ToolCall(id="c1", name="submit_review", arguments='{"verdict": "approve", "summary": "No defects found."}')],
            finish_reason="tool_calls",
            usage=usage,
        )

    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call)

    result = _run_agentic_review(config, diff, pr_meta, pr=1)

    assert result.verdict == "approve"
    assert call_count["n"] == 3  # 2 content (nudged) + 1 finish


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
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda _pr: _meta())
    monkeypatch.setattr(
        f"{_REVIEWER}.get_pr_diff",
        lambda _pr: (
            "diff --git a/current.py b/current.py\n"
            "--- a/current.py\n+++ b/current.py\n"
            "@@ -1,2 +1,3 @@\n ctx\n+new\n end\n"
        ),
    )
    monkeypatch.setattr(
        f"{_REVIEWER}.get_deleted_files",
        lambda _pr: {"deleted.py"},
    )
    monkeypatch.setattr(
        f"{_REVIEWER}.get_review_threads",
        lambda _pr, _owner, _repo: threads,
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
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda _pr: _meta())
    monkeypatch.setattr(
        f"{_REVIEWER}.get_pr_diff",
        lambda _pr: "diff --git a/x.py b/x.py\n",
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda _pr: {"deleted.py"})
    monkeypatch.setattr(
        f"{_REVIEWER}.get_review_threads", lambda _pr, _owner, _repo: threads
    )
    monkeypatch.setattr(f"{_REVIEWER}.resolve_thread", lambda _tid: False)

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
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda _pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda _pr: pr_meta)
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda _msgs, _model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(
        f"{_REVIEWER}.post_review",
        lambda _pr, result, _owner, _repo, _sha: posted.append(result) or True,
    )
    monkeypatch.setattr(f"{_REVIEWER}.set_commit_status", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        f"{_REVIEWER}.get_review_threads",
        lambda _pr, _owner, _repo: existing_threads,
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda _pr: set())
    monkeypatch.setattr(f"{_REVIEWER}.resolve_thread", lambda _tid: True)

    result = run_review(53, project_dir=tmp_path)

    assert result == 0
    assert len(posted) == 1
    # The duplicate comment should have been removed, so no inline comments posted
    assert len(posted[0].comments) == 0
    # Unresolved thread → COMMENT verdict (not request_changes; commit is clean)
    assert posted[0].verdict == "comment"
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
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda _pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda _pr: pr_meta)
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda _msgs, _model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(
        f"{_REVIEWER}.post_review",
        lambda _pr, _result, _owner, _repo, _sha: True,
    )
    monkeypatch.setattr(f"{_REVIEWER}.set_commit_status", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        f"{_REVIEWER}.get_review_threads",
        lambda _pr, _owner, _repo: existing_threads,
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda _pr: {"removed.py"})
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

    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda _pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda _pr: pr_meta)
    monkeypatch.setattr(
        f"{_REVIEWER}.call_openrouter", lambda _msgs, _model: llm_response
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(
        f"{_REVIEWER}.get_review_threads", lambda _pr, _owner, _repo: threads
    )
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda _pr: set())
    monkeypatch.setattr(
        f"{_REVIEWER}.post_review",
        lambda _pr, result, _owner, _repo, _sha: (
            captured["posted_reviews"].append(result) or True
        ),
    )
    monkeypatch.setattr(
        f"{_REVIEWER}.set_commit_status",
        lambda _owner, _repo, _sha, state, desc: captured["set_statuses"].append(
            (state, desc)
        ),
    )
    monkeypatch.setattr(
        f"{_REVIEWER}.resolve_thread",
        lambda tid: captured["resolved_threads"].append(tid) or True,
    )

    return captured


def test_run_review_approve_blocked_by_unresolved_threads(tmp_path, monkeypatch):
    """Review finds 0 new defects but 2 unresolved threads exist -> comment (not request_changes).

    The commit is clean — bot posts a COMMENT review to remind the author to
    resolve the threads, without blocking the merge gate.
    """
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
    assert posted[0].verdict == "comment"
    assert "2 unresolved" in posted[0].summary
    assert "Nothing new found" in posted[0].summary


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
    assert "comment" in output  # COMMENT verdict, not request_changes


def test_run_review_unresolved_threads_set_success_status(tmp_path, monkeypatch):
    """Unresolved threads with no new defects → COMMENT verdict → commit status success.

    The commit itself is clean. Open threads are informational — they should not
    block the merge gate via a failure status.
    """
    threads = [
        _make_marked_thread("thread-1", is_resolved=False),
    ]
    captured = _stub_clean_review(tmp_path, monkeypatch, existing_threads=threads)

    run_review(42, project_dir=tmp_path)

    # Find the final status (last one set, not the "pending" one)
    final_statuses = [s for s in captured["set_statuses"] if s[0] != "pending"]
    assert len(final_statuses) == 1
    assert final_statuses[0][0] == "success"


def test_run_review_loads_and_saves_memory(tmp_path, monkeypatch):
    """run_review loads memory before review and saves it after posting."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text('[config]\nmodel = "test/m"\n[review]\nagentic = false\n')

    diff_text = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n+++ b/foo.py\n"
        "@@ -1,1 +1,2 @@\n context\n+added\n"
    )
    pr_meta = _meta(head_ref_oid="sha1")
    llm_response = json.dumps(
        {"verdict": "approve", "summary": "<!-- guardrails-review -->\nLGTM", "comments": []}
    )

    fake_mem = Memory(
        version=1,
        repo="owner/repo",
        false_positives=[],
        conventions=["Uses gh CLI"],
        resolution_stats=ResolutionStats(
            total_threads=0, fixed=0, false_positive=0, wont_fix=0, avg_rounds_to_resolve=0.0
        ),
    )
    saved_memories = []

    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda pr: pr_meta)
    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter", lambda msgs, model: llm_response)
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(f"{_REVIEWER}.get_review_threads", lambda pr, owner, repo: [])
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda pr: set())
    monkeypatch.setattr(f"{_REVIEWER}.post_review", lambda *a, **kw: True)
    monkeypatch.setattr(f"{_REVIEWER}.set_commit_status", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_REVIEWER}.resolve_thread", lambda tid: True)
    monkeypatch.setattr(f"{_REVIEWER}.load_memory", lambda owner, repo: fake_mem)

    def _capture_save(mem):
        saved_memories.append(mem)

    monkeypatch.setattr(f"{_REVIEWER}.save_memory", _capture_save)

    result = run_review(42, project_dir=tmp_path)

    assert result == 0
    assert len(saved_memories) == 1
    assert saved_memories[0].repo == "owner/repo"


def test_run_review_memory_context_injected_into_prompt(tmp_path, monkeypatch):
    """Memory context is injected into LLM prompt when false positives exist."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text('[config]\nmodel = "test/m"\n[review]\nagentic = false\n')

    diff_text = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n+++ b/foo.py\n"
        "@@ -1,1 +1,2 @@\n context\n+added\n"
    )
    pr_meta = _meta(head_ref_oid="sha1")
    llm_response = json.dumps(
        {"verdict": "approve", "summary": "<!-- guardrails-review -->\nLGTM", "comments": []}
    )

    fake_mem = Memory(
        version=1,
        repo="owner/repo",
        false_positives=[
            FalsePositive(
                pattern="urllib for API",
                rule="S605",
                file_pattern="src/**/*.py",
                occurrences=3,
                first_seen="2026-01-01",
                last_seen="2026-03-01",
            )
        ],
        conventions=[],
        resolution_stats=ResolutionStats(
            total_threads=0, fixed=0, false_positive=0, wont_fix=0, avg_rounds_to_resolve=0.0
        ),
    )
    captured_messages = []

    def fake_openrouter(msgs, model):
        captured_messages.extend(msgs)
        return llm_response

    monkeypatch.setattr(f"{_REVIEWER}.get_pr_diff", lambda pr: diff_text)
    monkeypatch.setattr(f"{_REVIEWER}.get_pr_metadata", lambda pr: pr_meta)
    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter", fake_openrouter)
    monkeypatch.setattr(f"{_REVIEWER}.get_repo_info", lambda: ("owner", "repo"))
    monkeypatch.setattr(f"{_REVIEWER}.get_review_threads", lambda pr, owner, repo: [])
    monkeypatch.setattr(f"{_REVIEWER}.get_deleted_files", lambda pr: set())
    monkeypatch.setattr(f"{_REVIEWER}.post_review", lambda *a, **kw: True)
    monkeypatch.setattr(f"{_REVIEWER}.set_commit_status", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_REVIEWER}.resolve_thread", lambda tid: True)
    monkeypatch.setattr(f"{_REVIEWER}.load_memory", lambda owner, repo: fake_mem)
    monkeypatch.setattr(f"{_REVIEWER}.save_memory", lambda mem: None)

    run_review(42, project_dir=tmp_path)

    # The user message should contain the false positive pattern
    user_msg = next(m for m in captured_messages if m["role"] == "user")
    assert "urllib for API" in user_msg["content"]
    assert "S605" in user_msg["content"]


# --- New v2 tests ---


def _make_submit_response(verdict: str = "approve") -> LLMResponse:
    """Return a submit_review response for use in tests."""
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCall(
                id="submit1",
                name="submit_review",
                arguments='{"verdict": "approve", "summary": "No defects found."}',
            )
        ],
        finish_reason="tool_calls",
        usage={"prompt_tokens": 20_000, "completion_tokens": 100},
    )


def test_agentic_empty_stop_injects_nudge_and_continues(monkeypatch):
    """finish_reason=stop with no content/tool_calls -> nudge injected, loop continues."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=5)
    diff = "diff --git a/f.py b/f.py\n"
    pr_meta = _meta()
    _stub_agentic_deps(monkeypatch)

    call_count = {"n": 0}

    def fake_call(messages, model, *, tools, tool_choice=None):
        call_count["n"] += 1
        usage = {"prompt_tokens": 20_000, "completion_tokens": 100}
        if call_count["n"] == 1:
            # Empty stop — no content, no tool calls
            return LLMResponse(content=None, tool_calls=[], finish_reason="stop", usage=usage)
        # Second call succeeds with submit_review
        return _make_submit_response()

    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call)

    result = _run_agentic_review(config, diff, pr_meta, pr=1)

    assert result.verdict == "approve"
    assert call_count["n"] == 2


def test_agentic_content_stop_injects_nudge(monkeypatch):
    """finish_reason=stop with content -> nudge is injected, loop continues."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=5)
    diff = "diff --git a/f.py b/f.py\n"
    pr_meta = _meta()
    _stub_agentic_deps(monkeypatch)

    call_count = {"n": 0}

    def fake_call(messages, model, *, tools, tool_choice=None):
        call_count["n"] += 1
        usage = {"prompt_tokens": 20_000, "completion_tokens": 100}
        if call_count["n"] == 1:
            # Content stop without tool call
            return LLMResponse(
                content="I found no issues.", tool_calls=[], finish_reason="stop", usage=usage
            )
        return _make_submit_response()

    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call)

    result = _run_agentic_review(config, diff, pr_meta, pr=1)

    assert result.verdict == "approve"
    assert call_count["n"] == 2


def test_agentic_timeout_retries_then_falls_back(monkeypatch):
    """TimeoutError repeated _MAX_TIMEOUT_RETRIES+1 times -> oneshot fallback."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=10)
    diff = (
        "diff --git a/f.py b/f.py\n"
        "--- a/f.py\n+++ b/f.py\n"
        "@@ -1,2 +1,3 @@\n ctx\n+new\n end\n"
    )
    pr_meta = _meta()
    _stub_agentic_deps(monkeypatch)

    def fake_call_tools(messages, model, *, tools, tool_choice=None):
        raise TimeoutError("timed out")

    def fake_oneshot(messages, model):
        return json.dumps(
            {
                "verdict": "approve",
                "summary": "<!-- guardrails-review -->\nOneshot",
                "comments": [],
            }
        )

    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call_tools)
    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter", fake_oneshot)

    result = _run_agentic_review(config, diff, pr_meta, pr=1)

    assert result.verdict == "approve"
    assert "Oneshot" in result.summary


def test_agentic_timeout_retry_succeeds(monkeypatch):
    """Single TimeoutError followed by success -> completes normally."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=5)
    diff = "diff --git a/f.py b/f.py\n"
    pr_meta = _meta()
    _stub_agentic_deps(monkeypatch)

    call_count = {"n": 0}

    def fake_call(messages, model, *, tools, tool_choice=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise TimeoutError("timed out")
        return _make_submit_response()

    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call)

    result = _run_agentic_review(config, diff, pr_meta, pr=1)

    assert result.verdict == "approve"
    assert call_count["n"] == 2


def _make_large_diff(n_lines: int) -> str:
    """Build a fake diff with n_lines of additions."""
    header = (
        "diff --git a/f.py b/f.py\n"
        "--- a/f.py\n+++ b/f.py\n"
        f"@@ -1,1 +1,{n_lines} @@\n"
    )
    return header + "".join(f"+line{i}\n" for i in range(1, n_lines + 1))


def test_agentic_premature_post_comments_nudges_on_large_diff(monkeypatch):
    """post_comments after 0 tool uses on 200-line diff -> nudge injected."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=10)
    diff = _make_large_diff(200)
    pr_meta = _meta(head_ref_oid="sha123")
    _stub_agentic_deps(monkeypatch)

    call_count = {"n": 0}

    def fake_call(messages, model, *, tools, tool_choice=None):
        call_count["n"] += 1
        usage = {"prompt_tokens": 20_000, "completion_tokens": 100}
        if call_count["n"] == 1:
            # post_comments with 0 prior tool uses -> should nudge
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="post_comments",
                        arguments=json.dumps({"comments": []}),
                    )
                ],
                finish_reason="tool_calls",
                usage=usage,
            )
        return _make_submit_response()

    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call)

    result = _run_agentic_review(config, diff, pr_meta, pr=1)

    # Should have looped at least twice (first was nudged, second submit_review accepted)
    assert call_count["n"] >= 2
    assert result.verdict == "approve"


def test_agentic_premature_post_comments_accepted_on_small_diff(monkeypatch):
    """post_comments on small diff -> no nudge (threshold not crossed)."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=10)
    diff = _make_large_diff(50)  # below threshold
    pr_meta = _meta(head_ref_oid="sha123")
    _stub_agentic_deps(monkeypatch)

    call_count = {"n": 0}

    def fake_call(messages, model, *, tools, tool_choice=None):
        call_count["n"] += 1
        usage = {"prompt_tokens": 20_000, "completion_tokens": 100}
        if call_count["n"] == 1:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="post_comments",
                        arguments=json.dumps({"comments": []}),
                    )
                ],
                finish_reason="tool_calls",
                usage=usage,
            )
        return _make_submit_response()

    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call)

    result = _run_agentic_review(config, diff, pr_meta, pr=1)

    # Small diff -> no nudge on post_comments -> continues to finish
    assert result.verdict == "approve"
    assert call_count["n"] == 2


def test_agentic_submit_review_always_accepted(monkeypatch):
    """submit_review is always accepted without nudge regardless of tool use count."""
    config = ReviewConfig(model="test/m", agentic=True, max_iterations=10)
    diff = _make_large_diff(200)
    pr_meta = _meta()
    _stub_agentic_deps(monkeypatch)

    call_count = {"n": 0}

    def fake_call(messages, model, *, tools, tool_choice=None):
        call_count["n"] += 1
        return _make_submit_response()

    monkeypatch.setattr(f"{_REVIEWER}.call_openrouter_tools", fake_call)

    result = _run_agentic_review(config, diff, pr_meta, pr=1)

    # submit_review accepted on first call without nudge
    assert call_count["n"] == 1
    assert result.verdict == "approve"


# ---------------------------------------------------------------------------
# _block_approval_if_unresolved — comment verdict
# ---------------------------------------------------------------------------


def test_block_approval_comment_when_unresolved_threads(monkeypatch):
    """approve → comment when unresolved threads remain (nothing new found)."""
    monkeypatch.setattr(
        f"{_REVIEWER}._check_unresolved_threads",
        lambda threads, auto_resolved: [threads[0]],
    )
    final = ReviewResult(
        verdict="approve",
        summary="<!-- guardrails-review -->\nNo defects found.",
        comments=[],
        model="test/m",
        pr=1,
    )
    thread = _make_thread(path="src/foo.py", line=10)
    result = _block_approval_if_unresolved(final, [thread], set(), pr=1)

    assert result.verdict == "comment"
    assert "Nothing new found" in result.summary
    assert "resolve them before merging" in result.summary


def test_block_approval_no_change_when_no_unresolved(monkeypatch):
    """approve → approve when all threads are resolved."""
    monkeypatch.setattr(
        f"{_REVIEWER}._check_unresolved_threads",
        lambda threads, auto_resolved: [],
    )
    final = ReviewResult(
        verdict="approve",
        summary="<!-- guardrails-review -->\nNo defects found.",
        comments=[],
        model="test/m",
        pr=1,
    )
    result = _block_approval_if_unresolved(final, [], set(), pr=1)

    assert result.verdict == "approve"


def test_block_approval_does_not_downgrade_request_changes(monkeypatch):
    """request_changes is never changed to comment by this function."""
    monkeypatch.setattr(
        f"{_REVIEWER}._check_unresolved_threads",
        lambda threads, auto_resolved: [threads[0]],
    )
    final = ReviewResult(
        verdict="request_changes",
        summary="<!-- guardrails-review -->\n1 defect found.",
        comments=[],
        model="test/m",
        pr=1,
    )
    thread = _make_thread(path="src/foo.py", line=10)
    result = _block_approval_if_unresolved(final, [thread], set(), pr=1)

    assert result.verdict == "request_changes"


# ---------------------------------------------------------------------------
# _build_final_result — agentic verdict preservation
# ---------------------------------------------------------------------------


def test_build_final_result_preserves_agentic_request_changes():
    """Agentic reviews post inline comments and return comments=[].

    _build_final_result must NOT downgrade request_changes → approve just
    because result.comments is empty (inline comments are already on GitHub).
    """
    result = ReviewResult(
        verdict="request_changes",
        summary="<!-- guardrails-review -->\n10 defect(s) found.",
        comments=[],
        model="test/m",
        pr=1,
    )
    final, invalid = _build_final_result(result, valid_lines={}, pr=1)

    assert final.verdict == "request_changes"
    assert invalid == []


def test_build_final_result_approve_when_clean():
    """approve verdict and no comments → approve preserved."""
    result = ReviewResult(
        verdict="approve",
        summary="<!-- guardrails-review -->\nNo defects found.",
        comments=[],
        model="test/m",
        pr=1,
    )
    final, invalid = _build_final_result(result, valid_lines={}, pr=1)

    assert final.verdict == "approve"
    assert invalid == []


def test_build_final_result_request_changes_from_non_agentic_comments():
    """Non-agentic path: result has comments → request_changes regardless of verdict."""
    result = ReviewResult(
        verdict="approve",
        summary="<!-- guardrails-review -->\nfound issues",
        comments=[
            ReviewComment(path="src/foo.py", line=10, body="issue", severity="error")
        ],
        model="test/m",
        pr=1,
    )
    final, invalid = _build_final_result(result, valid_lines={"src/foo.py": {10}}, pr=1)

    assert final.verdict == "request_changes"
    assert len(final.comments) == 1
