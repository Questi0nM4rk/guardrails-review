"""Parse unified diff output to extract valid line numbers for review comments.

GitHub's review API returns 422 for comments on lines outside the diff,
so we need to know exactly which right-side lines are valid targets.
"""

from __future__ import annotations

import re

_DIFF_HEADER_RE = re.compile(r"^diff --git a/.+ b/(.+)$")
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_METADATA_PREFIXES = (
    "index ",
    "--- ",
    "+++ ",
    "new file mode",
    "deleted file mode",
    "similarity index",
    "rename from ",
    "rename to ",
    "old mode",
    "new mode",
)


def _is_metadata(line: str) -> bool:
    """Return True if the line is diff metadata (not content)."""
    return line.startswith(_METADATA_PREFIXES) or line.startswith("\\ ")


def format_diff_with_lines(diff: str) -> str:
    """Format a unified diff with embedded right-side line numbers.

    For each ``+`` (addition) or `` `` (context) line, prepends
    ``LINE_N:`` so the LLM can reference precise line numbers.
    Deletion lines, headers, and binary markers are output unchanged.

    Args:
        diff: Full unified diff string.

    Returns:
        The reformatted diff with ``LINE_N:`` prefixes on content lines.
    """
    if not diff:
        return ""

    output: list[str] = []
    right_line = 0

    for line in diff.splitlines():
        # New file header — output unchanged, reset nothing
        header_match = _DIFF_HEADER_RE.match(line)
        if header_match:
            output.append(line)
            continue

        # Binary file marker — output unchanged
        if line.startswith("Binary files "):
            output.append(line)
            continue

        # Metadata lines — output unchanged
        if _is_metadata(line):
            output.append(line)
            continue

        # Hunk header — output unchanged, reset right_line counter
        hunk_match = _HUNK_RE.match(line)
        if hunk_match:
            right_line = int(hunk_match.group(1))
            output.append(line)
            continue

        # Addition (+) or context ( ) line — prefix with LINE_N:
        if line.startswith((" ", "+")):
            prefix = line[0]
            content = line[1:]
            output.append(f"{prefix}LINE_{right_line}: {content}")
            right_line += 1
            continue

        # Deletion (-) line — output unchanged, right_line does not advance
        output.append(line)

    return "\n".join(output)


def parse_diff_hunks(diff: str) -> dict[str, set[int]]:
    """Parse unified diff and return valid right-side line numbers per file.

    Args:
        diff: Full unified diff output (e.g. from ``gh pr diff --patch``).

    Returns:
        Mapping of file path to set of right-side line numbers where review
        comments can be placed (context lines and additions).
    """
    if not diff:
        return {}

    result: dict[str, set[int]] = {}
    current_file: str | None = None
    right_line = 0

    for line in diff.splitlines():
        current_file, right_line = _process_line(
            line,
            current_file,
            right_line,
            result,
        )

    # Remove entries with empty line sets (e.g. deleted files)
    return {path: lines for path, lines in result.items() if lines}


def _process_line(
    line: str,
    current_file: str | None,
    right_line: int,
    result: dict[str, set[int]],
) -> tuple[str | None, int]:
    """Process a single diff line, updating result in place.

    Returns:
        Updated (current_file, right_line) tuple.
    """
    # New file header
    header_match = _DIFF_HEADER_RE.match(line)
    if header_match:
        return header_match.group(1), right_line

    # Binary file marker -- skip this file entirely
    if line.startswith("Binary files "):
        return None, right_line

    if current_file is None or _is_metadata(line):
        return current_file, right_line

    # Hunk header
    hunk_match = _HUNK_RE.match(line)
    if hunk_match:
        result.setdefault(current_file, set())
        return current_file, int(hunk_match.group(1))

    # Context line (space prefix) or addition -- valid for comments
    if line.startswith((" ", "+")):
        result.setdefault(current_file, set()).add(right_line)
        return current_file, right_line + 1

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line
