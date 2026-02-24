"""GitHub CLI wrapper for all GitHub operations.

All interactions with GitHub go through the ``gh`` CLI binary.
This module provides typed Python functions around common operations.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from guardrails_review.types import ReviewResult


def run_gh(*args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Run a ``gh`` CLI command and return the result.

    Args:
        *args: Arguments to pass after ``gh``.
        timeout: Maximum seconds to wait for the process.

    Returns:
        The completed process on success.

    Raises:
        RuntimeError: If the command exits with a non-zero return code.
    """
    proc = subprocess.run(  # noqa: S603 — args are controlled by callers in this module
        ["gh", *args],  # noqa: S607 — "gh" is a known CLI binary
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
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
        The unified diff string.
    """
    proc = run_gh("pr", "diff", str(pr), "--patch")
    return proc.stdout


def get_pr_metadata(pr: int) -> dict[str, str]:
    """Fetch pull request metadata as a dict.

    Args:
        pr: Pull request number.

    Returns:
        Dict with keys: title, body, headRefOid, baseRefName.
    """
    proc = run_gh("pr", "view", str(pr), "--json", "title,body,headRefOid,baseRefName")
    result: dict[str, str] = json.loads(proc.stdout)
    return result


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

    cmd_args = [
        "gh",
        "api",
        f"repos/{owner}/{repo}/pulls/{pr}/reviews",
        "--method",
        "POST",
        "--input",
        "-",
    ]
    proc = subprocess.run(  # noqa: S603 — args are constructed from validated parameters
        cmd_args,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0:
        msg = f"post_review failed (exit {proc.returncode}): {proc.stderr}"
        raise RuntimeError(msg)

    return True


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
