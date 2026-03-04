"""Tests for diff parsing module."""

from __future__ import annotations

from guardrails_review.diff import format_diff_with_lines, parse_diff_hunks


def test_parse_single_hunk() -> None:
    """Single file, single hunk with additions, deletions, and context."""
    diff = """\
diff --git a/src/main.py b/src/main.py
index abc1234..def5678 100644
--- a/src/main.py
+++ b/src/main.py
@@ -10,6 +10,7 @@ def existing():
     keep1
     keep2
+    new_line
     keep3
-    old_line
     keep4
"""
    result = parse_diff_hunks(diff)
    assert "src/main.py" in result
    lines = result["src/main.py"]
    # Right-side lines: 10-11 context, 12 added, 13-14 context (deletion skipped)
    assert lines == {10, 11, 12, 13, 14}


def test_parse_multiple_hunks() -> None:
    """Single file with two separate hunks."""
    diff = """\
diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1,3 +1,4 @@
 line1
+added_top
 line2
 line3
@@ -20,3 +21,4 @@ def func():
 line20
 line21
+added_bottom
 line22
"""
    result = parse_diff_hunks(diff)
    assert "app.py" in result
    lines = result["app.py"]
    # Hunk 1: context 1, added 2, context 3, 4
    assert {1, 2, 3, 4}.issubset(lines)
    # Hunk 2: context 21, 22, added 23, context 24
    assert {21, 22, 23, 24}.issubset(lines)


def test_parse_multiple_files() -> None:
    """Two different files in one diff output."""
    diff = """\
diff --git a/foo.py b/foo.py
index aaa..bbb 100644
--- a/foo.py
+++ b/foo.py
@@ -1,2 +1,3 @@
 existing
+new_in_foo
 end
diff --git a/bar.py b/bar.py
index ccc..ddd 100644
--- a/bar.py
+++ b/bar.py
@@ -5,2 +5,3 @@ class Bar:
     old
+    new_in_bar
     end
"""
    result = parse_diff_hunks(diff)
    assert "foo.py" in result
    assert "bar.py" in result
    assert result["foo.py"] == {1, 2, 3}
    assert result["bar.py"] == {5, 6, 7}


def test_parse_new_file() -> None:
    """Newly created file -- all lines are additions."""
    diff = """\
diff --git a/new_file.py b/new_file.py
new file mode 100644
index 0000000..abc1234
--- /dev/null
+++ b/new_file.py
@@ -0,0 +1,3 @@
+line1
+line2
+line3
"""
    result = parse_diff_hunks(diff)
    assert "new_file.py" in result
    assert result["new_file.py"] == {1, 2, 3}


def test_parse_deleted_file() -> None:
    """Deleted file -- no valid right-side lines."""
    diff = """\
diff --git a/removed.py b/removed.py
deleted file mode 100644
index abc1234..0000000
--- a/removed.py
+++ /dev/null
@@ -1,3 +0,0 @@
-line1
-line2
-line3
"""
    result = parse_diff_hunks(diff)
    # Deleted file should have no valid lines (or not appear at all)
    assert result.get("removed.py", set()) == set()


def test_parse_context_lines_are_valid() -> None:
    """Context lines (space-prefixed) must be included as valid comment targets."""
    diff = """\
diff --git a/ctx.py b/ctx.py
index aaa..bbb 100644
--- a/ctx.py
+++ b/ctx.py
@@ -5,5 +5,6 @@ def func():
     ctx1
     ctx2
+    added
     ctx3
     ctx4
     ctx5
"""
    result = parse_diff_hunks(diff)
    # All context and added lines are valid
    assert result["ctx.py"] == {5, 6, 7, 8, 9, 10}


def test_parse_empty_diff() -> None:
    """Empty string returns empty dict."""
    assert parse_diff_hunks("") == {}


def test_parse_no_newline_marker() -> None:
    r"""Lines with '\ No newline at end of file' are skipped."""
    diff = """\
diff --git a/no_nl.py b/no_nl.py
index aaa..bbb 100644
--- a/no_nl.py
+++ b/no_nl.py
@@ -1,2 +1,2 @@
 unchanged
-old_last
+new_last
\\ No newline at end of file
"""
    result = parse_diff_hunks(diff)
    assert result["no_nl.py"] == {1, 2}


def test_parse_renamed_file() -> None:
    """Renamed file uses the b/ path (new name)."""
    diff = """\
diff --git a/old_name.py b/new_name.py
similarity index 90%
rename from old_name.py
rename to new_name.py
index aaa..bbb 100644
--- a/old_name.py
+++ b/new_name.py
@@ -1,3 +1,4 @@
 line1
+inserted
 line2
 line3
"""
    result = parse_diff_hunks(diff)
    assert "old_name.py" not in result
    assert "new_name.py" in result
    assert result["new_name.py"] == {1, 2, 3, 4}


def test_parse_binary_file_skipped() -> None:
    """Binary files should be skipped entirely."""
    diff = """\
diff --git a/image.png b/image.png
new file mode 100644
index 0000000..abc1234
Binary files /dev/null and b/image.png differ
diff --git a/code.py b/code.py
index aaa..bbb 100644
--- a/code.py
+++ b/code.py
@@ -1,2 +1,3 @@
 line1
+added
 line2
"""
    result = parse_diff_hunks(diff)
    assert "image.png" not in result
    assert "code.py" in result
    assert result["code.py"] == {1, 2, 3}


