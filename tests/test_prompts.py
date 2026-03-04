"""Tests for guardrails_review.prompts module."""

from __future__ import annotations

from guardrails_review.prompts import (
    _AGENTIC_SYSTEM_PROMPT,
    _SYSTEM_PROMPT,
    _build_user_content,
    build_agentic_messages,
    build_messages,
)
from guardrails_review.types import PathInstruction, PRMetadata, ReviewConfig, ReviewThread


def _meta(title="T", body="", head_ref_oid="sha", base_ref_name="main"):
    return PRMetadata(
        title=title, body=body, head_ref_oid=head_ref_oid, base_ref_name=base_ref_name
    )


def test_system_prompt_contains_defect_categories():
    """System prompt lists defect categories and excludes style."""
    assert "Bugs" in _SYSTEM_PROMPT
    assert "Security" in _SYSTEM_PROMPT
    assert "Do NOT report" in _SYSTEM_PROMPT
    assert "Style" in _SYSTEM_PROMPT  # in the "do not" section


def test_agentic_prompt_contains_tool_instructions():
    """Agentic prompt includes tool usage instructions."""
    assert "submit_review" in _AGENTIC_SYSTEM_PROMPT
    assert "read_file" in _AGENTIC_SYSTEM_PROMPT
    assert "search_code" in _AGENTIC_SYSTEM_PROMPT


def test_build_user_content_includes_title_and_diff():
    """User content includes PR title and diff text."""
    config = ReviewConfig(model="m")
    content = _build_user_content("diff text", config, _meta(title="My PR", body="desc"))

    assert "My PR" in content
    assert "diff text" in content
    assert "desc" in content


def test_build_user_content_truncates_diff():
    """Diff is truncated to max_diff_chars."""
    config = ReviewConfig(model="m", max_diff_chars=5)
    content = _build_user_content("abcdefghij", config, _meta())

    assert "abcde" in content
    assert "abcdefghij" not in content


def test_build_user_content_with_extra_instructions():
    """Extra instructions appear before PR content."""
    config = ReviewConfig(model="m", extra_instructions="Check for SQL injection")
    content = _build_user_content("diff", config, _meta())

    assert "SQL injection" in content
    # Extra instructions should come before the diff
    assert content.index("SQL injection") < content.index("diff")


def test_build_user_content_empty_body_shows_placeholder():
    """Empty PR body shows '(no description)' placeholder."""
    config = ReviewConfig(model="m")
    content = _build_user_content("diff", config, _meta())

    assert "(no description)" in content


def test_build_user_content_missing_title_shows_untitled():
    """Empty title defaults to 'Untitled'."""
    config = ReviewConfig(model="m")
    content = _build_user_content("diff", config, _meta(title=""))

    assert "Untitled" in content


def test_build_messages_returns_two_messages():
    """build_messages returns system + user message pair."""
    config = ReviewConfig(model="m")
    messages = build_messages("diff", config, _meta())

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


def test_build_messages_system_prompt_is_oneshot():
    """build_messages uses the oneshot system prompt (not agentic)."""
    config = ReviewConfig(model="m")
    messages = build_messages("diff", config, _meta())

    assert "ONLY valid JSON" in messages[0]["content"]
    assert "tools" not in messages[0]["content"].lower()


def test_build_agentic_messages_uses_agentic_prompt():
    """build_agentic_messages uses the agentic system prompt."""
    config = ReviewConfig(model="m")
    messages = build_agentic_messages("diff", config, _meta())

    assert len(messages) == 2
    assert "tools" in messages[0]["content"].lower()
    assert "submit_review" in messages[0]["content"]


def test_build_user_content_includes_memory_context():
    """memory_context appears before PR content when provided."""
    config = ReviewConfig(model="m")
    memory_ctx = "## Known False Positives\n- [S605] urllib use"
    content = _build_user_content("diff", config, _meta(title="PR"), memory_context=memory_ctx)

    assert "urllib use" in content
    assert content.index("urllib use") < content.index("diff")


