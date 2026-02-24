"""Load and validate .guardrails-review.toml configuration."""

from __future__ import annotations

import tomllib
from pathlib import Path

from guardrails_review.types import ReviewConfig

_CONFIG_FILENAME = ".guardrails-review.toml"


def load_config(project_dir: Path | None = None) -> ReviewConfig:
    """Load ReviewConfig from .guardrails-review.toml in *project_dir*.

    Args:
        project_dir: Directory containing the config file.  Defaults to cwd.

    Returns:
        A validated ReviewConfig dataclass.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If ``model`` is missing or empty.
    """
    if project_dir is None:
        project_dir = Path.cwd()

    config_path = project_dir / _CONFIG_FILENAME

    if not config_path.exists():
        msg = f"{_CONFIG_FILENAME} not found in {project_dir}"
        raise FileNotFoundError(msg)

    with config_path.open("rb") as f:
        raw = tomllib.load(f)

    config_section = raw.get("config", {})
    model = config_section.get("model", "")

    if not model:
        msg = "'model' must be set in [config] section of " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )
