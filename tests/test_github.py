"""Tests for guardrails_review.github module."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from guardrails_review.github import (
    approve_pr,
    get_pr_diff,
    get_pr_metadata,
    get_repo_info,
    post_review,
    request_changes,
    run_gh,
)
from guardrails_review.types import ReviewComment, ReviewResult


def _make_completed_process(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    """Build a fake CompletedProcess for test assertions."""
    return subprocess.CompletedProcess(
        args=["gh"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_run_gh_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_gh returns CompletedProcess on zero exit code."""
    expected = _make_completed_process(stdout="ok\n")

    def mock_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert args[0] == "gh"
        assert args[1:] == ["pr", "list"]
        return expected

    monkeypatch.setattr("subprocess.run", mock_run)

    result = run_gh("pr", "list")

    assert result.stdout == "ok\n"
    assert result.returncode == 0


def test_run_gh_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_gh raises RuntimeError on non-zero exit code."""

    def mock_run(_args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _make_completed_process(returncode=1, stderr="not found")

    monkeypatch.setattr("subprocess.run", mock_run)

    with pytest.raises(RuntimeError, match="not found"):
        run_gh("pr", "view")


def test_get_pr_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_pr_diff returns the diff string from gh pr diff."""
    diff_text = "diff --git a/foo.py b/foo.py\n+hello\n"

    def mock_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert "diff" in args
        assert "--patch" in args
        assert "42" in args
        return _make_completed_process(stdout=diff_text)

    monkeypatch.setattr("subprocess.run", mock_run)

    result = get_pr_diff(42)

    assert result == diff_text


def test_get_pr_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_pr_metadata returns parsed JSON dict with PR fields."""
    metadata = {
        "title": "Fix bug",
        "body": "Description here",
        "headRefOid": "abc123",
        "baseRefName": "main",
    }

    def mock_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert "--json" in args
        return _make_completed_process(stdout=json.dumps(metadata))

    monkeypatch.setattr("subprocess.run", mock_run)

    result = get_pr_metadata(42)

    assert result["title"] == "Fix bug"
    assert result["headRefOid"] == "abc123"
    assert result["baseRefName"] == "main"


def test_get_repo_info(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_repo_info returns (owner, repo) tuple."""
    repo_json = {"owner": {"login": "myorg"}, "name": "myrepo"}

    def mock_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert "repo" in args
        assert "view" in args
        return _make_completed_process(stdout=json.dumps(repo_json))

    monkeypatch.setattr("subprocess.run", mock_run)

    owner, repo = get_repo_info()

    assert owner == "myorg"
    assert repo == "myrepo"


def test_post_review_approve(monkeypatch: pytest.MonkeyPatch) -> None:
    """post_review sends APPROVE event for approve verdict."""
    captured_stdin: list[str] = []

    def mock_run(_args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if kwargs.get("input"):
            captured_stdin.append(kwargs["input"])
        return _make_completed_process(stdout="{}")

    monkeypatch.setattr("subprocess.run", mock_run)

    result_obj = ReviewResult(verdict="approve", summary="LGTM")
    success = post_review(pr=1, result=result_obj, owner="org", repo="repo", commit_sha="abc123")

    assert success is True
    body = json.loads(captured_stdin[0])
    assert body["event"] == "APPROVE"
    assert body["body"] == "LGTM"
    assert body["commit_id"] == "abc123"


def test_post_review_request_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """post_review sends REQUEST_CHANGES event for request_changes verdict."""
    captured_stdin: list[str] = []

    def mock_run(_args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if kwargs.get("input"):
            captured_stdin.append(kwargs["input"])
        return _make_completed_process(stdout="{}")

    monkeypatch.setattr("subprocess.run", mock_run)

    result_obj = ReviewResult(verdict="request_changes", summary="Fix issues")
    success = post_review(pr=2, result=result_obj, owner="org", repo="repo", commit_sha="def456")

    assert success is True
    body = json.loads(captured_stdin[0])
    assert body["event"] == "REQUEST_CHANGES"


def test_post_review_with_comments(monkeypatch: pytest.MonkeyPatch) -> None:
    """post_review includes comment array with correct structure."""
    captured_stdin: list[str] = []

    def mock_run(_args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if kwargs.get("input"):
            captured_stdin.append(kwargs["input"])
        return _make_completed_process(stdout="{}")

    monkeypatch.setattr("subprocess.run", mock_run)

    comments = [
        ReviewComment(path="src/foo.py", line=10, body="Bug here", severity="error"),
        ReviewComment(
            path="src/bar.py",
            line=20,
            body="Multi-line issue",
            severity="warning",
            start_line=15,
        ),
    ]
    result_obj = ReviewResult(verdict="request_changes", summary="Issues found", comments=comments)
    post_review(pr=3, result=result_obj, owner="org", repo="repo", commit_sha="ghi789")

    body = json.loads(captured_stdin[0])
    assert len(body["comments"]) == 2

    # Simple comment: no start_line
    c0 = body["comments"][0]
    assert c0["path"] == "src/foo.py"
    assert c0["line"] == 10
    assert c0["body"] == "Bug here"
    assert c0["side"] == "RIGHT"
    assert "start_line" not in c0

    # Multi-line comment: has start_line
    c1 = body["comments"][1]
    assert c1["path"] == "src/bar.py"
    assert c1["line"] == 20
    assert c1["start_line"] == 15
    assert c1["start_side"] == "RIGHT"
    assert c1["side"] == "RIGHT"


def test_approve_pr(monkeypatch: pytest.MonkeyPatch) -> None:
    """approve_pr calls gh pr review --approve with body."""
    captured_args: list[list[str]] = []

    def mock_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured_args.append(args)
        return _make_completed_process()

    monkeypatch.setattr("subprocess.run", mock_run)

    success = approve_pr(42, "Looks good")

    assert success is True
    assert captured_args[0] == [
        "gh",
        "pr",
        "review",
        "42",
        "--approve",
        "-b",
        "Looks good",
    ]


def test_request_changes_pr(monkeypatch: pytest.MonkeyPatch) -> None:
    """request_changes calls gh pr review --request-changes with body."""
    captured_args: list[list[str]] = []

    def mock_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured_args.append(args)
        return _make_completed_process()

    monkeypatch.setattr("subprocess.run", mock_run)

    success = request_changes(42, "Please fix")

    assert success is True
    assert captured_args[0] == [
        "gh",
        "pr",
        "review",
        "42",
        "--request-changes",
        "-b",
        "Please fix",
    ]
