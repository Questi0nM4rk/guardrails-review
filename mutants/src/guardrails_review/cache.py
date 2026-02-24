"""Local JSON cache for review results.

Stores reviews as append-only JSON files in `.guardrails-review/cache/`
relative to the project root. Files are named `pr-{N}-{timestamp}.json`.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path

from guardrails_review.types import ReviewComment, ReviewResult

_CACHE_DIR = Path(".guardrails-review") / "cache"
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


def _cache_dir(project_dir: Path | None) -> Path:
    args = [project_dir]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x__cache_dir__mutmut_orig, x__cache_dir__mutmut_mutants, args, kwargs, None)


def x__cache_dir__mutmut_orig(project_dir: Path | None) -> Path:
    base = project_dir if project_dir is not None else Path.cwd()
    return base / _CACHE_DIR


def x__cache_dir__mutmut_1(project_dir: Path | None) -> Path:
    base = None
    return base / _CACHE_DIR


def x__cache_dir__mutmut_2(project_dir: Path | None) -> Path:
    base = project_dir if project_dir is None else Path.cwd()
    return base / _CACHE_DIR


def x__cache_dir__mutmut_3(project_dir: Path | None) -> Path:
    base = project_dir if project_dir is not None else Path.cwd()
    return base * _CACHE_DIR

x__cache_dir__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x__cache_dir__mutmut_1': x__cache_dir__mutmut_1, 
    'x__cache_dir__mutmut_2': x__cache_dir__mutmut_2, 
    'x__cache_dir__mutmut_3': x__cache_dir__mutmut_3
}
x__cache_dir__mutmut_orig.__name__ = 'x__cache_dir'


def save_review(result: ReviewResult, project_dir: Path | None = None) -> Path:
    args = [result, project_dir]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x_save_review__mutmut_orig, x_save_review__mutmut_mutants, args, kwargs, None)


def x_save_review__mutmut_orig(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_1(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = None
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_2(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(None)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_3(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=None, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_4(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=None)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_5(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_6(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, )

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_7(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=False, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_8(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=False)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_9(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = None
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_10(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime(None)
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_11(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=None).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_12(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("XX%Y%m%dT%H%M%SXX")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_13(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%y%m%dt%h%m%s")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_14(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%M%DT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_15(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = None
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_16(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = None

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_17(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache * filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_18(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = None
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_19(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 2
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_20(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = None
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_21(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = None
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_22(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache * filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_23(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter = 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_24(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter -= 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_25(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 2

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_26(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = None
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_27(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(None)
    path.write_text(json.dumps(data, indent=2))
    return path.resolve()


def x_save_review__mutmut_28(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(None)
    return path.resolve()


def x_save_review__mutmut_29(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(None, indent=2))
    return path.resolve()


def x_save_review__mutmut_30(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=None))
    return path.resolve()


def x_save_review__mutmut_31(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(indent=2))
    return path.resolve()


def x_save_review__mutmut_32(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, ))
    return path.resolve()


def x_save_review__mutmut_33(result: ReviewResult, project_dir: Path | None = None) -> Path:
    """Serialize a ReviewResult to JSON and write to the cache directory.

    Creates the cache directory if it does not exist.
    Returns the absolute path to the written file.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"pr-{result.pr}-{ts}.json"
    path = cache / filename

    # Handle filename collision (same second)
    counter = 1
    while path.exists():
        filename = f"pr-{result.pr}-{ts}_{counter}.json"
        path = cache / filename
        counter += 1

    data = dataclasses.asdict(result)
    path.write_text(json.dumps(data, indent=3))
    return path.resolve()

