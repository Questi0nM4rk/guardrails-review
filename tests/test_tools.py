"""Tests for guardrails_review.tools module."""

from __future__ import annotations

import base64
import json
import subprocess

import pytest

from guardrails_review.tools import (
    TOOL_DEFINITIONS,
    ToolContext,
    execute_tool,
)


@pytest.fixture()
def ctx():
    """Standard tool context for tests."""
    return ToolContext(pr=42, owner="acme", repo="widgets", commit_sha="abc123")


def _gh_mock(stdout: str, returncode: int = 0):
    """Create a subprocess.CompletedProcess mock for run_gh."""
    return subprocess.CompletedProcess(["gh"], returncode, stdout, "")


# --- read_file ---


def test_read_file_full(monkeypatch, ctx):
    """read_file returns numbered file contents."""
    content = base64.b64encode(b"line1\nline2\nline3\n").decode()

    def fake_run_gh(*args, **kwargs):
        return _gh_mock(content + "\n")

    monkeypatch.setattr("guardrails_review.tools.run_gh", fake_run_gh)

    result = execute_tool("read_file", json.dumps({"path": "src/main.py"}), ctx)

    assert "1: line1" in result
    assert "2: line2" in result
    assert "3: line3" in result


def test_read_file_slice(monkeypatch, ctx):
    """read_file with start_line/end_line returns only requested lines."""
    content = base64.b64encode(b"a\nb\nc\nd\ne\n").decode()

    def fake_run_gh(*args, **kwargs):
        return _gh_mock(content + "\n")

    monkeypatch.setattr("guardrails_review.tools.run_gh", fake_run_gh)

    result = execute_tool(
        "read_file",
        json.dumps({"path": "f.py", "start_line": 2, "end_line": 4}),
        ctx,
    )

    assert "2: b" in result
    assert "3: c" in result
    assert "4: d" in result
    assert "1: a" not in result
    assert "5: e" not in result


def test_read_file_rejects_absolute_path(ctx):
    """read_file rejects absolute paths as traversal attempt."""
    result = execute_tool("read_file", json.dumps({"path": "/etc/passwd"}), ctx)

    assert "Invalid path" in result


def test_read_file_rejects_dot_dot_traversal(ctx):
    """read_file rejects paths containing '..' components."""
    result = execute_tool(
        "read_file", json.dumps({"path": "src/../../etc/passwd"}), ctx
    )

    assert "Invalid path" in result


def test_read_file_end_line_only(monkeypatch, ctx):
    """read_file with only end_line starts numbering from line 1."""
    content = base64.b64encode(b"a\nb\nc\nd\ne\n").decode()

    def fake_run_gh(*args, **kwargs):
        return _gh_mock(content + "\n")

    monkeypatch.setattr("guardrails_review.tools.run_gh", fake_run_gh)

    result = execute_tool(
        "read_file",
        json.dumps({"path": "f.py", "end_line": 3}),
        ctx,
    )

    assert "1: a" in result
    assert "2: b" in result
    assert "3: c" in result
    assert "4: d" not in result


def test_read_file_error(monkeypatch, ctx):
    """read_file returns error message on gh failure."""

    def fake_run_gh(*args, **kwargs):
        msg = "gh api failed (exit 1): not found"
        raise RuntimeError(msg)

    monkeypatch.setattr("guardrails_review.tools.run_gh", fake_run_gh)

    result = execute_tool("read_file", json.dumps({"path": "missing.py"}), ctx)

    assert "Error reading missing.py" in result


# --- list_changed_files ---


def test_list_changed_files_success(monkeypatch, ctx):
    """list_changed_files returns formatted file list."""
    gh_output = json.dumps(
        {
            "files": [
                {"path": "src/main.py", "additions": 10, "deletions": 3},
                {"path": "tests/test_main.py", "additions": 20, "deletions": 0},
            ]
        }
    )

    def fake_run_gh(*args, **kwargs):
        return _gh_mock(gh_output)

    monkeypatch.setattr("guardrails_review.tools.run_gh", fake_run_gh)

    result = execute_tool("list_changed_files", "{}", ctx)

    assert "src/main.py (+10/-3)" in result
    assert "tests/test_main.py (+20/-0)" in result


