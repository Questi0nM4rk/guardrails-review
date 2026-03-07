"""Tool definitions and execution for the agentic review loop."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import logging
import re
from typing import Any

from guardrails_review.github import run_gh

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolContext:
    """Context needed by tool implementations to access the PR."""

    pr: int
    owner: str
    repo: str
    commit_sha: str


TOOL_DEFINITIONS: list[dict[str, object]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a file from the repository at the PR head commit. "
                "Returns the file contents. Use start_line/end_line to read a slice."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative file path in the repository.",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": (
                            "First line to return (1-indexed, inclusive)."
                            " Omit for full file."
                        ),
                    },
                    "end_line": {
                        "type": "integer",
                        "description": (
                            "Last line to return (1-indexed, inclusive)."
                            " Omit for full file."
                        ),
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_changed_files",
            "description": (
                "List all files changed in the pull request with their change status."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": (
                "Search for code in the repository. "
                "Useful for finding callers, related functions, or test files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "think",
            "description": (
                "Write down your analysis and reasoning. Use this before taking any "
                "other action to plan your approach. The output is not shown to the "
                "PR author — it is only for your own reasoning."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reasoning": {
                        "type": "string",
                        "description": (
                            "Your analysis of the diff: what changed, what risks "
                            "you see, what context you need to gather."
                        ),
                    },
                },
                "required": ["reasoning"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "post_comments",
            "description": (
                "Post inline review comments to the PR immediately. "
                "Call this as soon as you find defects. Do not accumulate "
                "findings -- post each batch as you go."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "comments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "line": {"type": "integer"},
                                "body": {"type": "string"},
                                "start_line": {
                                    "type": "integer",
                                    "description": (
                                        "First line of a multi-line comment (optional)."
                                    ),
                                },
                            },
                            "required": ["path", "line", "body"],
                        },
                        "description": "Inline review comments to post.",
                    },
                },
                "required": ["comments"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_review",
            "description": (
                "Submit your review. This is your final action — call it when "
                "you have finished investigating all files. "
                "Use 'request_changes' if you found defects, "
                "'approve' if code is clean and no unresolved threads remain, "
                "'comment' if code is clean but unresolved threads from previous "
                "runs still exist (use this to confirm the commit is clean without "
                "overriding the existing block)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "verdict": {
                        "type": "string",
                        "enum": ["approve", "request_changes", "comment"],
                        "description": (
                            "'request_changes' if defects were found, "
                            "'approve' if code is clean and no open threads remain, "
                            "'comment' if code is clean but open threads exist."
                        ),
                    },
                    "summary": {
                        "type": "string",
                        "description": (
                            "Short summary shown in the review header. "
                            "E.g. '3 defects found.' or 'No defects found.'"
                        ),
                    },
                },
                "required": ["verdict", "summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_memory",
            "description": (
                "Read this bot's accumulated knowledge about the repository: "
                "conventions, patterns, and known false positives recorded from "
                "previous review rounds. Call this at the start of every review."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_memory",
            "description": (
                "Persist a new convention or false-positive pattern to the bot's "
                "memory so future reviews benefit from it. Call this when you "
                "learn something about how this codebase is structured that is "
                "not already in memory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "convention": {
                        "type": "string",
                        "description": (
                            "A convention or pattern observed in this codebase. "
                            "E.g. 'All DB queries use parameterised placeholders — "
                            "string interpolation in SQL is always a bug here.' "
                            "Prefix with 'FALSE POSITIVE: ' to record a pattern "
                            "that looks like a bug but is intentional."
                        ),
                    },
                },
                "required": ["convention"],
            },
        },
    },
]


def _think(args: dict[str, Any], ctx: ToolContext) -> str:  # noqa: ARG001
    """Accept reasoning from the model and acknowledge it."""
    reasoning = args.get("reasoning", "")
    logger.debug("Model reasoning: %s", reasoning)
    return "Noted. Continue with your review."


def execute_tool(name: str, arguments: str, ctx: ToolContext) -> str:
    """Dispatch a tool call and return the result as a string.

    Args:
        name: Tool function name.
        arguments: Raw JSON string of arguments.
        ctx: Context for accessing the PR.

    Returns:
        Tool execution result as a string.

    Raises:
        ValueError: If the tool name is unknown.
    """
    args = json.loads(arguments)

    dispatch = {
        "read_file": _read_file,
        "list_changed_files": _list_changed_files,
        "search_code": _search_code,
        "think": _think,
        "read_memory": _read_memory,
        "update_memory": _update_memory,
    }

    handler = dispatch.get(name)
    if handler is None:
        msg = f"Unknown tool: {name}"
        raise ValueError(msg)

    return handler(args, ctx)


def _read_file(args: dict[str, Any], ctx: ToolContext) -> str:
    """Read a file from the repo at the PR head commit."""
    path = args["path"]
    if path.startswith("/") or ".." in path.split("/"):
        return f"Invalid path: {path}"
    try:
        proc = run_gh(
            "api",
            f"repos/{ctx.owner}/{ctx.repo}/contents/{path}",
            "-q",
            ".content",
            "--method",
            "GET",
            "-f",
            f"ref={ctx.commit_sha}",
        )
    except RuntimeError as exc:
        return f"Error reading {path}: {exc}"

    try:
        content = base64.b64decode(proc.stdout.strip()).decode(errors="replace")
    except (ValueError, UnicodeDecodeError):
        return f"Error decoding {path}: could not base64-decode response"

    lines = content.splitlines()

    start = args.get("start_line")
    end = args.get("end_line")
    if start is not None or end is not None:
        start_idx = max(0, (start or 1) - 1)
        end_idx = end or len(lines)
        lines = lines[start_idx:end_idx]

    base_line = start if start is not None else 1
    numbered = [f"{i + base_line}: {line}" for i, line in enumerate(lines)]
    return "\n".join(numbered)


def _list_changed_files(_args: dict[str, Any], ctx: ToolContext) -> str:
    """List files changed in the PR."""
    try:
        proc = run_gh("pr", "view", str(ctx.pr), "--json", "files")
    except RuntimeError as exc:
        return f"Error listing changed files: {exc}"

    data = json.loads(proc.stdout)
    files = data.get("files", [])
    if not files:
        return "No changed files found."

    lines = []
    for f in files:
        path = f.get("path", "unknown")
        additions = f.get("additions", 0)
        deletions = f.get("deletions", 0)
        lines.append(f"{path} (+{additions}/-{deletions})")
    return "\n".join(lines)


_GITHUB_QUALIFIER_RE = re.compile(
    r"\b(repo|org|user|path|language|filename):\S+", re.IGNORECASE
)


def _read_memory(_args: dict[str, Any], ctx: ToolContext) -> str:
    """Return formatted memory for this repository."""
    from guardrails_review.memory import build_memory_context, load_memory  # noqa: PLC0415

    memory = load_memory(ctx.owner, ctx.repo)
    context = build_memory_context(memory)
    return context or "Memory is empty — no conventions recorded yet."


def _update_memory(args: dict[str, Any], ctx: ToolContext) -> str:
    """Append a convention to this repository's memory."""
    import dataclasses  # noqa: PLC0415

    from guardrails_review.memory import load_memory, save_memory  # noqa: PLC0415

    convention = args.get("convention", "").strip()
    if not convention:
        return "No convention provided — nothing written."

    memory = load_memory(ctx.owner, ctx.repo)
    if convention in memory.conventions:
        return "Convention already recorded."

    new_memory = dataclasses.replace(
        memory, conventions=[*memory.conventions, convention]
    )
    save_memory(new_memory)
    return f"Saved: {convention}"


def _search_code(args: dict[str, Any], ctx: ToolContext) -> str:
    """Search for code in the repository."""
    raw_query = args["query"]
    # Strip GitHub search qualifiers the LLM may inject to prevent scope escape
    query = _GITHUB_QUALIFIER_RE.sub("", raw_query).strip()
    search_query = f"{query} repo:{ctx.owner}/{ctx.repo}"
    try:
        proc = run_gh(
            "api",
            "search/code",
            "-X",
            "GET",
            "-f",
            f"q={search_query}",
            "-q",
            '.items[:10] | .[] | .path + ":" + (.text_matches[0].fragment // "")',
        )
    except RuntimeError as exc:
        return f"Error searching code: {exc}"

    result = proc.stdout.strip()
    if not result:
        return f"No results found for: {query}"
    return result
