"""Review thread lifecycle: fetch, filter, resolve, deduplicate."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from guardrails_review.github import graphql
from guardrails_review.types import (
    REVIEW_MARKER,
    ReviewThread,
    ThreadResolution,
)

if TYPE_CHECKING:
    from guardrails_review.types import ReviewComment

logger = logging.getLogger(__name__)

_THREADS_QUERY = """\
query($owner: String!, $repo: String!, $pr: Int!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id isResolved isOutdated path line
          comments(first: 1) {
            nodes { body author { login } createdAt }
          }
        }
      }
    }
  }
}
"""


def get_review_threads(pr: int, owner: str, repo: str) -> list[ReviewThread]:
    """Fetch all review threads via GraphQL with cursor-based pagination.

    Args:
        pr: Pull request number.
        owner: Repository owner.
        repo: Repository name.

    Returns:
        List of all review threads on the PR.
    """
    threads: list[ReviewThread] = []
    cursor: str | None = None

    while True:
        variables: dict[str, str | int] = {
            "owner": owner,
            "repo": repo,
            "pr": pr,
        }
        if cursor is not None:
            variables["cursor"] = cursor

        data = graphql(_THREADS_QUERY, variables=variables)

        review_threads = (
            data.get("data", {})
            .get("repository", {})
            .get("pullRequest", {})
            .get("reviewThreads", {})
        )
        nodes = review_threads.get("nodes", [])

        for node in nodes:
            comments = node.get("comments", {}).get("nodes", [])
            first_comment = comments[0] if comments else {}
            author_info = first_comment.get("author", {})

            threads.append(
                ReviewThread(
                    thread_id=node["id"],
                    path=node.get("path", ""),
                    line=node.get("line"),
                    body=first_comment.get("body", ""),
                    is_resolved=node.get("isResolved", False),
                    is_outdated=node.get("isOutdated", False),
                    author=author_info.get("login", ""),
                    created_at=first_comment.get("createdAt", ""),
                )
            )

        page_info = review_threads.get("pageInfo", {})
        if not page_info.get("hasNextPage", False):
            break
        cursor = page_info.get("endCursor")

    return threads


def get_our_threads(threads: list[ReviewThread]) -> list[ReviewThread]:
    """Filter threads to those containing the guardrails-review marker.

    Args:
        threads: All review threads.

    Returns:
        Threads that contain the ``<!-- guardrails-review -->`` marker.
    """
    return [t for t in threads if REVIEW_MARKER in t.body]


def find_resolvable_threads(
    threads: list[ReviewThread],
    valid_lines: dict[str, set[int]],
    deleted_files: set[str],
    head_sha: str,
) -> list[ThreadResolution]:
    """Determine which unresolved threads can be auto-resolved.

    Resolution rules (conservative):
    1. File deleted -> "File removed"
    2. GitHub marked outdated -> "Code changed (outdated)"
    3. Thread line no longer in diff -> "Line modified in {sha}"
    When in doubt, leave open.

    Args:
        threads: Our unresolved review threads.
        valid_lines: Map of file path -> set of line numbers in the current diff.
        deleted_files: Set of file paths deleted in the PR.
        head_sha: Current HEAD commit SHA.

    Returns:
        List of ThreadResolution for threads that can be resolved.
    """
    resolutions: list[ThreadResolution] = []

    for t in threads:
        if t.is_resolved:
            continue

        if t.path in deleted_files:
            resolutions.append(
                ThreadResolution(
                    thread_id=t.thread_id, resolved=True, reason="File removed"
                )
            )
        elif t.is_outdated:
            resolutions.append(
                ThreadResolution(
                    thread_id=t.thread_id,
                    resolved=True,
                    reason="Code changed (outdated)",
                )
            )
        elif t.line is not None and t.line not in valid_lines.get(t.path, set()):
            resolutions.append(
                ThreadResolution(
                    thread_id=t.thread_id,
                    resolved=True,
                    reason=f"Line modified in {head_sha}",
                )
            )

    return resolutions


def deduplicate_comments(
    new_comments: list[ReviewComment],
    existing_threads: list[ReviewThread],
) -> list[ReviewComment]:
    """Remove new comments that duplicate existing unresolved threads.

    Matches on (path, line) only -- LLM text is non-deterministic so exact
    body match is unreliable.

    Args:
        new_comments: Comments about to be posted.
        existing_threads: Existing review threads from GitHub.

    Returns:
        Filtered list of comments with duplicates removed.
    """
    existing = {(t.path, t.line) for t in existing_threads if not t.is_resolved}
    return [c for c in new_comments if (c.path, c.line) not in existing]
