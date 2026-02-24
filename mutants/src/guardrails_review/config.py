"""Load and validate .guardrails-review.toml configuration."""

from __future__ import annotations

import tomllib
from pathlib import Path

from guardrails_review.types import ReviewConfig

_CONFIG_FILENAME = ".guardrails-review.toml"
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


def load_config(project_dir: Path | None = None) -> ReviewConfig:
    args = [project_dir]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x_load_config__mutmut_orig, x_load_config__mutmut_mutants, args, kwargs, None)


def x_load_config__mutmut_orig(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_1(project_dir: Path | None = None) -> ReviewConfig:
    """Load ReviewConfig from .guardrails-review.toml in *project_dir*.

    Args:
        project_dir: Directory containing the config file.  Defaults to cwd.

    Returns:
        A validated ReviewConfig dataclass.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If ``model`` is missing or empty.
    """
    if project_dir is not None:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_2(project_dir: Path | None = None) -> ReviewConfig:
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
        project_dir = None

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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_3(project_dir: Path | None = None) -> ReviewConfig:
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

    config_path = None

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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_4(project_dir: Path | None = None) -> ReviewConfig:
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

    config_path = project_dir * _CONFIG_FILENAME

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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_5(project_dir: Path | None = None) -> ReviewConfig:
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

    if config_path.exists():
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_6(project_dir: Path | None = None) -> ReviewConfig:
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
        msg = None
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_7(project_dir: Path | None = None) -> ReviewConfig:
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
        raise FileNotFoundError(None)

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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_8(project_dir: Path | None = None) -> ReviewConfig:
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

    with config_path.open(None) as f:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_9(project_dir: Path | None = None) -> ReviewConfig:
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

    with config_path.open("XXrbXX") as f:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_10(project_dir: Path | None = None) -> ReviewConfig:
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

    with config_path.open("RB") as f:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_11(project_dir: Path | None = None) -> ReviewConfig:
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
        raw = None

    config_section = raw.get("config", {})
    model = config_section.get("model", "")

    if not model:
        msg = "'model' must be set in [config] section of " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_12(project_dir: Path | None = None) -> ReviewConfig:
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
        raw = tomllib.load(None)

    config_section = raw.get("config", {})
    model = config_section.get("model", "")

    if not model:
        msg = "'model' must be set in [config] section of " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_13(project_dir: Path | None = None) -> ReviewConfig:
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

    config_section = None
    model = config_section.get("model", "")

    if not model:
        msg = "'model' must be set in [config] section of " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_14(project_dir: Path | None = None) -> ReviewConfig:
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

    config_section = raw.get(None, {})
    model = config_section.get("model", "")

    if not model:
        msg = "'model' must be set in [config] section of " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_15(project_dir: Path | None = None) -> ReviewConfig:
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

    config_section = raw.get("config", None)
    model = config_section.get("model", "")

    if not model:
        msg = "'model' must be set in [config] section of " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_16(project_dir: Path | None = None) -> ReviewConfig:
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

    config_section = raw.get({})
    model = config_section.get("model", "")

    if not model:
        msg = "'model' must be set in [config] section of " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_17(project_dir: Path | None = None) -> ReviewConfig:
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

    config_section = raw.get("config", )
    model = config_section.get("model", "")

    if not model:
        msg = "'model' must be set in [config] section of " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_18(project_dir: Path | None = None) -> ReviewConfig:
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

    config_section = raw.get("XXconfigXX", {})
    model = config_section.get("model", "")

    if not model:
        msg = "'model' must be set in [config] section of " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_19(project_dir: Path | None = None) -> ReviewConfig:
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

    config_section = raw.get("CONFIG", {})
    model = config_section.get("model", "")

    if not model:
        msg = "'model' must be set in [config] section of " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_20(project_dir: Path | None = None) -> ReviewConfig:
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
    model = None

    if not model:
        msg = "'model' must be set in [config] section of " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_21(project_dir: Path | None = None) -> ReviewConfig:
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
    model = config_section.get(None, "")

    if not model:
        msg = "'model' must be set in [config] section of " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_22(project_dir: Path | None = None) -> ReviewConfig:
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
    model = config_section.get("model", None)

    if not model:
        msg = "'model' must be set in [config] section of " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_23(project_dir: Path | None = None) -> ReviewConfig:
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
    model = config_section.get("")

    if not model:
        msg = "'model' must be set in [config] section of " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_24(project_dir: Path | None = None) -> ReviewConfig:
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
    model = config_section.get("model", )

    if not model:
        msg = "'model' must be set in [config] section of " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_25(project_dir: Path | None = None) -> ReviewConfig:
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
    model = config_section.get("XXmodelXX", "")

    if not model:
        msg = "'model' must be set in [config] section of " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_26(project_dir: Path | None = None) -> ReviewConfig:
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
    model = config_section.get("MODEL", "")

    if not model:
        msg = "'model' must be set in [config] section of " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_27(project_dir: Path | None = None) -> ReviewConfig:
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
    model = config_section.get("model", "XXXX")

    if not model:
        msg = "'model' must be set in [config] section of " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_28(project_dir: Path | None = None) -> ReviewConfig:
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

    if model:
        msg = "'model' must be set in [config] section of " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_29(project_dir: Path | None = None) -> ReviewConfig:
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
        msg = None
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_30(project_dir: Path | None = None) -> ReviewConfig:
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
        msg = "'model' must be set in [config] section of " - _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_31(project_dir: Path | None = None) -> ReviewConfig:
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
        msg = "XX'model' must be set in [config] section of XX" + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_32(project_dir: Path | None = None) -> ReviewConfig:
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
        msg = "'MODEL' MUST BE SET IN [CONFIG] SECTION OF " + _CONFIG_FILENAME
        raise ValueError(msg)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_33(project_dir: Path | None = None) -> ReviewConfig:
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
        raise ValueError(None)

    review_section = raw.get("review", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_34(project_dir: Path | None = None) -> ReviewConfig:
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

    review_section = None

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_35(project_dir: Path | None = None) -> ReviewConfig:
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

    review_section = raw.get(None, {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_36(project_dir: Path | None = None) -> ReviewConfig:
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

    review_section = raw.get("review", None)

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_37(project_dir: Path | None = None) -> ReviewConfig:
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

    review_section = raw.get({})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_38(project_dir: Path | None = None) -> ReviewConfig:
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

    review_section = raw.get("review", )

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_39(project_dir: Path | None = None) -> ReviewConfig:
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

    review_section = raw.get("XXreviewXX", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_40(project_dir: Path | None = None) -> ReviewConfig:
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

    review_section = raw.get("REVIEW", {})

    return ReviewConfig(
        model=model,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_41(project_dir: Path | None = None) -> ReviewConfig:
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
        model=None,
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_42(project_dir: Path | None = None) -> ReviewConfig:
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
        extra_instructions=None,
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_43(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=None,
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_44(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=None,
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_45(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=None,
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_46(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=None,
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_47(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=None,
    )


def x_load_config__mutmut_48(project_dir: Path | None = None) -> ReviewConfig:
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
        extra_instructions=review_section.get("extra_instructions", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_49(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_50(project_dir: Path | None = None) -> ReviewConfig:
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
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_51(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_52(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_53(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_54(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        )


def x_load_config__mutmut_55(project_dir: Path | None = None) -> ReviewConfig:
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
        extra_instructions=review_section.get(None, ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_56(project_dir: Path | None = None) -> ReviewConfig:
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
        extra_instructions=review_section.get("extra_instructions", None),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_57(project_dir: Path | None = None) -> ReviewConfig:
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
        extra_instructions=review_section.get(""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_58(project_dir: Path | None = None) -> ReviewConfig:
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
        extra_instructions=review_section.get("extra_instructions", ),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_59(project_dir: Path | None = None) -> ReviewConfig:
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
        extra_instructions=review_section.get("XXextra_instructionsXX", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_60(project_dir: Path | None = None) -> ReviewConfig:
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
        extra_instructions=review_section.get("EXTRA_INSTRUCTIONS", ""),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_61(project_dir: Path | None = None) -> ReviewConfig:
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
        extra_instructions=review_section.get("extra_instructions", "XXXX"),
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_62(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get(None, True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_63(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", None),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_64(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get(True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_65(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", ),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_66(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("XXauto_approveXX", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_67(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("AUTO_APPROVE", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_68(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", False),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_69(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get(None, "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_70(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", None),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_71(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_72(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", ),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_73(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("XXseverity_thresholdXX", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_74(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("SEVERITY_THRESHOLD", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_75(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "XXerrorXX"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_76(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "ERROR"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_77(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get(None, 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_78(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", None),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_79(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get(120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_80(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", ),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_81(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("XXmax_diff_charsXX", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_82(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("MAX_DIFF_CHARS", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_83(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120001),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_84(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get(None, True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_85(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", None),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_86(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get(True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_87(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", ),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_88(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("XXagenticXX", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_89(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("AGENTIC", True),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_90(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", False),
        max_iterations=review_section.get("max_iterations", 5),
    )


def x_load_config__mutmut_91(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get(None, 5),
    )


def x_load_config__mutmut_92(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", None),
    )


def x_load_config__mutmut_93(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get(5),
    )


def x_load_config__mutmut_94(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", ),
    )


def x_load_config__mutmut_95(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("XXmax_iterationsXX", 5),
    )


def x_load_config__mutmut_96(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("MAX_ITERATIONS", 5),
    )


def x_load_config__mutmut_97(project_dir: Path | None = None) -> ReviewConfig:
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
        auto_approve=review_section.get("auto_approve", True),
        severity_threshold=review_section.get("severity_threshold", "error"),
        max_diff_chars=review_section.get("max_diff_chars", 120_000),
        agentic=review_section.get("agentic", True),
        max_iterations=review_section.get("max_iterations", 6),
    )

x_load_config__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x_load_config__mutmut_1': x_load_config__mutmut_1, 
    'x_load_config__mutmut_2': x_load_config__mutmut_2, 
    'x_load_config__mutmut_3': x_load_config__mutmut_3, 
    'x_load_config__mutmut_4': x_load_config__mutmut_4, 
    'x_load_config__mutmut_5': x_load_config__mutmut_5, 
    'x_load_config__mutmut_6': x_load_config__mutmut_6, 
    'x_load_config__mutmut_7': x_load_config__mutmut_7, 
    'x_load_config__mutmut_8': x_load_config__mutmut_8, 
    'x_load_config__mutmut_9': x_load_config__mutmut_9, 
    'x_load_config__mutmut_10': x_load_config__mutmut_10, 
    'x_load_config__mutmut_11': x_load_config__mutmut_11, 
    'x_load_config__mutmut_12': x_load_config__mutmut_12, 
    'x_load_config__mutmut_13': x_load_config__mutmut_13, 
    'x_load_config__mutmut_14': x_load_config__mutmut_14, 
    'x_load_config__mutmut_15': x_load_config__mutmut_15, 
    'x_load_config__mutmut_16': x_load_config__mutmut_16, 
    'x_load_config__mutmut_17': x_load_config__mutmut_17, 
    'x_load_config__mutmut_18': x_load_config__mutmut_18, 
    'x_load_config__mutmut_19': x_load_config__mutmut_19, 
    'x_load_config__mutmut_20': x_load_config__mutmut_20, 
    'x_load_config__mutmut_21': x_load_config__mutmut_21, 
    'x_load_config__mutmut_22': x_load_config__mutmut_22, 
    'x_load_config__mutmut_23': x_load_config__mutmut_23, 
    'x_load_config__mutmut_24': x_load_config__mutmut_24, 
    'x_load_config__mutmut_25': x_load_config__mutmut_25, 
    'x_load_config__mutmut_26': x_load_config__mutmut_26, 
    'x_load_config__mutmut_27': x_load_config__mutmut_27, 
    'x_load_config__mutmut_28': x_load_config__mutmut_28, 
    'x_load_config__mutmut_29': x_load_config__mutmut_29, 
    'x_load_config__mutmut_30': x_load_config__mutmut_30, 
    'x_load_config__mutmut_31': x_load_config__mutmut_31, 
    'x_load_config__mutmut_32': x_load_config__mutmut_32, 
    'x_load_config__mutmut_33': x_load_config__mutmut_33, 
    'x_load_config__mutmut_34': x_load_config__mutmut_34, 
    'x_load_config__mutmut_35': x_load_config__mutmut_35, 
    'x_load_config__mutmut_36': x_load_config__mutmut_36, 
    'x_load_config__mutmut_37': x_load_config__mutmut_37, 
    'x_load_config__mutmut_38': x_load_config__mutmut_38, 
    'x_load_config__mutmut_39': x_load_config__mutmut_39, 
    'x_load_config__mutmut_40': x_load_config__mutmut_40, 
    'x_load_config__mutmut_41': x_load_config__mutmut_41, 
    'x_load_config__mutmut_42': x_load_config__mutmut_42, 
    'x_load_config__mutmut_43': x_load_config__mutmut_43, 
    'x_load_config__mutmut_44': x_load_config__mutmut_44, 
    'x_load_config__mutmut_45': x_load_config__mutmut_45, 
    'x_load_config__mutmut_46': x_load_config__mutmut_46, 
    'x_load_config__mutmut_47': x_load_config__mutmut_47, 
    'x_load_config__mutmut_48': x_load_config__mutmut_48, 
    'x_load_config__mutmut_49': x_load_config__mutmut_49, 
    'x_load_config__mutmut_50': x_load_config__mutmut_50, 
    'x_load_config__mutmut_51': x_load_config__mutmut_51, 
    'x_load_config__mutmut_52': x_load_config__mutmut_52, 
    'x_load_config__mutmut_53': x_load_config__mutmut_53, 
    'x_load_config__mutmut_54': x_load_config__mutmut_54, 
    'x_load_config__mutmut_55': x_load_config__mutmut_55, 
    'x_load_config__mutmut_56': x_load_config__mutmut_56, 
    'x_load_config__mutmut_57': x_load_config__mutmut_57, 
    'x_load_config__mutmut_58': x_load_config__mutmut_58, 
    'x_load_config__mutmut_59': x_load_config__mutmut_59, 
    'x_load_config__mutmut_60': x_load_config__mutmut_60, 
    'x_load_config__mutmut_61': x_load_config__mutmut_61, 
    'x_load_config__mutmut_62': x_load_config__mutmut_62, 
    'x_load_config__mutmut_63': x_load_config__mutmut_63, 
    'x_load_config__mutmut_64': x_load_config__mutmut_64, 
    'x_load_config__mutmut_65': x_load_config__mutmut_65, 
    'x_load_config__mutmut_66': x_load_config__mutmut_66, 
    'x_load_config__mutmut_67': x_load_config__mutmut_67, 
    'x_load_config__mutmut_68': x_load_config__mutmut_68, 
    'x_load_config__mutmut_69': x_load_config__mutmut_69, 
    'x_load_config__mutmut_70': x_load_config__mutmut_70, 
    'x_load_config__mutmut_71': x_load_config__mutmut_71, 
    'x_load_config__mutmut_72': x_load_config__mutmut_72, 
    'x_load_config__mutmut_73': x_load_config__mutmut_73, 
    'x_load_config__mutmut_74': x_load_config__mutmut_74, 
    'x_load_config__mutmut_75': x_load_config__mutmut_75, 
    'x_load_config__mutmut_76': x_load_config__mutmut_76, 
    'x_load_config__mutmut_77': x_load_config__mutmut_77, 
    'x_load_config__mutmut_78': x_load_config__mutmut_78, 
    'x_load_config__mutmut_79': x_load_config__mutmut_79, 
    'x_load_config__mutmut_80': x_load_config__mutmut_80, 
    'x_load_config__mutmut_81': x_load_config__mutmut_81, 
    'x_load_config__mutmut_82': x_load_config__mutmut_82, 
    'x_load_config__mutmut_83': x_load_config__mutmut_83, 
    'x_load_config__mutmut_84': x_load_config__mutmut_84, 
    'x_load_config__mutmut_85': x_load_config__mutmut_85, 
    'x_load_config__mutmut_86': x_load_config__mutmut_86, 
    'x_load_config__mutmut_87': x_load_config__mutmut_87, 
    'x_load_config__mutmut_88': x_load_config__mutmut_88, 
    'x_load_config__mutmut_89': x_load_config__mutmut_89, 
    'x_load_config__mutmut_90': x_load_config__mutmut_90, 
    'x_load_config__mutmut_91': x_load_config__mutmut_91, 
    'x_load_config__mutmut_92': x_load_config__mutmut_92, 
    'x_load_config__mutmut_93': x_load_config__mutmut_93, 
    'x_load_config__mutmut_94': x_load_config__mutmut_94, 
    'x_load_config__mutmut_95': x_load_config__mutmut_95, 
    'x_load_config__mutmut_96': x_load_config__mutmut_96, 
    'x_load_config__mutmut_97': x_load_config__mutmut_97
}
x_load_config__mutmut_orig.__name__ = 'x_load_config'
