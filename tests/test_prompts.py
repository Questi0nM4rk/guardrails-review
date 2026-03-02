"""Tests for guardrails_review.prompts module."""

from __future__ import annotations

import base64
import subprocess

from guardrails_review.prompts import (
    _AGENTIC_SYSTEM_PROMPT,
    _SYSTEM_PROMPT,
    _build_user_content,
    build_agentic_messages,
    build_ci_context,
    build_messages,
)
from guardrails_review.types import PRMetadata, ReviewConfig


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
    """Agentic prompt includes tool usage instructions for new tools."""
    assert "post_comments" in _AGENTIC_SYSTEM_PROMPT
    assert "finish_review" in _AGENTIC_SYSTEM_PROMPT
    assert "read_file" in _AGENTIC_SYSTEM_PROMPT
    assert "search_code" in _AGENTIC_SYSTEM_PROMPT
    # submit_review is gone
    assert "submit_review" not in _AGENTIC_SYSTEM_PROMPT


def test_build_user_content_includes_title_and_diff():
    """User content includes PR title and diff text."""
    config = ReviewConfig(model="m")
    content = _build_user_content(
        "diff text", config, _meta(title="My PR", body="desc")
    )

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
    assert "post_comments" in messages[0]["content"]
    assert "finish_review" in messages[0]["content"]


def test_build_agentic_messages_includes_ci_context():
    """build_agentic_messages includes CI context when provided."""
    config = ReviewConfig(model="m")
    ci = "Pre-commit hooks: ruff (v0.8.0), mypy (v1.14)"
    messages = build_agentic_messages("diff", config, _meta(), ci_context=ci)

    assert "ruff" in messages[1]["content"]
    assert "Pre-commit hooks" in messages[1]["content"]


def test_build_agentic_messages_empty_ci_context():
    """build_agentic_messages excludes CI context section when empty."""
    config = ReviewConfig(model="m")
    messages = build_agentic_messages("diff", config, _meta(), ci_context="")

    assert "CI/CD" not in messages[1]["content"]


# --- build_ci_context ---


def test_build_ci_context_extracts_hooks(monkeypatch):
    """build_ci_context extracts hook IDs and revs from pre-commit config."""
    pre_commit_yaml = """\
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.14.0
    hooks:
      - id: mypy
"""
    encoded = base64.b64encode(pre_commit_yaml.encode()).decode()

    def fake_run_gh(*args, **kwargs):
        return subprocess.CompletedProcess(["gh"], 0, encoded + "\n", "")

    monkeypatch.setattr("guardrails_review.prompts.run_gh", fake_run_gh)

    result = build_ci_context("owner", "repo", "sha123")

    assert "ruff" in result
    assert "ruff-format" in result
    assert "mypy" in result
    assert "v0.8.0" in result
    assert "v1.14.0" in result


def test_build_ci_context_returns_empty_on_error(monkeypatch):
    """build_ci_context returns empty string when file fetch fails."""

    def fake_run_gh(*args, **kwargs):
        msg = "not found"
        raise RuntimeError(msg)

    monkeypatch.setattr("guardrails_review.prompts.run_gh", fake_run_gh)

    result = build_ci_context("owner", "repo", "sha123")

    assert result == ""
