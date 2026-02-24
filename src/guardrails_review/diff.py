"""Parse unified diff output to extract valid line numbers for review comments.

GitHub's review API returns 422 for comments on lines outside the diff,
so we need to know exactly which right-side lines are valid targets.
"""

from __future__ import annotations

import re

_DIFF_HEADER_RE = re.compile(r"^diff --git a/.+ b/(.+)$")
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


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
    in_binary = False

    for line in diff.splitlines():
        # New file header
        header_match = _DIFF_HEADER_RE.match(line)
        if header_match:
            current_file = header_match.group(1)
            in_binary = False
            continue

        # Binary file marker -- skip this file entirely
        if line.startswith("Binary files "):
            in_binary = True
            current_file = None
            continue

        if in_binary or current_file is None:
            continue

        # Hunk header
        hunk_match = _HUNK_RE.match(line)
        if hunk_match:
            right_line = int(hunk_match.group(1))
            if current_file not in result:
                result[current_file] = set()
            continue

        # Skip metadata lines (index, ---, +++, rename, similarity, etc.)
        if (
            line.startswith("index ")
            or line.startswith("--- ")
            or line.startswith("+++ ")
            or line.startswith("new file mode")
            or line.startswith("deleted file mode")
            or line.startswith("similarity index")
            or line.startswith("rename from ")
            or line.startswith("rename to ")
            or line.startswith("old mode")
            or line.startswith("new mode")
        ):
            continue

        # No newline marker -- skip
        if line.startswith("\\ "):
            continue

        # Context line (space prefix) -- valid for comments
        if line.startswith(" "):
            if current_file is not None:
                result.setdefault(current_file, set()).add(right_line)
            right_line += 1
            continue

        # Addition -- valid for comments
        if line.startswith("+"):
            if current_file is not None:
                result.setdefault(current_file, set()).add(right_line)
            right_line += 1
            continue

        # Deletion -- only affects old file, right-side line does not advance
        if line.startswith("-"):
            continue

    # Remove entries with empty line sets (e.g. deleted files)
    return {path: lines for path, lines in result.items() if lines}