x_save_review__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x_save_review__mutmut_1': x_save_review__mutmut_1, 
    'x_save_review__mutmut_2': x_save_review__mutmut_2, 
    'x_save_review__mutmut_3': x_save_review__mutmut_3, 
    'x_save_review__mutmut_4': x_save_review__mutmut_4, 
    'x_save_review__mutmut_5': x_save_review__mutmut_5, 
    'x_save_review__mutmut_6': x_save_review__mutmut_6, 
    'x_save_review__mutmut_7': x_save_review__mutmut_7, 
    'x_save_review__mutmut_8': x_save_review__mutmut_8, 
    'x_save_review__mutmut_9': x_save_review__mutmut_9, 
    'x_save_review__mutmut_10': x_save_review__mutmut_10, 
    'x_save_review__mutmut_11': x_save_review__mutmut_11, 
    'x_save_review__mutmut_12': x_save_review__mutmut_12, 
    'x_save_review__mutmut_13': x_save_review__mutmut_13, 
    'x_save_review__mutmut_14': x_save_review__mutmut_14, 
    'x_save_review__mutmut_15': x_save_review__mutmut_15, 
    'x_save_review__mutmut_16': x_save_review__mutmut_16, 
    'x_save_review__mutmut_17': x_save_review__mutmut_17, 
    'x_save_review__mutmut_18': x_save_review__mutmut_18, 
    'x_save_review__mutmut_19': x_save_review__mutmut_19, 
    'x_save_review__mutmut_20': x_save_review__mutmut_20, 
    'x_save_review__mutmut_21': x_save_review__mutmut_21, 
    'x_save_review__mutmut_22': x_save_review__mutmut_22, 
    'x_save_review__mutmut_23': x_save_review__mutmut_23, 
    'x_save_review__mutmut_24': x_save_review__mutmut_24, 
    'x_save_review__mutmut_25': x_save_review__mutmut_25, 
    'x_save_review__mutmut_26': x_save_review__mutmut_26, 
    'x_save_review__mutmut_27': x_save_review__mutmut_27, 
    'x_save_review__mutmut_28': x_save_review__mutmut_28, 
    'x_save_review__mutmut_29': x_save_review__mutmut_29, 
    'x_save_review__mutmut_30': x_save_review__mutmut_30, 
    'x_save_review__mutmut_31': x_save_review__mutmut_31, 
    'x_save_review__mutmut_32': x_save_review__mutmut_32, 
    'x_save_review__mutmut_33': x_save_review__mutmut_33
}
x_save_review__mutmut_orig.__name__ = 'x_save_review'


def _glob_for_pr(pr: int, project_dir: Path | None) -> list[Path]:
    args = [pr, project_dir]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x__glob_for_pr__mutmut_orig, x__glob_for_pr__mutmut_mutants, args, kwargs, None)


def x__glob_for_pr__mutmut_orig(pr: int, project_dir: Path | None) -> list[Path]:
    """Return cached review files for a PR, sorted oldest to newest by name."""
    cache = _cache_dir(project_dir)
    if not cache.is_dir():
        return []
    return sorted(cache.glob(f"pr-{pr}-*.json"))


def x__glob_for_pr__mutmut_1(pr: int, project_dir: Path | None) -> list[Path]:
    """Return cached review files for a PR, sorted oldest to newest by name."""
    cache = None
    if not cache.is_dir():
        return []
    return sorted(cache.glob(f"pr-{pr}-*.json"))


def x__glob_for_pr__mutmut_2(pr: int, project_dir: Path | None) -> list[Path]:
    """Return cached review files for a PR, sorted oldest to newest by name."""
    cache = _cache_dir(None)
    if not cache.is_dir():
        return []
    return sorted(cache.glob(f"pr-{pr}-*.json"))


def x__glob_for_pr__mutmut_3(pr: int, project_dir: Path | None) -> list[Path]:
    """Return cached review files for a PR, sorted oldest to newest by name."""
    cache = _cache_dir(project_dir)
    if cache.is_dir():
        return []
    return sorted(cache.glob(f"pr-{pr}-*.json"))


def x__glob_for_pr__mutmut_4(pr: int, project_dir: Path | None) -> list[Path]:
    """Return cached review files for a PR, sorted oldest to newest by name."""
    cache = _cache_dir(project_dir)
    if not cache.is_dir():
        return []
    return sorted(None)


def x__glob_for_pr__mutmut_5(pr: int, project_dir: Path | None) -> list[Path]:
    """Return cached review files for a PR, sorted oldest to newest by name."""
    cache = _cache_dir(project_dir)
    if not cache.is_dir():
        return []
    return sorted(cache.glob(None))

x__glob_for_pr__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x__glob_for_pr__mutmut_1': x__glob_for_pr__mutmut_1, 
    'x__glob_for_pr__mutmut_2': x__glob_for_pr__mutmut_2, 
    'x__glob_for_pr__mutmut_3': x__glob_for_pr__mutmut_3, 
    'x__glob_for_pr__mutmut_4': x__glob_for_pr__mutmut_4, 
    'x__glob_for_pr__mutmut_5': x__glob_for_pr__mutmut_5
}
x__glob_for_pr__mutmut_orig.__name__ = 'x__glob_for_pr'