def test_build_user_content_no_memory_context_skips_section():
    """No memory section appears when memory_context is empty."""
    config = ReviewConfig(model="m")
    content = _build_user_content("diff", config, _meta())

    assert "Project Memory" not in content


def test_build_messages_passes_memory_context():
    """build_messages injects memory_context into user message."""
    config = ReviewConfig(model="m")
    messages = build_messages("diff", config, _meta(), memory_context="## Known FP\n- pattern")

    assert "pattern" in messages[1]["content"]


def test_build_agentic_messages_passes_memory_context():
    """build_agentic_messages injects memory_context into user message."""
    config = ReviewConfig(model="m")
    messages = build_agentic_messages(
        "diff", config, _meta(), memory_context="## Conventions\n- gh CLI"
    )

    assert "gh CLI" in messages[1]["content"]


def test_agentic_prompt_requires_submit_review():
    """MUST and submit_review() appear in the agentic system prompt."""
    assert "MUST" in _AGENTIC_SYSTEM_PROMPT
    assert "submit_review()" in _AGENTIC_SYSTEM_PROMPT


def test_agentic_prompt_contains_ai_defect_categories():
    """AI-specific defect categories are in the agentic system prompt."""
    assert "Hallucinated" in _AGENTIC_SYSTEM_PROMPT
    assert "idempotency" in _AGENTIC_SYSTEM_PROMPT
    assert "Hardcoded" in _AGENTIC_SYSTEM_PROMPT
    assert "Code duplication" in _AGENTIC_SYSTEM_PROMPT
    assert "Unnecessary complexity" in _AGENTIC_SYSTEM_PROMPT
    assert "last line of defense" in _AGENTIC_SYSTEM_PROMPT


def test_build_agentic_messages_injects_previous_comments():
    """ReviewThread in previous_comments -> 'Existing Unresolved' section in user msg."""
    config = ReviewConfig(model="m")
    thread = ReviewThread(
        thread_id="t1",
        path="src/foo.py",
        line=42,
        body="This is a bug",
        is_resolved=False,
        is_outdated=False,
        author="bot",
        created_at="2024-01-01",
    )
    messages = build_agentic_messages(
        "diff", config, _meta(), previous_comments=[thread]
    )

    assert "Existing Unresolved" in messages[1]["content"]
    assert "src/foo.py:42" in messages[1]["content"]


def test_build_agentic_messages_injects_matched_path_instructions():
    """Matching path glob -> 'Path-Specific Review Rules' section in user message."""
    config = ReviewConfig(
        model="m",
        path_instructions=[PathInstruction(path="*.py", instructions="Check types")],
    )
    messages = build_agentic_messages(
        "diff", config, _meta(), changed_files=["src/main.py"]
    )

    assert "Path-Specific Review Rules" in messages[1]["content"]
    assert "Check types" in messages[1]["content"]


def test_build_agentic_messages_no_path_section_when_no_match():
    """Non-matching path glob -> no 'Path-Specific' section in user message."""
    config = ReviewConfig(
        model="m",
        path_instructions=[PathInstruction(path="*.sql", instructions="Check injection")],
    )
    messages = build_agentic_messages(
        "diff", config, _meta(), changed_files=["src/main.py"]
    )

    assert "Path-Specific" not in messages[1]["content"]


def test_build_agentic_messages_globstar_path_matches():
    """Path pattern with ** (globstar) matches nested files (fnmatch normalisation)."""
    config = ReviewConfig(
        model="m",
        path_instructions=[PathInstruction(path="tests/**", instructions="Mock at boundaries")],
    )
    messages = build_agentic_messages(
        "diff", config, _meta(), changed_files=["tests/test_foo.py"]
    )

    assert "Path-Specific Review Rules" in messages[1]["content"]
    assert "Mock at boundaries" in messages[1]["content"]


def test_build_agentic_messages_empty_previous_comments():
    """Empty previous_comments list -> no 'Existing Unresolved' section."""
    config = ReviewConfig(model="m")
    messages = build_agentic_messages(
        "diff", config, _meta(), previous_comments=[]
    )

    assert "Existing Unresolved" not in messages[1]["content"]