def test_parse_binary_between_text_files() -> None:
    """Binary file between two text files should not leak lines into adjacent files."""
    diff = """\
diff --git a/first.py b/first.py
index aaa..bbb 100644
--- a/first.py
+++ b/first.py
@@ -1,2 +1,3 @@
 a
+b
 c
diff --git a/image.png b/image.png
index aaa..bbb 100644
Binary files a/image.png and b/image.png differ
diff --git a/second.py b/second.py
index ccc..ddd 100644
--- a/second.py
+++ b/second.py
@@ -1,2 +1,3 @@
 x
+y
 z
"""
    result = parse_diff_hunks(diff)
    assert "image.png" not in result
    assert result["first.py"] == {1, 2, 3}
    assert result["second.py"] == {1, 2, 3}
    # Only expected files appear in result
    assert set(result.keys()) == {"first.py", "second.py"}


def test_parse_result_keys_exact() -> None:
    """Result dict contains only the expected file keys, nothing extra."""
    diff = """\
diff --git a/only.py b/only.py
index aaa..bbb 100644
--- a/only.py
+++ b/only.py
@@ -1,2 +1,3 @@
 line1
+added
 line2
"""
    result = parse_diff_hunks(diff)
    assert list(result.keys()) == ["only.py"]


def test_format_diff_with_lines_adds_line_numbers() -> None:
    """Addition lines get LINE_N: prefix with correct right-side line number."""
    diff = """\
diff --git a/src/foo.py b/src/foo.py
index aaa..bbb 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,2 +1,3 @@
 context
+new line
 end
"""
    result = format_diff_with_lines(diff)
    assert "+LINE_2: new line" in result


def test_format_diff_with_lines_context_lines_numbered() -> None:
    """Context lines (space prefix) get LINE_N: prefix."""
    diff = """\
diff --git a/src/foo.py b/src/foo.py
index aaa..bbb 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,2 +1,3 @@
 context
+new line
 end
"""
    result = format_diff_with_lines(diff)
    assert " LINE_1: context" in result
    assert " LINE_3: end" in result


def test_format_diff_with_lines_deletions_unchanged() -> None:
    """Deletion lines (-) are output unchanged with no LINE_N prefix."""
    diff = """\
diff --git a/src/foo.py b/src/foo.py
index aaa..bbb 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,2 @@
 keep
-deleted line
 other
"""
    result = format_diff_with_lines(diff)
    assert "-deleted line" in result
    assert "LINE" not in result.splitlines()[result.splitlines().index("-deleted line")]


def test_format_diff_with_lines_headers_unchanged() -> None:
    """diff --git and @@ header lines are output unchanged."""
    diff = """\
diff --git a/src/foo.py b/src/foo.py
index aaa..bbb 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,1 +1,1 @@
 same
"""
    result = format_diff_with_lines(diff)
    assert "diff --git a/src/foo.py b/src/foo.py" in result
    assert "@@ -1,1 +1,1 @@" in result


def test_format_diff_with_lines_multiple_hunks_resets_counter() -> None:
    """Second hunk starts numbering at its own right-side start line."""
    diff = """\
diff --git a/app.py b/app.py
index aaa..bbb 100644
--- a/app.py
+++ b/app.py
@@ -1,1 +1,1 @@
 first
@@ -50,1 +50,2 @@
 fifty
+fifty one
"""
    result = format_diff_with_lines(diff)
    assert " LINE_1: first" in result
    assert " LINE_50: fifty" in result
    assert "+LINE_51: fifty one" in result


def test_format_diff_with_lines_empty_string() -> None:
    """Empty diff string returns empty string."""
    assert format_diff_with_lines("") == ""


def test_format_diff_with_lines_pure_deletion() -> None:
    """Pure deletion diff produces no LINE_N: prefixes — deletion lines are unchanged."""
    diff = (
        "diff --git a/removed.py b/removed.py\n"
        "deleted file mode 100644\n"
        "--- a/removed.py\n"
        "+++ /dev/null\n"
        "@@ -1,3 +0,0 @@\n"
        "-line1\n"
        "-line2\n"
        "-line3\n"
    )
    result = format_diff_with_lines(diff)
    assert "LINE_" not in result
    assert "-line1" in result
    assert "-line2" in result
    assert "-line3" in result


def test_parse_no_newline_marker_excluded_from_line_set() -> None:
    r"""The '\ No newline at end of file' marker must not appear in valid lines.

    Verifies the exact count so the marker is provably excluded.
    """
    diff = """\
diff --git a/no_nl.py b/no_nl.py
index aaa..bbb 100644
--- a/no_nl.py
+++ b/no_nl.py
@@ -1,2 +1,2 @@
 unchanged
-old_last
+new_last
\\ No newline at end of file
"""
    result = parse_diff_hunks(diff)
    # Exactly 2 lines: context "unchanged" at 1, addition "new_last" at 2
    assert result["no_nl.py"] == {1, 2}
    assert len(result["no_nl.py"]) == 2