def _load_file(path: Path) -> ReviewResult:
    args = [path]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x__load_file__mutmut_orig, x__load_file__mutmut_mutants, args, kwargs, None)


def x__load_file__mutmut_orig(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_1(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = None
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_2(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(None)
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_3(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = None
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_4(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get(None, [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_5(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", None)]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_6(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get([])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_7(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", )]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_8(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("XXcommentsXX", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_9(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("COMMENTS", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_10(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=None,
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_11(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=None,
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_12(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=None,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_13(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=None,
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_14(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=None,
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_15(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=None,
    )


def x__load_file__mutmut_16(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_17(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_18(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_19(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_20(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_21(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        )


def x__load_file__mutmut_22(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["XXverdictXX"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_23(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["VERDICT"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_24(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["XXsummaryXX"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_25(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["SUMMARY"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_26(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get(None, ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_27(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", None),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_28(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get(""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_29(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_30(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("XXmodelXX", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_31(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("MODEL", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_32(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", "XXXX"),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_33(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get(None, ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_34(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", None),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_35(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get(""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_36(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_37(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("XXtimestampXX", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_38(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("TIMESTAMP", ""),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_39(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", "XXXX"),
        pr=data.get("pr", 0),
    )


def x__load_file__mutmut_40(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get(None, 0),
    )


def x__load_file__mutmut_41(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", None),
    )


def x__load_file__mutmut_42(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get(0),
    )


def x__load_file__mutmut_43(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", ),
    )


def x__load_file__mutmut_44(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("XXprXX", 0),
    )


def x__load_file__mutmut_45(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("PR", 0),
    )


def x__load_file__mutmut_46(path: Path) -> ReviewResult:
    """Deserialize a single cache file into a ReviewResult."""
    data = json.loads(path.read_text())
    comments = [ReviewComment(**c) for c in data.get("comments", [])]
    return ReviewResult(
        verdict=data["verdict"],
        summary=data["summary"],
        comments=comments,
        model=data.get("model", ""),
        timestamp=data.get("timestamp", ""),
        pr=data.get("pr", 1),
    )

x__load_file__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x__load_file__mutmut_1': x__load_file__mutmut_1, 
    'x__load_file__mutmut_2': x__load_file__mutmut_2, 
    'x__load_file__mutmut_3': x__load_file__mutmut_3, 
    'x__load_file__mutmut_4': x__load_file__mutmut_4, 
    'x__load_file__mutmut_5': x__load_file__mutmut_5, 
    'x__load_file__mutmut_6': x__load_file__mutmut_6, 
    'x__load_file__mutmut_7': x__load_file__mutmut_7, 
    'x__load_file__mutmut_8': x__load_file__mutmut_8, 
    'x__load_file__mutmut_9': x__load_file__mutmut_9, 
    'x__load_file__mutmut_10': x__load_file__mutmut_10, 
    'x__load_file__mutmut_11': x__load_file__mutmut_11, 
    'x__load_file__mutmut_12': x__load_file__mutmut_12, 
    'x__load_file__mutmut_13': x__load_file__mutmut_13, 
    'x__load_file__mutmut_14': x__load_file__mutmut_14, 
    'x__load_file__mutmut_15': x__load_file__mutmut_15, 
    'x__load_file__mutmut_16': x__load_file__mutmut_16, 
    'x__load_file__mutmut_17': x__load_file__mutmut_17, 
    'x__load_file__mutmut_18': x__load_file__mutmut_18, 
    'x__load_file__mutmut_19': x__load_file__mutmut_19, 
    'x__load_file__mutmut_20': x__load_file__mutmut_20, 
    'x__load_file__mutmut_21': x__load_file__mutmut_21, 
    'x__load_file__mutmut_22': x__load_file__mutmut_22, 
    'x__load_file__mutmut_23': x__load_file__mutmut_23, 
    'x__load_file__mutmut_24': x__load_file__mutmut_24, 
    'x__load_file__mutmut_25': x__load_file__mutmut_25, 
    'x__load_file__mutmut_26': x__load_file__mutmut_26, 
    'x__load_file__mutmut_27': x__load_file__mutmut_27, 
    'x__load_file__mutmut_28': x__load_file__mutmut_28, 
    'x__load_file__mutmut_29': x__load_file__mutmut_29, 
    'x__load_file__mutmut_30': x__load_file__mutmut_30, 
    'x__load_file__mutmut_31': x__load_file__mutmut_31, 
    'x__load_file__mutmut_32': x__load_file__mutmut_32, 
    'x__load_file__mutmut_33': x__load_file__mutmut_33, 
    'x__load_file__mutmut_34': x__load_file__mutmut_34, 
    'x__load_file__mutmut_35': x__load_file__mutmut_35, 
    'x__load_file__mutmut_36': x__load_file__mutmut_36, 
    'x__load_file__mutmut_37': x__load_file__mutmut_37, 
    'x__load_file__mutmut_38': x__load_file__mutmut_38, 
    'x__load_file__mutmut_39': x__load_file__mutmut_39, 
    'x__load_file__mutmut_40': x__load_file__mutmut_40, 
    'x__load_file__mutmut_41': x__load_file__mutmut_41, 
    'x__load_file__mutmut_42': x__load_file__mutmut_42, 
    'x__load_file__mutmut_43': x__load_file__mutmut_43, 
    'x__load_file__mutmut_44': x__load_file__mutmut_44, 
    'x__load_file__mutmut_45': x__load_file__mutmut_45, 
    'x__load_file__mutmut_46': x__load_file__mutmut_46
}
x__load_file__mutmut_orig.__name__ = 'x__load_file'


def load_latest_review(pr: int, project_dir: Path | None = None) -> ReviewResult | None:
    args = [pr, project_dir]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x_load_latest_review__mutmut_orig, x_load_latest_review__mutmut_mutants, args, kwargs, None)


def x_load_latest_review__mutmut_orig(pr: int, project_dir: Path | None = None) -> ReviewResult | None:
    """Load the most recent cached review for a PR.

    Returns None if no cached reviews exist.
    """
    files = _glob_for_pr(pr, project_dir)
    if not files:
        return None
    return _load_file(files[-1])


def x_load_latest_review__mutmut_1(pr: int, project_dir: Path | None = None) -> ReviewResult | None:
    """Load the most recent cached review for a PR.

    Returns None if no cached reviews exist.
    """
    files = None
    if not files:
        return None
    return _load_file(files[-1])


def x_load_latest_review__mutmut_2(pr: int, project_dir: Path | None = None) -> ReviewResult | None:
    """Load the most recent cached review for a PR.

    Returns None if no cached reviews exist.
    """
    files = _glob_for_pr(None, project_dir)
    if not files:
        return None
    return _load_file(files[-1])


def x_load_latest_review__mutmut_3(pr: int, project_dir: Path | None = None) -> ReviewResult | None:
    """Load the most recent cached review for a PR.

    Returns None if no cached reviews exist.
    """
    files = _glob_for_pr(pr, None)
    if not files:
        return None
    return _load_file(files[-1])


def x_load_latest_review__mutmut_4(pr: int, project_dir: Path | None = None) -> ReviewResult | None:
    """Load the most recent cached review for a PR.

    Returns None if no cached reviews exist.
    """
    files = _glob_for_pr(project_dir)
    if not files:
        return None
    return _load_file(files[-1])


def x_load_latest_review__mutmut_5(pr: int, project_dir: Path | None = None) -> ReviewResult | None:
    """Load the most recent cached review for a PR.

    Returns None if no cached reviews exist.
    """
    files = _glob_for_pr(pr, )
    if not files:
        return None
    return _load_file(files[-1])


def x_load_latest_review__mutmut_6(pr: int, project_dir: Path | None = None) -> ReviewResult | None:
    """Load the most recent cached review for a PR.

    Returns None if no cached reviews exist.
    """
    files = _glob_for_pr(pr, project_dir)
    if files:
        return None
    return _load_file(files[-1])


def x_load_latest_review__mutmut_7(pr: int, project_dir: Path | None = None) -> ReviewResult | None:
    """Load the most recent cached review for a PR.

    Returns None if no cached reviews exist.
    """
    files = _glob_for_pr(pr, project_dir)
    if not files:
        return None
    return _load_file(None)


def x_load_latest_review__mutmut_8(pr: int, project_dir: Path | None = None) -> ReviewResult | None:
    """Load the most recent cached review for a PR.

    Returns None if no cached reviews exist.
    """
    files = _glob_for_pr(pr, project_dir)
    if not files:
        return None
    return _load_file(files[+1])


def x_load_latest_review__mutmut_9(pr: int, project_dir: Path | None = None) -> ReviewResult | None:
    """Load the most recent cached review for a PR.

    Returns None if no cached reviews exist.
    """
    files = _glob_for_pr(pr, project_dir)
    if not files:
        return None
    return _load_file(files[-2])

x_load_latest_review__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x_load_latest_review__mutmut_1': x_load_latest_review__mutmut_1, 
    'x_load_latest_review__mutmut_2': x_load_latest_review__mutmut_2, 
    'x_load_latest_review__mutmut_3': x_load_latest_review__mutmut_3, 
    'x_load_latest_review__mutmut_4': x_load_latest_review__mutmut_4, 
    'x_load_latest_review__mutmut_5': x_load_latest_review__mutmut_5, 
    'x_load_latest_review__mutmut_6': x_load_latest_review__mutmut_6, 
    'x_load_latest_review__mutmut_7': x_load_latest_review__mutmut_7, 
    'x_load_latest_review__mutmut_8': x_load_latest_review__mutmut_8, 
    'x_load_latest_review__mutmut_9': x_load_latest_review__mutmut_9
}
x_load_latest_review__mutmut_orig.__name__ = 'x_load_latest_review'


def load_all_reviews(pr: int, project_dir: Path | None = None) -> list[ReviewResult]:
    args = [pr, project_dir]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x_load_all_reviews__mutmut_orig, x_load_all_reviews__mutmut_mutants, args, kwargs, None)


def x_load_all_reviews__mutmut_orig(pr: int, project_dir: Path | None = None) -> list[ReviewResult]:
    """Load all cached reviews for a PR, sorted oldest to newest."""
    files = _glob_for_pr(pr, project_dir)
    return [_load_file(f) for f in files]


def x_load_all_reviews__mutmut_1(pr: int, project_dir: Path | None = None) -> list[ReviewResult]:
    """Load all cached reviews for a PR, sorted oldest to newest."""
    files = None
    return [_load_file(f) for f in files]


def x_load_all_reviews__mutmut_2(pr: int, project_dir: Path | None = None) -> list[ReviewResult]:
    """Load all cached reviews for a PR, sorted oldest to newest."""
    files = _glob_for_pr(None, project_dir)
    return [_load_file(f) for f in files]


def x_load_all_reviews__mutmut_3(pr: int, project_dir: Path | None = None) -> list[ReviewResult]:
    """Load all cached reviews for a PR, sorted oldest to newest."""
    files = _glob_for_pr(pr, None)
    return [_load_file(f) for f in files]


def x_load_all_reviews__mutmut_4(pr: int, project_dir: Path | None = None) -> list[ReviewResult]:
    """Load all cached reviews for a PR, sorted oldest to newest."""
    files = _glob_for_pr(project_dir)
    return [_load_file(f) for f in files]


def x_load_all_reviews__mutmut_5(pr: int, project_dir: Path | None = None) -> list[ReviewResult]:
    """Load all cached reviews for a PR, sorted oldest to newest."""
    files = _glob_for_pr(pr, )
    return [_load_file(f) for f in files]


def x_load_all_reviews__mutmut_6(pr: int, project_dir: Path | None = None) -> list[ReviewResult]:
    """Load all cached reviews for a PR, sorted oldest to newest."""
    files = _glob_for_pr(pr, project_dir)
    return [_load_file(None) for f in files]

x_load_all_reviews__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x_load_all_reviews__mutmut_1': x_load_all_reviews__mutmut_1, 
    'x_load_all_reviews__mutmut_2': x_load_all_reviews__mutmut_2, 
    'x_load_all_reviews__mutmut_3': x_load_all_reviews__mutmut_3, 
    'x_load_all_reviews__mutmut_4': x_load_all_reviews__mutmut_4, 
    'x_load_all_reviews__mutmut_5': x_load_all_reviews__mutmut_5, 
    'x_load_all_reviews__mutmut_6': x_load_all_reviews__mutmut_6
}
x_load_all_reviews__mutmut_orig.__name__ = 'x_load_all_reviews'
