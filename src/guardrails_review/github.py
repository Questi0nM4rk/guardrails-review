"""GitHub CLI wrapper for all GitHub operations.

All interactions with GitHub go through the ``gh`` CLI binary.
This module provides typed Python functions around common operations.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any

from guardrails_review.types import PRMetadata

if TYPE_CHECKING:
    from guardrails_review.types import ReviewComment, ReviewResult


class DiffTooLargeError(RuntimeError):
    """Raised when a PR diff exceeds GitHub's 20,000-line API limit."""

    def __init__(self, pr: int) -> None:
        super().__init__(
            f"PR #{pr} diff exceeds GitHub's 20,000-line limit — "
            "automated review skipped"
        )
        self.pr = pr


def run_gh(
    *args: str,
    timeout: int = 60,
    input_data: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a ``gh`` CLI command and return the result.

    Args:
        *args: Arguments to pass after ``gh``.
        timeout: Maximum seconds to wait for the process.
        input_data: Optional string to pass to stdin (for ``--input -`` patterns).

    Returns:
        The completed process on success.

    Raises:
        RuntimeError: If the command exits with a non-zero return code.
    """
    proc = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        input=input_data,
    )
    if proc.returncode != 0:
        msg = f"gh {' '.join(args)} failed (exit {proc.returncode}): {proc.stderr}"
        raise RuntimeError(msg)
    return proc


def get_pr_diff(pr: int, *, unified_context: int = 5) -> str:
    """Fetch the patch-format diff for a pull request.

    Attempts to use ``git diff`` for controllable context lines. Falls back to
    ``gh pr diff --patch`` (3-line context, GitHub default) if git is not
    available or the base branch cannot be fetched.

    Args:
        pr: Pull request number.
        unified_context: Lines of surrounding context per hunk (default 5).

    Returns:
        Unified diff string with ``unified_context`` lines of context per hunk.
    """
    import subprocess as _subprocess  # noqa: PLC0415

    try:
        meta = run_gh("pr", "view", str(pr), "--json", "baseRefName")
        base_ref = json.loads(meta.stdout)["baseRefName"]
        fetch = _subprocess.run(
            ["git", "fetch", "origin", base_ref],
            capture_output=True,
            text=True,
            check=False,
        )
        if fetch.returncode == 0:
            diff = _subprocess.run(
                ["git", "diff", f"origin/{base_ref}...HEAD", f"-U{unified_context}"],
                capture_output=True,
                text=True,
                check=False,
            )
            if diff.returncode == 0 and diff.stdout.strip():
                return diff.stdout
    except (RuntimeError, KeyError, json.JSONDecodeError):
        pass

    try:
        proc = run_gh("pr", "diff", str(pr), "--patch")
    except RuntimeError as exc:
        if "too_large" in str(exc) or "maximum number of lines" in str(exc):
            raise DiffTooLargeError(pr) from exc
        raise
    return proc.stdout


def get_pr_metadata(pr: int) -> PRMetadata:
    """Fetch pull request metadata as a typed dataclass.

    Args:
        pr: Pull request number.

    Returns:
        PRMetadata with title, body, head_ref_oid, base_ref_name.
    """
    proc = run_gh("pr", "view", str(pr), "--json", "title,body,headRefOid,baseRefName")
    data = json.loads(proc.stdout)
    return PRMetadata(
        title=data.get("title", ""),
        body=data.get("body") or "",  # GitHub returns null for empty body
        head_ref_oid=data.get("headRefOid", ""),
        base_ref_name=data.get("baseRefName", ""),
    )


def get_repo_info() -> tuple[str, str]:
    """Get the current repository owner and name.

    Returns:
        Tuple of (owner, repo_name).
    """
    proc = run_gh("repo", "view", "--json", "owner,name")
    data = json.loads(proc.stdout)
    owner: str = data["owner"]["login"]
    name: str = data["name"]
    return owner, name


def post_review(
    pr: int,
    result: ReviewResult,
    owner: str,
    repo: str,
    commit_sha: str,
) -> bool:
    """Post a pull request review via the GitHub API.

    Args:
        pr: Pull request number.
        result: The review result containing verdict, summary, and comments.
        owner: Repository owner.
        repo: Repository name.
        commit_sha: The commit SHA to attach the review to.

    Returns:
        True if the review was posted successfully.
    """
    event_map = {
        "approve": "APPROVE",
        "request_changes": "REQUEST_CHANGES",
    }
    event = event_map.get(result.verdict, "COMMENT")

    comments: list[dict[str, object]] = []
    for c in result.comments:
        entry: dict[str, object] = {
            "path": c.path,
            "line": c.line,
            "body": c.body,
            "side": "RIGHT",
        }
        if c.start_line is not None:
            entry["start_line"] = c.start_line
            entry["start_side"] = "RIGHT"
        comments.append(entry)

    payload = {
        "event": event,
        "body": result.summary,
        "commit_id": commit_sha,
        "comments": comments,
    }

    run_gh(
        "api",
        f"repos/{owner}/{repo}/pulls/{pr}/reviews",
        "--method",
        "POST",
        "--input",
        "-",
        input_data=json.dumps(payload),
    )

    return True


def create_pending_review(
    pr: int,
    owner: str,
    repo: str,
    commit_sha: str,
) -> int:
    """Create a pending (draft) pull request review and return its ID.

    The review is not visible to the PR author until submitted via
    ``submit_pending_review()``.  Inline comments are added separately
    via ``add_pending_review_comment()``.

    Args:
        pr: Pull request number.
        owner: Repository owner.
        repo: Repository name.
        commit_sha: The commit SHA to attach the review to.

    Returns:
        The GitHub review ID.
    """
    payload = {"commit_id": commit_sha}
    proc = run_gh(
        "api",
        f"repos/{owner}/{repo}/pulls/{pr}/reviews",
        "--method",
        "POST",
        "--input",
        "-",
        input_data=json.dumps(payload),
    )
    data = json.loads(proc.stdout)
    return int(data["id"])


def add_pending_review_comment(
    review_id: int,
    pr: int,
    comment: ReviewComment,
    owner: str,
    repo: str,
) -> None:
    """Add an inline comment to a pending pull request review.

    The comment is not visible until the review is submitted.

    Args:
        review_id: ID of the pending review (from ``create_pending_review()``).
        pr: Pull request number.
        comment: The review comment to add.
        owner: Repository owner.
        repo: Repository name.
    """
    entry: dict[str, object] = {
        "path": comment.path,
        "line": comment.line,
        "body": comment.body,
        "side": "RIGHT",
    }
    if comment.start_line is not None:
        entry["start_line"] = comment.start_line
        entry["start_side"] = "RIGHT"

    run_gh(
        "api",
        f"repos/{owner}/{repo}/pulls/{pr}/reviews/{review_id}/comments",
        "--method",
        "POST",
        "--input",
        "-",
        input_data=json.dumps(entry),
    )


def get_pending_review_comment_count(
    review_id: int,
    pr: int,
    owner: str,
    repo: str,
) -> int:
    """Return the number of inline comments on a pending review.

    Used to verify that comments survived GitHub API validation before
    deciding whether to submit as CHANGES_REQUESTED or APPROVE.

    Args:
        review_id: ID of the pending review.
        pr: Pull request number.
        owner: Repository owner.
        repo: Repository name.

    Returns:
        Number of inline comments currently on the review, or 0 on error.
    """
    try:
        proc = run_gh(
            "api",
            f"repos/{owner}/{repo}/pulls/{pr}/reviews/{review_id}/comments",
        )
        data: list = json.loads(proc.stdout)
        return len(data)
    except (RuntimeError, json.JSONDecodeError, TypeError):
        return 0


def submit_pending_review(  # noqa: PLR0913
    review_id: int,
    pr: int,
    verdict: str,
    body: str,
    owner: str,
    repo: str,
) -> None:
    """Submit a pending pull request review with the given verdict.

    Args:
        review_id: ID of the pending review (from ``create_pending_review()``).
        pr: Pull request number.
        verdict: One of ``"approve"``, ``"request_changes"``, ``"comment"``.
        body: Summary text shown in the review header.
        owner: Repository owner.
        repo: Repository name.
    """
    event_map = {
        "approve": "APPROVE",
        "request_changes": "REQUEST_CHANGES",
        "comment": "COMMENT",
    }
    event = event_map.get(verdict, "COMMENT")
    payload = {"event": event, "body": body}
    run_gh(
        "api",
        f"repos/{owner}/{repo}/pulls/{pr}/reviews/{review_id}/events",
        "--method",
        "POST",
        "--input",
        "-",
        input_data=json.dumps(payload),
    )


def graphql(
    query: str, variables: dict[str, str | int] | None = None
) -> dict[str, Any]:
    """Execute a GraphQL query via ``gh api graphql``.

    Returns dict[str, Any] intentionally -- GraphQL response shape varies by query.
    Callers must validate the response structure for their specific query.

    Args:
        query: GraphQL query string.
        variables: Optional variables dict. Int values use ``-F``, strings use ``-f``.

    Returns:
        Parsed JSON response dict.

    Raises:
        RuntimeError: If the command fails.
    """
    args: list[str] = ["api", "graphql", "-f", f"query={query}"]
    if variables:
        for key, value in variables.items():
            if isinstance(value, int):
                args.extend(["-F", f"{key}={value}"])
            else:
                args.extend(["-f", f"{key}={value}"])
    proc = run_gh(*args)
    result: dict[str, Any] = json.loads(proc.stdout)
    return result


def resolve_thread(thread_id: str) -> bool:
    """Resolve a review thread via GraphQL mutation.

    Args:
        thread_id: GraphQL node ID of the thread.

    Returns:
        True if resolved successfully, False otherwise.
    """
    mutation = """
    mutation($threadId: ID!) {
      resolveReviewThread(input: {threadId: $threadId}) {
        thread { id isResolved }
      }
    }
    """
    try:
        graphql(mutation, variables={"threadId": thread_id})
    except RuntimeError:
        return False
    return True


def get_deleted_files(pr: int) -> set[str]:
    """Get the set of files deleted in a pull request.

    Args:
        pr: Pull request number.

    Returns:
        Set of file paths with status "removed".
    """
    proc = run_gh("pr", "view", str(pr), "--json", "files")
    data = json.loads(proc.stdout)
    return {f["path"] for f in data.get("files", []) if f.get("status") == "removed"}


def set_commit_status(
    owner: str,
    repo: str,
    sha: str,
    state: str,
    description: str,
) -> None:
    """Set a commit status check on a specific SHA.

    Args:
        owner: Repository owner.
        repo: Repository name.
        sha: Commit SHA to set status on.
        state: One of "pending", "success", "failure", "error".
        description: Short description of the status.

    Raises:
        RuntimeError: If the API call fails.
    """
    run_gh(
        "api",
        f"repos/{owner}/{repo}/statuses/{sha}",
        "--method",
        "POST",
        "-f",
        f"state={state}",
        "-f",
        f"description={description}",
        "-f",
        "context=guardrails-review",
    )


def enable_auto_merge(pr: int, *, merge_method: str = "squash") -> bool:
    """Enable auto-merge on a pull request.

    Args:
        pr: Pull request number.
        merge_method: One of "squash", "merge", or "rebase".

    Returns:
        True if auto-merge was enabled, False if already enabled or unsupported.
    """
    try:
        run_gh("pr", "merge", str(pr), "--auto", f"--{merge_method}")
    except RuntimeError:
        return False
    return True


def approve_pr(pr: int, body: str) -> bool:
    """Approve a pull request with a comment.

    Args:
        pr: Pull request number.
        body: Approval message.

    Returns:
        True if the approval was posted successfully.
    """
    run_gh("pr", "review", str(pr), "--approve", "-b", body)
    return True


def request_changes(pr: int, body: str) -> bool:
    """Request changes on a pull request with a comment.

    Args:
        pr: Pull request number.
        body: Message explaining requested changes.

    Returns:
        True if the request was posted successfully.
    """
    run_gh("pr", "review", str(pr), "--request-changes", "-b", body)
    return True
