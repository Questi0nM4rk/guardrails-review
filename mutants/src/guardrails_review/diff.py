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
from typing import Annotated
from typing import Callable
from typing import ClassVar

MutantDict = Annotated[dict[str, Callable], "Mutant"] # type: ignore


def _mutmut_trampoline(orig, mutants, call_args, call_kwargs, self_arg = None): # type: ignore
    """Forward call to original or mutated function, depending on the environment"""
    import os # type: ignore
    mutant_under_test = os.environ['MUTANT_UNDER_TEST'] # type: ignore
    if mutant_under_test == 'fail': # type: ignore
        from mutmut.__main__ import MutmutProgrammaticFailException # type: ignore
        raise MutmutProgrammaticFailException('Failed programmatically')       # type: ignore
    elif mutant_under_test == 'stats': # type: ignore
        from mutmut.__main__ import record_trampoline_hit # type: ignore
        record_trampoline_hit(orig.__module__ + '.' + orig.__name__) # type: ignore
        # (for class methods, orig is bound and thus does not need the explicit self argument)
        result = orig(*call_args, **call_kwargs) # type: ignore
        return result # type: ignore
    prefix = orig.__module__ + '.' + orig.__name__ + '__mutmut_' # type: ignore
    if not mutant_under_test.startswith(prefix): # type: ignore
        result = orig(*call_args, **call_kwargs) # type: ignore
        return result # type: ignore
    mutant_name = mutant_under_test.rpartition('.')[-1] # type: ignore
    if self_arg is not None: # type: ignore
        # call to a class method where self is not bound
        result = mutants[mutant_name](self_arg, *call_args, **call_kwargs) # type: ignore
    else:
        result = mutants[mutant_name](*call_args, **call_kwargs) # type: ignore
    return result # type: ignore


def _is_metadata(line: str) -> bool:
    args = [line]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x__is_metadata__mutmut_orig, x__is_metadata__mutmut_mutants, args, kwargs, None)


def x__is_metadata__mutmut_orig(line: str) -> bool:
    """Return True if the line is diff metadata (not content)."""
    return line.startswith(_METADATA_PREFIXES) or line.startswith("\\ ")


def x__is_metadata__mutmut_1(line: str) -> bool:
    """Return True if the line is diff metadata (not content)."""
    return line.startswith(_METADATA_PREFIXES) and line.startswith("\\ ")


def x__is_metadata__mutmut_2(line: str) -> bool:
    """Return True if the line is diff metadata (not content)."""
    return line.startswith(None) or line.startswith("\\ ")


def x__is_metadata__mutmut_3(line: str) -> bool:
    """Return True if the line is diff metadata (not content)."""
    return line.startswith(_METADATA_PREFIXES) or line.startswith(None)


def x__is_metadata__mutmut_4(line: str) -> bool:
    """Return True if the line is diff metadata (not content)."""
    return line.startswith(_METADATA_PREFIXES) or line.startswith("XX\\ XX")

x__is_metadata__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x__is_metadata__mutmut_1': x__is_metadata__mutmut_1, 
    'x__is_metadata__mutmut_2': x__is_metadata__mutmut_2, 
    'x__is_metadata__mutmut_3': x__is_metadata__mutmut_3, 
    'x__is_metadata__mutmut_4': x__is_metadata__mutmut_4
}
x__is_metadata__mutmut_orig.__name__ = 'x__is_metadata'


def parse_diff_hunks(diff: str) -> dict[str, set[int]]:
    args = [diff]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x_parse_diff_hunks__mutmut_orig, x_parse_diff_hunks__mutmut_mutants, args, kwargs, None)


def x_parse_diff_hunks__mutmut_orig(diff: str) -> dict[str, set[int]]:
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


def x_parse_diff_hunks__mutmut_1(diff: str) -> dict[str, set[int]]:
    """Parse unified diff and return valid right-side line numbers per file.

    Args:
        diff: Full unified diff output (e.g. from ``gh pr diff --patch``).

    Returns:
        Mapping of file path to set of right-side line numbers where review
        comments can be placed (context lines and additions).
    """
    if diff:
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