def test_list_changed_files_empty(monkeypatch, ctx):
    """list_changed_files returns message when no files changed."""

    def fake_run_gh(*args, **kwargs):
        return _gh_mock(json.dumps({"files": []}))

    monkeypatch.setattr("guardrails_review.tools.run_gh", fake_run_gh)

    result = execute_tool("list_changed_files", "{}", ctx)

    assert "No changed files" in result


def test_list_changed_files_error(monkeypatch, ctx):
    """list_changed_files returns error on gh failure."""
    _err = "gh failed"

    def fake_run_gh(*args, **kwargs):
        raise RuntimeError(_err)

    monkeypatch.setattr("guardrails_review.tools.run_gh", fake_run_gh)

    result = execute_tool("list_changed_files", "{}", ctx)

    assert "Error listing changed files" in result


# --- search_code ---


def test_search_code_success(monkeypatch, ctx):
    """search_code returns formatted results."""

    def fake_run_gh(*args, **kwargs):
        return _gh_mock("src/main.py:def hello():\nsrc/utils.py:def world():\n")

    monkeypatch.setattr("guardrails_review.tools.run_gh", fake_run_gh)

    result = execute_tool("search_code", json.dumps({"query": "def hello"}), ctx)

    assert "src/main.py" in result


def test_search_code_strips_github_qualifiers(monkeypatch, ctx):
    """search_code strips GitHub search qualifiers from query."""
    captured_queries = []

    def fake_run_gh(*args, **kwargs):
        # Capture the -f q=... argument
        captured_queries.extend(
            a[2:] for a in args if isinstance(a, str) and a.startswith("q=")
        )
        return _gh_mock("src/main.py:def hello():\n")

    monkeypatch.setattr("guardrails_review.tools.run_gh", fake_run_gh)

    execute_tool(
        "search_code",
        json.dumps({"query": "def hello repo:evil/inject org:hacked"}),
        ctx,
    )

    assert len(captured_queries) == 1
    # The injected repo:/org: should be stripped; only our repo: should remain
    assert "repo:evil/inject" not in captured_queries[0]
    assert "org:hacked" not in captured_queries[0]
    assert "repo:acme/widgets" in captured_queries[0]
    assert "def hello" in captured_queries[0]


def test_search_code_no_results(monkeypatch, ctx):
    """search_code returns helpful message when no results found."""

    def fake_run_gh(*args, **kwargs):
        return _gh_mock("")

    monkeypatch.setattr("guardrails_review.tools.run_gh", fake_run_gh)

    result = execute_tool("search_code", json.dumps({"query": "nonexistent"}), ctx)

    assert "No results found" in result


def test_search_code_error(monkeypatch, ctx):
    """search_code returns error on gh failure."""
    _err = "gh api failed"

    def fake_run_gh(*args, **kwargs):
        raise RuntimeError(_err)

    monkeypatch.setattr("guardrails_review.tools.run_gh", fake_run_gh)

    result = execute_tool("search_code", json.dumps({"query": "test"}), ctx)

    assert "Error searching code" in result


# --- execute_tool dispatch ---


def test_execute_tool_unknown_raises(ctx):
    """Unknown tool name raises ValueError."""
    with pytest.raises(ValueError, match="Unknown tool: bogus"):
        execute_tool("bogus", "{}", ctx)


def test_execute_tool_submit_review_not_dispatched(ctx):
    """submit_review is handled by the loop, not execute_tool."""
    with pytest.raises(ValueError, match="Unknown tool: submit_review"):
        execute_tool("submit_review", "{}", ctx)


# --- Tool definitions ---


def test_tool_definitions_have_required_structure():
    """All tool definitions have the expected OpenRouter format."""
    assert len(TOOL_DEFINITIONS) == 4
    names = {t["function"]["name"] for t in TOOL_DEFINITIONS}
    assert names == {"read_file", "list_changed_files", "search_code", "submit_review"}
    for tool in TOOL_DEFINITIONS:
        assert tool["type"] == "function"
        assert "description" in tool["function"]
        assert "parameters" in tool["function"]


def test_submit_review_schema_has_no_severity():
    """submit_review tool schema should not include severity field."""
    submit_tool = next(
        t for t in TOOL_DEFINITIONS if t["function"]["name"] == "submit_review"
    )
    comment_props = submit_tool["function"]["parameters"]["properties"]["comments"][
        "items"
    ]["properties"]
    assert "severity" not in comment_props
    required = submit_tool["function"]["parameters"]["properties"]["comments"]["items"][
        "required"
    ]
    assert "severity" not in required
