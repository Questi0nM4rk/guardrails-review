"""Tests for guardrails_review.prompts module."""

from __future__ import annotations

from guardrails_review.prompts import (
    _AGENTIC_SYSTEM_PROMPT,
    _SYSTEM_PROMPT,
    _build_user_content,
    build_agentic_messages,
    build_messages,
)
from guardrails_review.types import ReviewConfig


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
    content = _build_user_content("diff text", config, {"title": "My PR", "body": "desc"})

    assert "My PR" in content
    assert "diff text" in content
    assert "desc" in content


def test_build_user_content_truncates_diff():
    """Diff is truncated to max_diff_chars."""
    config = ReviewConfig(model="m", max_diff_chars=5)
    content = _build_user_content("abcdefghij", config, {"title": "T", "body": ""})

    assert "abcde" in content
    assert "abcdefghij" not in content


def test_build_user_content_with_extra_instructions():
    """Extra instructions appear before PR content."""
    config = ReviewConfig(model="m", extra_instructions="Check for SQL injection")
    content = _build_user_content("diff", config, {"title": "T", "body": ""})

    assert "SQL injection" in content
    # Extra instructions should come before the diff
    assert content.index("SQL injection") < content.index("diff")


def test_build_user_content_empty_body_shows_placeholder():
    """Empty PR body shows '(no description)' placeholder."""
    config = ReviewConfig(model="m")
    content = _build_user_content("diff", config, {"title": "T", "body": ""})

    assert "(no description)" in content


def test_build_user_content_missing_title_shows_untitled():
    """Missing title defaults to 'Untitled'."""
    config = ReviewConfig(model="m")
    content = _build_user_content("diff", config, {})

    assert "Untitled" in content


def test_build_messages_returns_two_messages():
    """build_messages returns system + user message pair."""
    config = ReviewConfig(model="m")
    messages = build_messages("diff", config, {"title": "T", "body": ""})

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


def test_build_messages_system_prompt_is_oneshot():
    """build_messages uses the oneshot system prompt (not agentic)."""
    config = ReviewConfig(model="m")
    messages = build_messages("diff", config, {"title": "T", "body": ""})

    assert "ONLY valid JSON" in messages[0]["content"]
    assert "tools" not in messages[0]["content"].lower()


def test_build_agentic_messages_uses_agentic_prompt():
    """build_agentic_messages uses the agentic system prompt."""
    config = ReviewConfig(model="m")
    messages = build_agentic_messages("diff", config, {"title": "T", "body": ""})

    assert len(messages) == 2
    assert "tools" in messages[0]["content"].lower()
    assert "submit_review" in messages[0]["content"]
