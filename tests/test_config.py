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
max_diff_chars = 50000
extra_instructions = "Focus on security."
agentic = false
max_iterations = 3
"""
    )

    result = load_config(tmp_path)

    assert result.model == "anthropic/claude-sonnet-4"
    assert result.max_diff_chars == 50000
    assert result.extra_instructions == "Focus on security."
    assert result.agentic is False
    assert result.max_iterations == 3


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
    assert result.max_diff_chars == 120_000
    assert result.agentic is True
    assert result.max_iterations == 30


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


def test_load_config_agentic_defaults(tmp_path: Path) -> None:
    """Agentic mode defaults to True with 15 iterations when not specified."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text('[config]\nmodel = "test/m"\n')

    result = load_config(tmp_path)

    assert result.agentic is True
    assert result.max_iterations == 30


def test_load_config_ignores_removed_fields(tmp_path: Path) -> None:
    """Old configs with auto_approve/severity_threshold are silently ignored."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text(
        """\
[config]
model = "test/m"

[review]
auto_approve = false
severity_threshold = "warning"
"""
    )

    result = load_config(tmp_path)

    assert result.model == "test/m"
    assert not hasattr(result, "auto_approve")
    assert not hasattr(result, "severity_threshold")


def test_load_config_agentic_disabled(tmp_path: Path) -> None:
    """Agentic mode can be explicitly disabled."""
    config_file = tmp_path / ".guardrails-review.toml"
    config_file.write_text(
        '[config]\nmodel = "test/m"\n\n[review]\nagentic = false\nmax_iterations = 10\n'
    )

    result = load_config(tmp_path)

    assert result.agentic is False
    assert result.max_iterations == 10