def x_parse_diff_hunks__mutmut_2(diff: str) -> dict[str, set[int]]:
    """Parse unified diff and return valid right-side line numbers per file.

    Args:
        diff: Full unified diff output (e.g. from ``gh pr diff --patch``).

    Returns:
        Mapping of file path to set of right-side line numbers where review
        comments can be placed (context lines and additions).
    """
    if not diff:
        return {}

    result: dict[str, set[int]] = None
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


def x_parse_diff_hunks__mutmut_3(diff: str) -> dict[str, set[int]]:
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
    current_file: str | None = ""
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


def x_parse_diff_hunks__mutmut_4(diff: str) -> dict[str, set[int]]:
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
    right_line = None

    for line in diff.splitlines():
        current_file, right_line = _process_line(
            line,
            current_file,
            right_line,
            result,
        )

    # Remove entries with empty line sets (e.g. deleted files)
    return {path: lines for path, lines in result.items() if lines}


def x_parse_diff_hunks__mutmut_5(diff: str) -> dict[str, set[int]]:
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
    right_line = 1

    for line in diff.splitlines():
        current_file, right_line = _process_line(
            line,
            current_file,
            right_line,
            result,
        )

    # Remove entries with empty line sets (e.g. deleted files)
    return {path: lines for path, lines in result.items() if lines}


def x_parse_diff_hunks__mutmut_6(diff: str) -> dict[str, set[int]]:
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
        current_file, right_line = None

    # Remove entries with empty line sets (e.g. deleted files)
    return {path: lines for path, lines in result.items() if lines}


def x_parse_diff_hunks__mutmut_7(diff: str) -> dict[str, set[int]]:
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
            None,
            current_file,
            right_line,
            result,
        )

    # Remove entries with empty line sets (e.g. deleted files)
    return {path: lines for path, lines in result.items() if lines}


def x_parse_diff_hunks__mutmut_8(diff: str) -> dict[str, set[int]]:
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
            None,
            right_line,
            result,
        )

    # Remove entries with empty line sets (e.g. deleted files)
    return {path: lines for path, lines in result.items() if lines}


def x_parse_diff_hunks__mutmut_9(diff: str) -> dict[str, set[int]]:
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
            None,
            result,
        )

    # Remove entries with empty line sets (e.g. deleted files)
    return {path: lines for path, lines in result.items() if lines}


def x_parse_diff_hunks__mutmut_10(diff: str) -> dict[str, set[int]]:
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
            None,
        )

    # Remove entries with empty line sets (e.g. deleted files)
    return {path: lines for path, lines in result.items() if lines}


def x_parse_diff_hunks__mutmut_11(diff: str) -> dict[str, set[int]]:
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
            current_file,
            right_line,
            result,
        )

    # Remove entries with empty line sets (e.g. deleted files)
    return {path: lines for path, lines in result.items() if lines}


def x_parse_diff_hunks__mutmut_12(diff: str) -> dict[str, set[int]]:
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
            right_line,
            result,
        )

    # Remove entries with empty line sets (e.g. deleted files)
    return {path: lines for path, lines in result.items() if lines}


def x_parse_diff_hunks__mutmut_13(diff: str) -> dict[str, set[int]]:
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
            result,
        )

    # Remove entries with empty line sets (e.g. deleted files)
    return {path: lines for path, lines in result.items() if lines}


def x_parse_diff_hunks__mutmut_14(diff: str) -> dict[str, set[int]]:
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
            )

    # Remove entries with empty line sets (e.g. deleted files)
    return {path: lines for path, lines in result.items() if lines}

x_parse_diff_hunks__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x_parse_diff_hunks__mutmut_1': x_parse_diff_hunks__mutmut_1, 
    'x_parse_diff_hunks__mutmut_2': x_parse_diff_hunks__mutmut_2, 
    'x_parse_diff_hunks__mutmut_3': x_parse_diff_hunks__mutmut_3, 
    'x_parse_diff_hunks__mutmut_4': x_parse_diff_hunks__mutmut_4, 
    'x_parse_diff_hunks__mutmut_5': x_parse_diff_hunks__mutmut_5, 
    'x_parse_diff_hunks__mutmut_6': x_parse_diff_hunks__mutmut_6, 
    'x_parse_diff_hunks__mutmut_7': x_parse_diff_hunks__mutmut_7, 
    'x_parse_diff_hunks__mutmut_8': x_parse_diff_hunks__mutmut_8, 
    'x_parse_diff_hunks__mutmut_9': x_parse_diff_hunks__mutmut_9, 
    'x_parse_diff_hunks__mutmut_10': x_parse_diff_hunks__mutmut_10, 
    'x_parse_diff_hunks__mutmut_11': x_parse_diff_hunks__mutmut_11, 
    'x_parse_diff_hunks__mutmut_12': x_parse_diff_hunks__mutmut_12, 
    'x_parse_diff_hunks__mutmut_13': x_parse_diff_hunks__mutmut_13, 
    'x_parse_diff_hunks__mutmut_14': x_parse_diff_hunks__mutmut_14
}
x_parse_diff_hunks__mutmut_orig.__name__ = 'x_parse_diff_hunks'


