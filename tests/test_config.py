"""Tests for guardrails_review.config module."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from guardrails_review.config import load_config


def test_load_config_valid_full(tmp_path: Path) -> None:
    """All fields set in config file produces a fully populated ReviewConfig."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text(
        """\
[config]
model = "anthropic/claude-sonnet-4"

[review]
auto_approve = false
severity_threshold = "warning"
max_diff_chars = 50000
extra_instructions = "Focus on security."
"""
    )

    result = load_config(tmp_path)

    assert result.model == "anthropic/claude-sonnet-4"
    assert result.auto_approve is False
    assert result.severity_threshold == "warning"
    assert result.max_diff_chars == 50000
    assert result.extra_instructions == "Focus on security."


def test_load_config_minimal(tmp_path: Path) -> None:
    """Only model set; all other fields use ReviewConfig defaults."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text(
        """\
[config]
model = "openai/gpt-4o"
"""
    )

    result = load_config(tmp_path)

    assert result.model == "openai/gpt-4o"
    assert result.extra_instructions == ""
    assert result.auto_approve is True
    assert result.severity_threshold == "error"
    assert result.max_diff_chars == 120_000


def test_load_config_missing_file(tmp_path: Path) -> None:
    """Raises FileNotFoundError when .guardrails-review.toml does not exist."""
    with pytest.raises(FileNotFoundError, match=r"\.guardrails-review\.toml"):
        load_config(tmp_path)


def test_load_config_empty_model(tmp_path: Path) -> None:
    """Raises ValueError when model is an empty string."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text(
        """\
[config]
model = ""
"""
    )

    with pytest.raises(ValueError, match="model"):
        load_config(tmp_path)


def test_load_config_missing_model(tmp_path: Path) -> None:
    """Raises ValueError when model key is absent from [config]."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text(
        """\
[config]
"""
    )

    with pytest.raises(ValueError, match="model"):
        load_config(tmp_path)


def test_load_config_missing_config_section(tmp_path: Path) -> None:
    """Raises ValueError when [config] section is entirely absent."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text(
        """\
[review]
auto_approve = true
"""
    )

    with pytest.raises(ValueError, match="model"):
        load_config(tmp_path)
