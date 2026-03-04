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


def get_pr_diff(pr: int) -> str:
    """Fetch the patch-format diff for a pull request.

    Args:
        pr: Pull request number.

    Returns:
        The unified diff string (3 context lines per hunk, gh default).
        Use the read_file tool for additional surrounding context when reviewing.
    """
    proc = run_gh("pr", "diff", str(pr), "--patch")
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


def post_inline_comments(
    pr: int,
    comments: list[ReviewComment],
    owner: str,
    repo: str,
    commit_sha: str,
) -> bool:
    """Post inline comments as a COMMENT review (no verdict).

    Uses ``event=COMMENT`` with an empty body.  This allows incremental
    posting during the agentic loop without affecting the final verdict.

    Args:
        pr: Pull request number.
        comments: Review comments to post inline.
        owner: Repository owner.
        repo: Repository name.
        commit_sha: The commit SHA to attach comments to.

    Returns:
        True on success, False on failure.
    """
    if not comments:
        return True

    api_comments: list[dict[str, object]] = []
    for c in comments:
        entry: dict[str, object] = {
            "path": c.path,
            "line": c.line,
            "body": c.body,
            "side": "RIGHT",
        }
        if c.start_line is not None:
            entry["start_line"] = c.start_line
            entry["start_side"] = "RIGHT"
        api_comments.append(entry)

    payload = {
        "event": "COMMENT",
        "body": "",
        "commit_id": commit_sha,
        "comments": api_comments,
    }

    try:
        run_gh(
            "api",
            f"repos/{owner}/{repo}/pulls/{pr}/reviews",
            "--method",
            "POST",
            "--input",
            "-",
            input_data=json.dumps(payload),
        )
    except RuntimeError:
        return False

    return True


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