def _process_line(
    line: str,
    current_file: str | None,
    right_line: int,
    result: dict[str, set[int]],
) -> tuple[str | None, int]:
    args = [line, current_file, right_line, result]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x__process_line__mutmut_orig, x__process_line__mutmut_mutants, args, kwargs, None)


def x__process_line__mutmut_orig(
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


def x__process_line__mutmut_1(
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
    header_match = None
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


def x__process_line__mutmut_2(
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
    header_match = _DIFF_HEADER_RE.match(None)
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


def x__process_line__mutmut_3(
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
        return header_match.group(None), right_line

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


def x__process_line__mutmut_4(
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
        return header_match.group(2), right_line

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


def x__process_line__mutmut_5(
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
    if line.startswith(None):
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


def x__process_line__mutmut_6(
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
    if line.startswith("XXBinary files XX"):
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


def x__process_line__mutmut_7(
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
    if line.startswith("binary files "):
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


def x__process_line__mutmut_8(
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
    if line.startswith("BINARY FILES "):
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


def x__process_line__mutmut_9(
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

    if current_file is None and _is_metadata(line):
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


def x__process_line__mutmut_10(
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

    if current_file is not None or _is_metadata(line):
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


def x__process_line__mutmut_11(
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

    if current_file is None or _is_metadata(None):
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


def x__process_line__mutmut_12(
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
    hunk_match = None
    if hunk_match:
        result.setdefault(current_file, set())
        return current_file, int(hunk_match.group(1))

    # Context line (space prefix) or addition -- valid for comments
    if line.startswith((" ", "+")):
        result.setdefault(current_file, set()).add(right_line)
        return current_file, right_line + 1

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line


def x__process_line__mutmut_13(
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
    hunk_match = _HUNK_RE.match(None)
    if hunk_match:
        result.setdefault(current_file, set())
        return current_file, int(hunk_match.group(1))

    # Context line (space prefix) or addition -- valid for comments
    if line.startswith((" ", "+")):
        result.setdefault(current_file, set()).add(right_line)
        return current_file, right_line + 1

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line


def x__process_line__mutmut_14(
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
        result.setdefault(None, set())
        return current_file, int(hunk_match.group(1))

    # Context line (space prefix) or addition -- valid for comments
    if line.startswith((" ", "+")):
        result.setdefault(current_file, set()).add(right_line)
        return current_file, right_line + 1

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line


def x__process_line__mutmut_15(
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
        result.setdefault(current_file, None)
        return current_file, int(hunk_match.group(1))

    # Context line (space prefix) or addition -- valid for comments
    if line.startswith((" ", "+")):
        result.setdefault(current_file, set()).add(right_line)
        return current_file, right_line + 1

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line


def x__process_line__mutmut_16(
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
        result.setdefault(set())
        return current_file, int(hunk_match.group(1))

    # Context line (space prefix) or addition -- valid for comments
    if line.startswith((" ", "+")):
        result.setdefault(current_file, set()).add(right_line)
        return current_file, right_line + 1

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line


def x__process_line__mutmut_17(
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
        result.setdefault(current_file, )
        return current_file, int(hunk_match.group(1))

    # Context line (space prefix) or addition -- valid for comments
    if line.startswith((" ", "+")):
        result.setdefault(current_file, set()).add(right_line)
        return current_file, right_line + 1

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line


def x__process_line__mutmut_18(
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
        return current_file, int(None)

    # Context line (space prefix) or addition -- valid for comments
    if line.startswith((" ", "+")):
        result.setdefault(current_file, set()).add(right_line)
        return current_file, right_line + 1

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line


def x__process_line__mutmut_19(
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
        return current_file, int(hunk_match.group(None))

    # Context line (space prefix) or addition -- valid for comments
    if line.startswith((" ", "+")):
        result.setdefault(current_file, set()).add(right_line)
        return current_file, right_line + 1

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line


def x__process_line__mutmut_20(
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
        return current_file, int(hunk_match.group(2))

    # Context line (space prefix) or addition -- valid for comments
    if line.startswith((" ", "+")):
        result.setdefault(current_file, set()).add(right_line)
        return current_file, right_line + 1

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line


def x__process_line__mutmut_21(
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
    if line.startswith(None):
        result.setdefault(current_file, set()).add(right_line)
        return current_file, right_line + 1

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line


def x__process_line__mutmut_22(
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
    if line.startswith(("XX XX", "+")):
        result.setdefault(current_file, set()).add(right_line)
        return current_file, right_line + 1

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line


def x__process_line__mutmut_23(
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
    if line.startswith((" ", "XX+XX")):
        result.setdefault(current_file, set()).add(right_line)
        return current_file, right_line + 1

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line


def x__process_line__mutmut_24(
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
        result.setdefault(current_file, set()).add(None)
        return current_file, right_line + 1

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line


def x__process_line__mutmut_25(
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
        result.setdefault(None, set()).add(right_line)
        return current_file, right_line + 1

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line


def x__process_line__mutmut_26(
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
        result.setdefault(current_file, None).add(right_line)
        return current_file, right_line + 1

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line


def x__process_line__mutmut_27(
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
        result.setdefault(set()).add(right_line)
        return current_file, right_line + 1

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line


def x__process_line__mutmut_28(
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
        result.setdefault(current_file, ).add(right_line)
        return current_file, right_line + 1

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line


def x__process_line__mutmut_29(
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
        return current_file, right_line - 1

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line


def x__process_line__mutmut_30(
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
        return current_file, right_line + 2

    # Deletion -- only affects old file, right-side line does not advance
    return current_file, right_line

x__process_line__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x__process_line__mutmut_1': x__process_line__mutmut_1, 
    'x__process_line__mutmut_2': x__process_line__mutmut_2, 
    'x__process_line__mutmut_3': x__process_line__mutmut_3, 
    'x__process_line__mutmut_4': x__process_line__mutmut_4, 
    'x__process_line__mutmut_5': x__process_line__mutmut_5, 
    'x__process_line__mutmut_6': x__process_line__mutmut_6, 
    'x__process_line__mutmut_7': x__process_line__mutmut_7, 
    'x__process_line__mutmut_8': x__process_line__mutmut_8, 
    'x__process_line__mutmut_9': x__process_line__mutmut_9, 
    'x__process_line__mutmut_10': x__process_line__mutmut_10, 
    'x__process_line__mutmut_11': x__process_line__mutmut_11, 
    'x__process_line__mutmut_12': x__process_line__mutmut_12, 
    'x__process_line__mutmut_13': x__process_line__mutmut_13, 
    'x__process_line__mutmut_14': x__process_line__mutmut_14, 
    'x__process_line__mutmut_15': x__process_line__mutmut_15, 
    'x__process_line__mutmut_16': x__process_line__mutmut_16, 
    'x__process_line__mutmut_17': x__process_line__mutmut_17, 
    'x__process_line__mutmut_18': x__process_line__mutmut_18, 
    'x__process_line__mutmut_19': x__process_line__mutmut_19, 
    'x__process_line__mutmut_20': x__process_line__mutmut_20, 
    'x__process_line__mutmut_21': x__process_line__mutmut_21, 
    'x__process_line__mutmut_22': x__process_line__mutmut_22, 
    'x__process_line__mutmut_23': x__process_line__mutmut_23, 
    'x__process_line__mutmut_24': x__process_line__mutmut_24, 
    'x__process_line__mutmut_25': x__process_line__mutmut_25, 
    'x__process_line__mutmut_26': x__process_line__mutmut_26, 
    'x__process_line__mutmut_27': x__process_line__mutmut_27, 
    'x__process_line__mutmut_28': x__process_line__mutmut_28, 
    'x__process_line__mutmut_29': x__process_line__mutmut_29, 
    'x__process_line__mutmut_30': x__process_line__mutmut_30
}
x__process_line__mutmut_orig.__name__ = 'x__process_line'
