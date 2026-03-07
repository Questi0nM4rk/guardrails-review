"""Tests for guardrails_review.github module."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from guardrails_review.github import (
    add_pending_review_comment,
    approve_pr,
    create_pending_review,
    get_deleted_files,
    get_pr_diff,
    get_pr_metadata,
    get_repo_info,
    graphql,
    post_review,
    request_changes,
    resolve_thread,
    run_gh,
    set_commit_status,
    submit_pending_review,
)
from guardrails_review.types import PRMetadata, ReviewComment, ReviewResult


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


def test_run_gh_with_input_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_gh passes input_data to subprocess stdin."""
    captured_kwargs: list[dict[str, Any]] = []

    def mock_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured_kwargs.append(kwargs)
        return _make_completed_process(stdout="ok\n")

    monkeypatch.setattr("subprocess.run", mock_run)

    run_gh("api", "endpoint", "--input", "-", input_data='{"key": "value"}')

    assert captured_kwargs[0]["input"] == '{"key": "value"}'


def test_run_gh_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_gh raises RuntimeError on non-zero exit code."""

    def mock_run(_args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _make_completed_process(returncode=1, stderr="not found")

    monkeypatch.setattr("subprocess.run", mock_run)

    with pytest.raises(RuntimeError, match="not found"):
        run_gh("pr", "view")


def test_get_pr_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_pr_diff returns the diff string (via git diff primary path)."""
    diff_text = "diff --git a/foo.py b/foo.py\n+hello\n"

    def mock_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["gh", "pr"] and "view" in args:
            return _make_completed_process(stdout='{"baseRefName": "main"}')
        if args[0] == "git" and args[1] == "fetch":
            return _make_completed_process(stdout="")
        if args[0] == "git" and args[1] == "diff":
            return _make_completed_process(stdout=diff_text)
        return _make_completed_process(stdout="")

    monkeypatch.setattr("subprocess.run", mock_run)

    result = get_pr_diff(42)

    assert result == diff_text


def test_get_pr_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_pr_metadata returns PRMetadata dataclass."""
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

    assert isinstance(result, PRMetadata)
    assert result.title == "Fix bug"
    assert result.body == "Description here"
    assert result.head_ref_oid == "abc123"
    assert result.base_ref_name == "main"


def test_get_pr_metadata_null_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_pr_metadata handles null body from GitHub (returns empty string)."""
    metadata = {
        "title": "Fix bug",
        "body": None,
        "headRefOid": "abc123",
        "baseRefName": "main",
    }

    def mock_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _make_completed_process(stdout=json.dumps(metadata))

    monkeypatch.setattr("subprocess.run", mock_run)

    result = get_pr_metadata(42)

    assert result.body == ""


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
    success = post_review(
        pr=1, result=result_obj, owner="org", repo="repo", commit_sha="abc123"
    )

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
    success = post_review(
        pr=2, result=result_obj, owner="org", repo="repo", commit_sha="def456"
    )

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
            severity="error",
            start_line=15,
        ),
    ]
    result_obj = ReviewResult(
        verdict="request_changes", summary="Issues found", comments=comments
    )
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


def test_post_review_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """post_review raises RuntimeError when the API call fails."""

    def mock_run(_args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _make_completed_process(returncode=1, stderr="permission denied")

    monkeypatch.setattr("subprocess.run", mock_run)

    result_obj = ReviewResult(verdict="approve", summary="LGTM")
    with pytest.raises(RuntimeError, match="permission denied"):
        post_review(pr=1, result=result_obj, owner="org", repo="repo", commit_sha="abc")


def test_set_commit_status_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """set_commit_status calls gh api with correct args."""
    captured_args: list[list[str]] = []

    def mock_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured_args.append(args)
        return _make_completed_process(stdout="{}")

    monkeypatch.setattr("subprocess.run", mock_run)

    set_commit_status("myorg", "myrepo", "abc123", "pending", "Review in progress")

    assert len(captured_args) == 1
    cmd = " ".join(captured_args[0])
    assert "repos/myorg/myrepo/statuses/abc123" in cmd
    assert "POST" in cmd
    assert "pending" in cmd
    assert "guardrails-review" in cmd


def test_set_commit_status_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """set_commit_status raises RuntimeError on gh failure."""

    def mock_run(_args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _make_completed_process(returncode=1, stderr="forbidden")

    monkeypatch.setattr("subprocess.run", mock_run)

    with pytest.raises(RuntimeError, match="forbidden"):
        set_commit_status("myorg", "myrepo", "abc123", "success", "OK")


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


# --- graphql ---


def test_graphql_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Graphql returns parsed JSON from gh api graphql."""
    response = {"data": {"repository": {"name": "test"}}}

    def mock_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert "graphql" in args
        return _make_completed_process(stdout=json.dumps(response))

    monkeypatch.setattr("subprocess.run", mock_run)

    result = graphql("query { repository { name } }")

    assert result == response


def test_graphql_with_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """Graphql passes variables via -f and -F flags."""
    captured_args: list[list[str]] = []

    def mock_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured_args.append(args)
        return _make_completed_process(stdout='{"data": {}}')

    monkeypatch.setattr("subprocess.run", mock_run)

    graphql(
        "query($pr: Int!) { pullRequest(number: $pr) { id } }",
        variables={"pr": 42, "owner": "myorg"},
    )

    cmd = " ".join(captured_args[0])
    # int variable uses -F, string uses -f
    assert "-F pr=42" in cmd
    assert "-f owner=myorg" in cmd


# --- resolve_thread ---


def test_resolve_thread_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_thread calls GraphQL mutation and returns True."""
    response = {
        "data": {"resolveReviewThread": {"thread": {"id": "t1", "isResolved": True}}}
    }

    def mock_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _make_completed_process(stdout=json.dumps(response))

    monkeypatch.setattr("subprocess.run", mock_run)

    result = resolve_thread("t1")

    assert result is True


def test_resolve_thread_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_thread returns False on failure."""

    def mock_run(_args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _make_completed_process(returncode=1, stderr="error")

    monkeypatch.setattr("subprocess.run", mock_run)

    result = resolve_thread("t1")

    assert result is False


# --- get_deleted_files ---


def test_get_deleted_files_returns_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_deleted_files returns set of removed file paths."""
    pr_files = {
        "files": [
            {"path": "a.py", "additions": 10, "deletions": 0},
            {
                "path": "deleted.py",
                "additions": 0,
                "deletions": 20,
                "status": "removed",
            },
            {"path": "renamed.py", "additions": 5, "deletions": 5, "status": "renamed"},
        ]
    }

    def mock_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _make_completed_process(stdout=json.dumps(pr_files))

    monkeypatch.setattr("subprocess.run", mock_run)

    result = get_deleted_files(42)

    assert result == {"deleted.py"}


def test_get_deleted_files_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_deleted_files returns empty set when no files deleted."""

    def mock_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _make_completed_process(stdout=json.dumps({"files": []}))

    monkeypatch.setattr("subprocess.run", mock_run)

    result = get_deleted_files(42)

    assert result == set()


def test_get_pr_diff_uses_git_diff_with_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_pr_diff uses git diff with -U5 context when git succeeds."""
    captured_args: list[list[str]] = []
    diff_text = "diff --git a/foo.py b/foo.py\n+hello\n"

    def mock_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured_args.append(args)
        if args[:2] == ["gh", "pr"]:
            return _make_completed_process(stdout='{"baseRefName": "main"}')
        # git fetch and git diff both succeed
        if args[0] == "git" and args[1] == "fetch":
            return _make_completed_process(stdout="")
        if args[0] == "git" and args[1] == "diff":
            return _make_completed_process(stdout=diff_text)
        return _make_completed_process(stdout="")

    monkeypatch.setattr("subprocess.run", mock_run)

    result = get_pr_diff(42)

    assert result == diff_text
    git_diff_calls = [a for a in captured_args if a[0] == "git" and a[1] == "diff"]
    assert git_diff_calls, "git diff should have been called"
    assert any("-U5" in a for a in git_diff_calls[0])


def test_get_pr_diff_falls_back_to_gh_on_git_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_pr_diff falls back to gh pr diff when git fetch fails."""
    diff_text = "diff --git a/foo.py b/foo.py\n+hello\n"

    def mock_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["gh", "pr"] and "view" in args:
            return _make_completed_process(stdout='{"baseRefName": "main"}')
        if args[0] == "git" and args[1] == "fetch":
            return _make_completed_process(stdout="", returncode=1)
        if args[:2] == ["gh", "pr"] and "diff" in args:
            return _make_completed_process(stdout=diff_text)
        return _make_completed_process(stdout="")

    monkeypatch.setattr("subprocess.run", mock_run)

    result = get_pr_diff(42)

    assert result == diff_text


def test_get_pr_diff_raises_diff_too_large_on_406(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_pr_diff raises DiffTooLargeError when gh reports the diff is too large."""
    from guardrails_review.github import DiffTooLargeError

    too_large_stderr = (
        "could not find pull request diff: HTTP 406: "
        "Sorry, the diff exceeded the maximum number of lines (20000) "
        "PullRequest.diff too_large"
    )

    def mock_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["gh", "pr"] and "view" in args:
            return _make_completed_process(stdout='{"baseRefName": "main"}')
        if args[0] == "git" and args[1] == "fetch":
            return _make_completed_process(stdout="", returncode=1)
        if args[:2] == ["gh", "pr"] and "diff" in args:
            return _make_completed_process(stdout="", stderr=too_large_stderr, returncode=1)
        return _make_completed_process(stdout="")

    monkeypatch.setattr("subprocess.run", mock_run)

    with pytest.raises(DiffTooLargeError, match="PR #42"):
        get_pr_diff(42)


# --- enable_auto_merge ---


def test_enable_auto_merge_calls_pr_merge_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    """enable_auto_merge calls gh pr merge --auto --squash."""
    from guardrails_review.github import enable_auto_merge

    captured: list[list[str]] = []

    def mock_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.append(args)
        return _make_completed_process(stdout="")

    monkeypatch.setattr("subprocess.run", mock_run)

    result = enable_auto_merge(42)

    assert result is True
    assert captured[0] == ["gh", "pr", "merge", "42", "--auto", "--squash"]


def test_enable_auto_merge_returns_false_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """enable_auto_merge returns False when gh command fails."""
    from guardrails_review.github import enable_auto_merge

    def mock_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _make_completed_process(stdout="", returncode=1)

    monkeypatch.setattr("subprocess.run", mock_run)

    result = enable_auto_merge(42)

    assert result is False


# --- Pending review API ---


def test_create_pending_review_returns_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_pending_review POSTs to /reviews with commit_id and returns review ID."""
    captured: list[dict[str, Any]] = []

    def mock_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.append({"args": args, "input": kwargs.get("input", "")})
        return _make_completed_process(stdout='{"id": 999}')

    monkeypatch.setattr("subprocess.run", mock_run)

    review_id = create_pending_review(pr=42, owner="org", repo="repo", commit_sha="abc123")

    assert review_id == 999
    payload = json.loads(captured[0]["input"])
    assert payload == {"commit_id": "abc123"}
    assert "pulls/42/reviews" in " ".join(captured[0]["args"])


def test_add_pending_review_comment_sends_correct_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """add_pending_review_comment POSTs to /reviews/{id}/comments with correct body."""
    captured: list[dict[str, Any]] = []

    def mock_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.append({"args": args, "input": kwargs.get("input", "")})
        return _make_completed_process(stdout="{}")

    monkeypatch.setattr("subprocess.run", mock_run)

    comment = ReviewComment(
        path="src/foo.py", line=10, body="Bug here", severity="error", start_line=8
    )
    add_pending_review_comment(review_id=999, pr=42, comment=comment, owner="org", repo="repo")

    assert len(captured) == 1
    url_part = " ".join(captured[0]["args"])
    assert "pulls/42/reviews/999/comments" in url_part
    payload = json.loads(captured[0]["input"])
    assert payload["path"] == "src/foo.py"
    assert payload["line"] == 10
    assert payload["side"] == "RIGHT"
    assert payload["start_line"] == 8
    assert payload["start_side"] == "RIGHT"


def test_submit_pending_review_sends_correct_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """submit_pending_review POSTs to /reviews/{id}/events with event and body."""
    captured: list[dict[str, Any]] = []

    def mock_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.append({"args": args, "input": kwargs.get("input", "")})
        return _make_completed_process(stdout="{}")

    monkeypatch.setattr("subprocess.run", mock_run)

    submit_pending_review(
        review_id=999,
        pr=42,
        verdict="request_changes",
        body="2 defects found.",
        owner="org",
        repo="repo",
    )

    assert len(captured) == 1
    url_part = " ".join(captured[0]["args"])
    assert "pulls/42/reviews/999/events" in url_part
    payload = json.loads(captured[0]["input"])
    assert payload["event"] == "REQUEST_CHANGES"
    assert payload["body"] == "2 defects found."


def test_submit_pending_review_maps_all_verdicts(monkeypatch: pytest.MonkeyPatch) -> None:
    """submit_pending_review maps all verdict strings to correct GitHub event values."""
    payloads: list[dict[str, Any]] = []

    def mock_run(_args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        payloads.append(json.loads(kwargs.get("input", "{}")))
        return _make_completed_process(stdout="{}")

    monkeypatch.setattr("subprocess.run", mock_run)

    for verdict, expected_event in [
        ("approve", "APPROVE"),
        ("request_changes", "REQUEST_CHANGES"),
        ("comment", "COMMENT"),
        ("unknown", "COMMENT"),  # fallback
    ]:
        submit_pending_review(
            review_id=1, pr=1, verdict=verdict, body="", owner="o", repo="r"
        )

    assert [p["event"] for p in payloads] == [
        "APPROVE",
        "REQUEST_CHANGES",
        "COMMENT",
        "COMMENT",
    ]
