"""Core review orchestrator: diff -> LLM -> validate -> post."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from guardrails_review.cache import save_review
from guardrails_review.config import load_config
from guardrails_review.diff import parse_diff_hunks
from guardrails_review.github import get_pr_diff, get_pr_metadata, get_repo_info, post_review
from guardrails_review.llm import call_openrouter, call_openrouter_tools
from guardrails_review.tools import TOOL_DEFINITIONS, ToolContext, execute_tool
from guardrails_review.types import ReviewComment, ReviewConfig, ReviewResult

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a code reviewer. Review the PR diff and return ONLY valid JSON:

{
  "verdict": "approve" | "request_changes",
  "summary": "1-2 sentence assessment",
  "comments": [
    {
      "path": "relative/file/path",
      "line": <line number in new file>,
      "severity": "error" | "warning" | "info",
      "body": "review comment"
    }
  ]
}

Rules:
- Line numbers reference the new file (right side of diff, + or space-prefixed lines)
- Only comment on lines within diff hunks
- "error" = must fix before merge, "warning" = should fix, "info" = suggestion
- Empty comments + "approve" = no issues found
- Do NOT flag style/formatting (handled by linters and pre-commit hooks)
- Do NOT flag missing tests unless a critical code path has zero coverage
- Include a <!-- guardrails-review --> HTML comment at the start of the summary\
"""

_AGENTIC_SYSTEM_PROMPT = """\
You are a thorough code reviewer with tools to explore the codebase before submitting.

**Workflow:**
1. First, examine the diff to understand what changed
2. Use your tools to gather context:
   - read_file() to see full file context around changes
   - list_changed_files() to see all files in the PR
   - search_code() to find related code, callers, or tests
3. When you have enough context, call submit_review() with your findings

**Review rules:**
- Line numbers reference the new file (right side of diff)
- Only comment on lines within diff hunks
- "error" = must fix, "warning" = should fix, "info" = suggestion
- Do NOT flag style/formatting (handled by linters)
- Do NOT flag missing tests unless a critical path has zero coverage
- Include <!-- guardrails-review --> at the start of your summary\
"""

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
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


def build_messages(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    args = [diff, config, pr_meta]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x_build_messages__mutmut_orig, x_build_messages__mutmut_mutants, args, kwargs, None)


def x_build_messages__mutmut_orig(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_1(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = None
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_2(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get(None, 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_3(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', None)}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_4(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_5(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', )}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_6(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('XXtitleXX', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_7(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('TITLE', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_8(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'XXUntitledXX')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_9(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_10(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'UNTITLED')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_11(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "XXXX",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_12(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") and "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_13(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get(None, "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_14(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", None) or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_15(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_16(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", ) or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_17(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("XXbodyXX", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_18(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("BODY", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_19(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "XXXX") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_20(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "XX(no description)XX",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_21(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(NO DESCRIPTION)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_22(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "XXXX",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_23(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "XX## DiffXX",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_24(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_25(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## DIFF",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_26(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "XXXX",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_27(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = None
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_28(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "XXXX",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_29(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"XXroleXX": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_30(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"ROLE": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_31(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "XXsystemXX", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_32(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "SYSTEM", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_33(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "XXcontentXX": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_34(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "CONTENT": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_35(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"XXroleXX": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_36(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"ROLE": "user", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_37(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "XXuserXX", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_38(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "USER", "content": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_39(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "XXcontentXX": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_40(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "CONTENT": "\n".join(user_parts)},
    ]


def x_build_messages__mutmut_41(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(None)},
    ]


def x_build_messages__mutmut_42(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, str]]:
    """Build the message list for the LLM call."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "XX\nXX".join(user_parts)},
    ]

x_build_messages__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x_build_messages__mutmut_1': x_build_messages__mutmut_1, 
    'x_build_messages__mutmut_2': x_build_messages__mutmut_2, 
    'x_build_messages__mutmut_3': x_build_messages__mutmut_3, 
    'x_build_messages__mutmut_4': x_build_messages__mutmut_4, 
    'x_build_messages__mutmut_5': x_build_messages__mutmut_5, 
    'x_build_messages__mutmut_6': x_build_messages__mutmut_6, 
    'x_build_messages__mutmut_7': x_build_messages__mutmut_7, 
    'x_build_messages__mutmut_8': x_build_messages__mutmut_8, 
    'x_build_messages__mutmut_9': x_build_messages__mutmut_9, 
    'x_build_messages__mutmut_10': x_build_messages__mutmut_10, 
    'x_build_messages__mutmut_11': x_build_messages__mutmut_11, 
    'x_build_messages__mutmut_12': x_build_messages__mutmut_12, 
    'x_build_messages__mutmut_13': x_build_messages__mutmut_13, 
    'x_build_messages__mutmut_14': x_build_messages__mutmut_14, 
    'x_build_messages__mutmut_15': x_build_messages__mutmut_15, 
    'x_build_messages__mutmut_16': x_build_messages__mutmut_16, 
    'x_build_messages__mutmut_17': x_build_messages__mutmut_17, 
    'x_build_messages__mutmut_18': x_build_messages__mutmut_18, 
    'x_build_messages__mutmut_19': x_build_messages__mutmut_19, 
    'x_build_messages__mutmut_20': x_build_messages__mutmut_20, 
    'x_build_messages__mutmut_21': x_build_messages__mutmut_21, 
    'x_build_messages__mutmut_22': x_build_messages__mutmut_22, 
    'x_build_messages__mutmut_23': x_build_messages__mutmut_23, 
    'x_build_messages__mutmut_24': x_build_messages__mutmut_24, 
    'x_build_messages__mutmut_25': x_build_messages__mutmut_25, 
    'x_build_messages__mutmut_26': x_build_messages__mutmut_26, 
    'x_build_messages__mutmut_27': x_build_messages__mutmut_27, 
    'x_build_messages__mutmut_28': x_build_messages__mutmut_28, 
    'x_build_messages__mutmut_29': x_build_messages__mutmut_29, 
    'x_build_messages__mutmut_30': x_build_messages__mutmut_30, 
    'x_build_messages__mutmut_31': x_build_messages__mutmut_31, 
    'x_build_messages__mutmut_32': x_build_messages__mutmut_32, 
    'x_build_messages__mutmut_33': x_build_messages__mutmut_33, 
    'x_build_messages__mutmut_34': x_build_messages__mutmut_34, 
    'x_build_messages__mutmut_35': x_build_messages__mutmut_35, 
    'x_build_messages__mutmut_36': x_build_messages__mutmut_36, 
    'x_build_messages__mutmut_37': x_build_messages__mutmut_37, 
    'x_build_messages__mutmut_38': x_build_messages__mutmut_38, 
    'x_build_messages__mutmut_39': x_build_messages__mutmut_39, 
    'x_build_messages__mutmut_40': x_build_messages__mutmut_40, 
    'x_build_messages__mutmut_41': x_build_messages__mutmut_41, 
    'x_build_messages__mutmut_42': x_build_messages__mutmut_42
}
x_build_messages__mutmut_orig.__name__ = 'x_build_messages'


def build_agentic_messages(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    args = [diff, config, pr_meta]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x_build_agentic_messages__mutmut_orig, x_build_agentic_messages__mutmut_mutants, args, kwargs, None)


def x_build_agentic_messages__mutmut_orig(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_1(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = None
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_2(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get(None, 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_3(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', None)}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_4(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_5(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', )}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_6(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('XXtitleXX', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_7(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('TITLE', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_8(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'XXUntitledXX')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_9(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_10(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'UNTITLED')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_11(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "XXXX",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_12(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") and "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_13(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get(None, "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_14(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", None) or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_15(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_16(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", ) or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_17(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("XXbodyXX", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_18(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("BODY", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_19(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "XXXX") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_20(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "XX(no description)XX",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_21(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(NO DESCRIPTION)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_22(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "XXXX",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_23(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "XX## DiffXX",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_24(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_25(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## DIFF",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_26(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "XXXX",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_27(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = None
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_28(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "XXXX",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_29(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"XXroleXX": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_30(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"ROLE": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_31(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "XXsystemXX", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_32(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "SYSTEM", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_33(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "XXcontentXX": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_34(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "CONTENT": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_35(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"XXroleXX": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_36(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"ROLE": "user", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_37(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "XXuserXX", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_38(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "USER", "content": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_39(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "XXcontentXX": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_40(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "CONTENT": "\n".join(user_parts)},
    ]


def x_build_agentic_messages__mutmut_41(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(None)},
    ]


def x_build_agentic_messages__mutmut_42(
    diff: str,
    config: ReviewConfig,
    pr_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the message list for the agentic tool-use review loop."""
    user_parts = [
        f"# PR: {pr_meta.get('title', 'Untitled')}",
        "",
        pr_meta.get("body", "") or "(no description)",
        "",
        "## Diff",
        "",
        diff[: config.max_diff_chars],
    ]
    if config.extra_instructions:
        user_parts = [
            f"## Project-specific instructions\n\n{config.extra_instructions}",
            "",
            *user_parts,
        ]
    return [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": "XX\nXX".join(user_parts)},
    ]

x_build_agentic_messages__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x_build_agentic_messages__mutmut_1': x_build_agentic_messages__mutmut_1, 
    'x_build_agentic_messages__mutmut_2': x_build_agentic_messages__mutmut_2, 
    'x_build_agentic_messages__mutmut_3': x_build_agentic_messages__mutmut_3, 
    'x_build_agentic_messages__mutmut_4': x_build_agentic_messages__mutmut_4, 
    'x_build_agentic_messages__mutmut_5': x_build_agentic_messages__mutmut_5, 
    'x_build_agentic_messages__mutmut_6': x_build_agentic_messages__mutmut_6, 
    'x_build_agentic_messages__mutmut_7': x_build_agentic_messages__mutmut_7, 
    'x_build_agentic_messages__mutmut_8': x_build_agentic_messages__mutmut_8, 
    'x_build_agentic_messages__mutmut_9': x_build_agentic_messages__mutmut_9, 
    'x_build_agentic_messages__mutmut_10': x_build_agentic_messages__mutmut_10, 
    'x_build_agentic_messages__mutmut_11': x_build_agentic_messages__mutmut_11, 
    'x_build_agentic_messages__mutmut_12': x_build_agentic_messages__mutmut_12, 
    'x_build_agentic_messages__mutmut_13': x_build_agentic_messages__mutmut_13, 
    'x_build_agentic_messages__mutmut_14': x_build_agentic_messages__mutmut_14, 
    'x_build_agentic_messages__mutmut_15': x_build_agentic_messages__mutmut_15, 
    'x_build_agentic_messages__mutmut_16': x_build_agentic_messages__mutmut_16, 
    'x_build_agentic_messages__mutmut_17': x_build_agentic_messages__mutmut_17, 
    'x_build_agentic_messages__mutmut_18': x_build_agentic_messages__mutmut_18, 
    'x_build_agentic_messages__mutmut_19': x_build_agentic_messages__mutmut_19, 
    'x_build_agentic_messages__mutmut_20': x_build_agentic_messages__mutmut_20, 
    'x_build_agentic_messages__mutmut_21': x_build_agentic_messages__mutmut_21, 
    'x_build_agentic_messages__mutmut_22': x_build_agentic_messages__mutmut_22, 
    'x_build_agentic_messages__mutmut_23': x_build_agentic_messages__mutmut_23, 
    'x_build_agentic_messages__mutmut_24': x_build_agentic_messages__mutmut_24, 
    'x_build_agentic_messages__mutmut_25': x_build_agentic_messages__mutmut_25, 
    'x_build_agentic_messages__mutmut_26': x_build_agentic_messages__mutmut_26, 
    'x_build_agentic_messages__mutmut_27': x_build_agentic_messages__mutmut_27, 
    'x_build_agentic_messages__mutmut_28': x_build_agentic_messages__mutmut_28, 
    'x_build_agentic_messages__mutmut_29': x_build_agentic_messages__mutmut_29, 
    'x_build_agentic_messages__mutmut_30': x_build_agentic_messages__mutmut_30, 
    'x_build_agentic_messages__mutmut_31': x_build_agentic_messages__mutmut_31, 
    'x_build_agentic_messages__mutmut_32': x_build_agentic_messages__mutmut_32, 
    'x_build_agentic_messages__mutmut_33': x_build_agentic_messages__mutmut_33, 
    'x_build_agentic_messages__mutmut_34': x_build_agentic_messages__mutmut_34, 
    'x_build_agentic_messages__mutmut_35': x_build_agentic_messages__mutmut_35, 
    'x_build_agentic_messages__mutmut_36': x_build_agentic_messages__mutmut_36, 
    'x_build_agentic_messages__mutmut_37': x_build_agentic_messages__mutmut_37, 
    'x_build_agentic_messages__mutmut_38': x_build_agentic_messages__mutmut_38, 
    'x_build_agentic_messages__mutmut_39': x_build_agentic_messages__mutmut_39, 
    'x_build_agentic_messages__mutmut_40': x_build_agentic_messages__mutmut_40, 
    'x_build_agentic_messages__mutmut_41': x_build_agentic_messages__mutmut_41, 
    'x_build_agentic_messages__mutmut_42': x_build_agentic_messages__mutmut_42
}
x_build_agentic_messages__mutmut_orig.__name__ = 'x_build_agentic_messages'


def parse_response(raw: str, model: str, pr: int) -> ReviewResult:
    args = [raw, model, pr]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x_parse_response__mutmut_orig, x_parse_response__mutmut_mutants, args, kwargs, None)


def x_parse_response__mutmut_orig(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_1(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = None

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_2(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=None).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_3(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = None
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_4(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(None)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_5(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is not None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_6(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict=None,
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_7(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=None,
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_8(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=None,
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_9(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=None,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_10(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=None,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_11(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=None,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_12(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_13(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_14(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_15(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_16(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_17(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_18(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="XXrequest_changesXX",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_19(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="REQUEST_CHANGES",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_response__mutmut_20(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(None, model, pr, timestamp)


def x_parse_response__mutmut_21(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, None, pr, timestamp)


def x_parse_response__mutmut_22(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, None, timestamp)


def x_parse_response__mutmut_23(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, None)


def x_parse_response__mutmut_24(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(model, pr, timestamp)


def x_parse_response__mutmut_25(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, pr, timestamp)


def x_parse_response__mutmut_26(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, timestamp)


def x_parse_response__mutmut_27(raw: str, model: str, pr: int) -> ReviewResult:
    """Parse LLM response JSON into a ReviewResult.

    Falls back gracefully for malformed responses.
    """
    timestamp = datetime.now(tz=UTC).isoformat()

    parsed = _try_parse_json(raw)
    if parsed is None:
        return ReviewResult(
            verdict="request_changes",
            summary=f"<!-- guardrails-review -->\nReview produced non-JSON output:\n\n{raw}",
            comments=[],
            model=model,
            timestamp=timestamp,
            pr=pr,
        )

    return _build_result_from_parsed(parsed, model, pr, )

x_parse_response__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x_parse_response__mutmut_1': x_parse_response__mutmut_1, 
    'x_parse_response__mutmut_2': x_parse_response__mutmut_2, 
    'x_parse_response__mutmut_3': x_parse_response__mutmut_3, 
    'x_parse_response__mutmut_4': x_parse_response__mutmut_4, 
    'x_parse_response__mutmut_5': x_parse_response__mutmut_5, 
    'x_parse_response__mutmut_6': x_parse_response__mutmut_6, 
    'x_parse_response__mutmut_7': x_parse_response__mutmut_7, 
    'x_parse_response__mutmut_8': x_parse_response__mutmut_8, 
    'x_parse_response__mutmut_9': x_parse_response__mutmut_9, 
    'x_parse_response__mutmut_10': x_parse_response__mutmut_10, 
    'x_parse_response__mutmut_11': x_parse_response__mutmut_11, 
    'x_parse_response__mutmut_12': x_parse_response__mutmut_12, 
    'x_parse_response__mutmut_13': x_parse_response__mutmut_13, 
    'x_parse_response__mutmut_14': x_parse_response__mutmut_14, 
    'x_parse_response__mutmut_15': x_parse_response__mutmut_15, 
    'x_parse_response__mutmut_16': x_parse_response__mutmut_16, 
    'x_parse_response__mutmut_17': x_parse_response__mutmut_17, 
    'x_parse_response__mutmut_18': x_parse_response__mutmut_18, 
    'x_parse_response__mutmut_19': x_parse_response__mutmut_19, 
    'x_parse_response__mutmut_20': x_parse_response__mutmut_20, 
    'x_parse_response__mutmut_21': x_parse_response__mutmut_21, 
    'x_parse_response__mutmut_22': x_parse_response__mutmut_22, 
    'x_parse_response__mutmut_23': x_parse_response__mutmut_23, 
    'x_parse_response__mutmut_24': x_parse_response__mutmut_24, 
    'x_parse_response__mutmut_25': x_parse_response__mutmut_25, 
    'x_parse_response__mutmut_26': x_parse_response__mutmut_26, 
    'x_parse_response__mutmut_27': x_parse_response__mutmut_27
}
x_parse_response__mutmut_orig.__name__ = 'x_parse_response'


def parse_submit_review_args(arguments: str, model: str, pr: int) -> ReviewResult:
    args = [arguments, model, pr]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x_parse_submit_review_args__mutmut_orig, x_parse_submit_review_args__mutmut_mutants, args, kwargs, None)


def x_parse_submit_review_args__mutmut_orig(arguments: str, model: str, pr: int) -> ReviewResult:
    """Parse the submit_review tool call arguments into a ReviewResult."""
    timestamp = datetime.now(tz=UTC).isoformat()
    parsed = json.loads(arguments)
    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_submit_review_args__mutmut_1(arguments: str, model: str, pr: int) -> ReviewResult:
    """Parse the submit_review tool call arguments into a ReviewResult."""
    timestamp = None
    parsed = json.loads(arguments)
    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_submit_review_args__mutmut_2(arguments: str, model: str, pr: int) -> ReviewResult:
    """Parse the submit_review tool call arguments into a ReviewResult."""
    timestamp = datetime.now(tz=None).isoformat()
    parsed = json.loads(arguments)
    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_submit_review_args__mutmut_3(arguments: str, model: str, pr: int) -> ReviewResult:
    """Parse the submit_review tool call arguments into a ReviewResult."""
    timestamp = datetime.now(tz=UTC).isoformat()
    parsed = None
    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_submit_review_args__mutmut_4(arguments: str, model: str, pr: int) -> ReviewResult:
    """Parse the submit_review tool call arguments into a ReviewResult."""
    timestamp = datetime.now(tz=UTC).isoformat()
    parsed = json.loads(None)
    return _build_result_from_parsed(parsed, model, pr, timestamp)


def x_parse_submit_review_args__mutmut_5(arguments: str, model: str, pr: int) -> ReviewResult:
    """Parse the submit_review tool call arguments into a ReviewResult."""
    timestamp = datetime.now(tz=UTC).isoformat()
    parsed = json.loads(arguments)
    return _build_result_from_parsed(None, model, pr, timestamp)


def x_parse_submit_review_args__mutmut_6(arguments: str, model: str, pr: int) -> ReviewResult:
    """Parse the submit_review tool call arguments into a ReviewResult."""
    timestamp = datetime.now(tz=UTC).isoformat()
    parsed = json.loads(arguments)
    return _build_result_from_parsed(parsed, None, pr, timestamp)


def x_parse_submit_review_args__mutmut_7(arguments: str, model: str, pr: int) -> ReviewResult:
    """Parse the submit_review tool call arguments into a ReviewResult."""
    timestamp = datetime.now(tz=UTC).isoformat()
    parsed = json.loads(arguments)
    return _build_result_from_parsed(parsed, model, None, timestamp)


def x_parse_submit_review_args__mutmut_8(arguments: str, model: str, pr: int) -> ReviewResult:
    """Parse the submit_review tool call arguments into a ReviewResult."""
    timestamp = datetime.now(tz=UTC).isoformat()
    parsed = json.loads(arguments)
    return _build_result_from_parsed(parsed, model, pr, None)


def x_parse_submit_review_args__mutmut_9(arguments: str, model: str, pr: int) -> ReviewResult:
    """Parse the submit_review tool call arguments into a ReviewResult."""
    timestamp = datetime.now(tz=UTC).isoformat()
    parsed = json.loads(arguments)
    return _build_result_from_parsed(model, pr, timestamp)


def x_parse_submit_review_args__mutmut_10(arguments: str, model: str, pr: int) -> ReviewResult:
    """Parse the submit_review tool call arguments into a ReviewResult."""
    timestamp = datetime.now(tz=UTC).isoformat()
    parsed = json.loads(arguments)
    return _build_result_from_parsed(parsed, pr, timestamp)


def x_parse_submit_review_args__mutmut_11(arguments: str, model: str, pr: int) -> ReviewResult:
    """Parse the submit_review tool call arguments into a ReviewResult."""
    timestamp = datetime.now(tz=UTC).isoformat()
    parsed = json.loads(arguments)
    return _build_result_from_parsed(parsed, model, timestamp)


def x_parse_submit_review_args__mutmut_12(arguments: str, model: str, pr: int) -> ReviewResult:
    """Parse the submit_review tool call arguments into a ReviewResult."""
    timestamp = datetime.now(tz=UTC).isoformat()
    parsed = json.loads(arguments)
    return _build_result_from_parsed(parsed, model, pr, )

x_parse_submit_review_args__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x_parse_submit_review_args__mutmut_1': x_parse_submit_review_args__mutmut_1, 
    'x_parse_submit_review_args__mutmut_2': x_parse_submit_review_args__mutmut_2, 
    'x_parse_submit_review_args__mutmut_3': x_parse_submit_review_args__mutmut_3, 
    'x_parse_submit_review_args__mutmut_4': x_parse_submit_review_args__mutmut_4, 
    'x_parse_submit_review_args__mutmut_5': x_parse_submit_review_args__mutmut_5, 
    'x_parse_submit_review_args__mutmut_6': x_parse_submit_review_args__mutmut_6, 
    'x_parse_submit_review_args__mutmut_7': x_parse_submit_review_args__mutmut_7, 
    'x_parse_submit_review_args__mutmut_8': x_parse_submit_review_args__mutmut_8, 
    'x_parse_submit_review_args__mutmut_9': x_parse_submit_review_args__mutmut_9, 
    'x_parse_submit_review_args__mutmut_10': x_parse_submit_review_args__mutmut_10, 
    'x_parse_submit_review_args__mutmut_11': x_parse_submit_review_args__mutmut_11, 
    'x_parse_submit_review_args__mutmut_12': x_parse_submit_review_args__mutmut_12
}
x_parse_submit_review_args__mutmut_orig.__name__ = 'x_parse_submit_review_args'


def _build_result_from_parsed(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    args = [parsed, model, pr, timestamp]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x__build_result_from_parsed__mutmut_orig, x__build_result_from_parsed__mutmut_mutants, args, kwargs, None)


def x__build_result_from_parsed__mutmut_orig(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_1(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = None

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_2(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=None,
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_3(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=None,
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_4(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=None,
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_5(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=None,
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_6(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=None,
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_7(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_8(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_9(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_10(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_11(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_12(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get(None, ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_13(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", None),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_14(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get(""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_15(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_16(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("XXpathXX", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_17(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("PATH", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_18(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", "XXXX"),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_19(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get(None, 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_20(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", None),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_21(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get(0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_22(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", ),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_23(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("XXlineXX", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_24(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("LINE", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_25(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 1),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_26(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get(None, ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_27(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", None),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_28(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get(""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_29(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_30(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("XXbodyXX", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_31(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("BODY", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_32(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", "XXXX"),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_33(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get(None, "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_34(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", None),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_35(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_36(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", ),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_37(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("XXseverityXX", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_38(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("SEVERITY", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_39(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "XXinfoXX"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_40(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "INFO"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_41(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get(None),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_42(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("XXstart_lineXX"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_43(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("START_LINE"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_44(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get(None, [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_45(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", None)
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_46(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get([])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_47(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", )
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_48(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("XXcommentsXX", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_49(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("COMMENTS", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_50(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") or c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_51(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get(None) and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_52(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("XXpathXX") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_53(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("PATH") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_54(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get(None)
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_55(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("XXlineXX")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_56(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("LINE")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_57(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = None
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_58(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get(None, "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_59(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", None)
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_60(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_61(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", )
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_62(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("XXverdictXX", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_63(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("VERDICT", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_64(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "XXrequest_changesXX")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_65(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "REQUEST_CHANGES")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_66(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_67(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("XXapproveXX", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_68(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("APPROVE", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_69(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "XXrequest_changesXX"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_70(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "REQUEST_CHANGES"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_71(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = None

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_72(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "XXrequest_changesXX"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_73(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "REQUEST_CHANGES"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_74(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = None
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_75(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get(None, "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_76(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", None)
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_77(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_78(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", )
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_79(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("XXsummaryXX", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_80(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("SUMMARY", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_81(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "XXNo summary provided.XX")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_82(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "no summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_83(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "NO SUMMARY PROVIDED.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_84(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "XX<!-- guardrails-review -->XX" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_85(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- GUARDRAILS-REVIEW -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_86(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_87(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = None

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_88(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=None,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_89(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=None,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_90(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=None,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_91(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=None,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_92(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=None,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_93(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=None,
    )


def x__build_result_from_parsed__mutmut_94(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_95(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        comments=comments,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_96(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        model=model,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_97(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        timestamp=timestamp,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_98(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        pr=pr,
    )


def x__build_result_from_parsed__mutmut_99(parsed: dict, model: str, pr: int, timestamp: str) -> ReviewResult:
    """Build a ReviewResult from a parsed JSON dict."""
    comments = [
        ReviewComment(
            path=c.get("path", ""),
            line=c.get("line", 0),
            body=c.get("body", ""),
            severity=c.get("severity", "info"),
            start_line=c.get("start_line"),
        )
        for c in parsed.get("comments", [])
        if c.get("path") and c.get("line")
    ]

    verdict = parsed.get("verdict", "request_changes")
    if verdict not in ("approve", "request_changes"):
        verdict = "request_changes"

    summary = parsed.get("summary", "No summary provided.")
    if "<!-- guardrails-review -->" not in summary:
        summary = f"<!-- guardrails-review -->\n{summary}"

    return ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=comments,
        model=model,
        timestamp=timestamp,
        )

x__build_result_from_parsed__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x__build_result_from_parsed__mutmut_1': x__build_result_from_parsed__mutmut_1, 
    'x__build_result_from_parsed__mutmut_2': x__build_result_from_parsed__mutmut_2, 
    'x__build_result_from_parsed__mutmut_3': x__build_result_from_parsed__mutmut_3, 
    'x__build_result_from_parsed__mutmut_4': x__build_result_from_parsed__mutmut_4, 
    'x__build_result_from_parsed__mutmut_5': x__build_result_from_parsed__mutmut_5, 
    'x__build_result_from_parsed__mutmut_6': x__build_result_from_parsed__mutmut_6, 
    'x__build_result_from_parsed__mutmut_7': x__build_result_from_parsed__mutmut_7, 
    'x__build_result_from_parsed__mutmut_8': x__build_result_from_parsed__mutmut_8, 
    'x__build_result_from_parsed__mutmut_9': x__build_result_from_parsed__mutmut_9, 
    'x__build_result_from_parsed__mutmut_10': x__build_result_from_parsed__mutmut_10, 
    'x__build_result_from_parsed__mutmut_11': x__build_result_from_parsed__mutmut_11, 
    'x__build_result_from_parsed__mutmut_12': x__build_result_from_parsed__mutmut_12, 
    'x__build_result_from_parsed__mutmut_13': x__build_result_from_parsed__mutmut_13, 
    'x__build_result_from_parsed__mutmut_14': x__build_result_from_parsed__mutmut_14, 
    'x__build_result_from_parsed__mutmut_15': x__build_result_from_parsed__mutmut_15, 
    'x__build_result_from_parsed__mutmut_16': x__build_result_from_parsed__mutmut_16, 
    'x__build_result_from_parsed__mutmut_17': x__build_result_from_parsed__mutmut_17, 
    'x__build_result_from_parsed__mutmut_18': x__build_result_from_parsed__mutmut_18, 
    'x__build_result_from_parsed__mutmut_19': x__build_result_from_parsed__mutmut_19, 
    'x__build_result_from_parsed__mutmut_20': x__build_result_from_parsed__mutmut_20, 
    'x__build_result_from_parsed__mutmut_21': x__build_result_from_parsed__mutmut_21, 
    'x__build_result_from_parsed__mutmut_22': x__build_result_from_parsed__mutmut_22, 
    'x__build_result_from_parsed__mutmut_23': x__build_result_from_parsed__mutmut_23, 
    'x__build_result_from_parsed__mutmut_24': x__build_result_from_parsed__mutmut_24, 
    'x__build_result_from_parsed__mutmut_25': x__build_result_from_parsed__mutmut_25, 
    'x__build_result_from_parsed__mutmut_26': x__build_result_from_parsed__mutmut_26, 
    'x__build_result_from_parsed__mutmut_27': x__build_result_from_parsed__mutmut_27, 
    'x__build_result_from_parsed__mutmut_28': x__build_result_from_parsed__mutmut_28, 
    'x__build_result_from_parsed__mutmut_29': x__build_result_from_parsed__mutmut_29, 
    'x__build_result_from_parsed__mutmut_30': x__build_result_from_parsed__mutmut_30, 
    'x__build_result_from_parsed__mutmut_31': x__build_result_from_parsed__mutmut_31, 
    'x__build_result_from_parsed__mutmut_32': x__build_result_from_parsed__mutmut_32, 
    'x__build_result_from_parsed__mutmut_33': x__build_result_from_parsed__mutmut_33, 
    'x__build_result_from_parsed__mutmut_34': x__build_result_from_parsed__mutmut_34, 
    'x__build_result_from_parsed__mutmut_35': x__build_result_from_parsed__mutmut_35, 
    'x__build_result_from_parsed__mutmut_36': x__build_result_from_parsed__mutmut_36, 
    'x__build_result_from_parsed__mutmut_37': x__build_result_from_parsed__mutmut_37, 
    'x__build_result_from_parsed__mutmut_38': x__build_result_from_parsed__mutmut_38, 
    'x__build_result_from_parsed__mutmut_39': x__build_result_from_parsed__mutmut_39, 
    'x__build_result_from_parsed__mutmut_40': x__build_result_from_parsed__mutmut_40, 
    'x__build_result_from_parsed__mutmut_41': x__build_result_from_parsed__mutmut_41, 
    'x__build_result_from_parsed__mutmut_42': x__build_result_from_parsed__mutmut_42, 
    'x__build_result_from_parsed__mutmut_43': x__build_result_from_parsed__mutmut_43, 
    'x__build_result_from_parsed__mutmut_44': x__build_result_from_parsed__mutmut_44, 
    'x__build_result_from_parsed__mutmut_45': x__build_result_from_parsed__mutmut_45, 
    'x__build_result_from_parsed__mutmut_46': x__build_result_from_parsed__mutmut_46, 
    'x__build_result_from_parsed__mutmut_47': x__build_result_from_parsed__mutmut_47, 
    'x__build_result_from_parsed__mutmut_48': x__build_result_from_parsed__mutmut_48, 
    'x__build_result_from_parsed__mutmut_49': x__build_result_from_parsed__mutmut_49, 
    'x__build_result_from_parsed__mutmut_50': x__build_result_from_parsed__mutmut_50, 
    'x__build_result_from_parsed__mutmut_51': x__build_result_from_parsed__mutmut_51, 
    'x__build_result_from_parsed__mutmut_52': x__build_result_from_parsed__mutmut_52, 
    'x__build_result_from_parsed__mutmut_53': x__build_result_from_parsed__mutmut_53, 
    'x__build_result_from_parsed__mutmut_54': x__build_result_from_parsed__mutmut_54, 
    'x__build_result_from_parsed__mutmut_55': x__build_result_from_parsed__mutmut_55, 
    'x__build_result_from_parsed__mutmut_56': x__build_result_from_parsed__mutmut_56, 
    'x__build_result_from_parsed__mutmut_57': x__build_result_from_parsed__mutmut_57, 
    'x__build_result_from_parsed__mutmut_58': x__build_result_from_parsed__mutmut_58, 
    'x__build_result_from_parsed__mutmut_59': x__build_result_from_parsed__mutmut_59, 
    'x__build_result_from_parsed__mutmut_60': x__build_result_from_parsed__mutmut_60, 
    'x__build_result_from_parsed__mutmut_61': x__build_result_from_parsed__mutmut_61, 
    'x__build_result_from_parsed__mutmut_62': x__build_result_from_parsed__mutmut_62, 
    'x__build_result_from_parsed__mutmut_63': x__build_result_from_parsed__mutmut_63, 
    'x__build_result_from_parsed__mutmut_64': x__build_result_from_parsed__mutmut_64, 
    'x__build_result_from_parsed__mutmut_65': x__build_result_from_parsed__mutmut_65, 
    'x__build_result_from_parsed__mutmut_66': x__build_result_from_parsed__mutmut_66, 
    'x__build_result_from_parsed__mutmut_67': x__build_result_from_parsed__mutmut_67, 
    'x__build_result_from_parsed__mutmut_68': x__build_result_from_parsed__mutmut_68, 
    'x__build_result_from_parsed__mutmut_69': x__build_result_from_parsed__mutmut_69, 
    'x__build_result_from_parsed__mutmut_70': x__build_result_from_parsed__mutmut_70, 
    'x__build_result_from_parsed__mutmut_71': x__build_result_from_parsed__mutmut_71, 
    'x__build_result_from_parsed__mutmut_72': x__build_result_from_parsed__mutmut_72, 
    'x__build_result_from_parsed__mutmut_73': x__build_result_from_parsed__mutmut_73, 
    'x__build_result_from_parsed__mutmut_74': x__build_result_from_parsed__mutmut_74, 
    'x__build_result_from_parsed__mutmut_75': x__build_result_from_parsed__mutmut_75, 
    'x__build_result_from_parsed__mutmut_76': x__build_result_from_parsed__mutmut_76, 
    'x__build_result_from_parsed__mutmut_77': x__build_result_from_parsed__mutmut_77, 
    'x__build_result_from_parsed__mutmut_78': x__build_result_from_parsed__mutmut_78, 
    'x__build_result_from_parsed__mutmut_79': x__build_result_from_parsed__mutmut_79, 
    'x__build_result_from_parsed__mutmut_80': x__build_result_from_parsed__mutmut_80, 
    'x__build_result_from_parsed__mutmut_81': x__build_result_from_parsed__mutmut_81, 
    'x__build_result_from_parsed__mutmut_82': x__build_result_from_parsed__mutmut_82, 
    'x__build_result_from_parsed__mutmut_83': x__build_result_from_parsed__mutmut_83, 
    'x__build_result_from_parsed__mutmut_84': x__build_result_from_parsed__mutmut_84, 
    'x__build_result_from_parsed__mutmut_85': x__build_result_from_parsed__mutmut_85, 
    'x__build_result_from_parsed__mutmut_86': x__build_result_from_parsed__mutmut_86, 
    'x__build_result_from_parsed__mutmut_87': x__build_result_from_parsed__mutmut_87, 
    'x__build_result_from_parsed__mutmut_88': x__build_result_from_parsed__mutmut_88, 
    'x__build_result_from_parsed__mutmut_89': x__build_result_from_parsed__mutmut_89, 
    'x__build_result_from_parsed__mutmut_90': x__build_result_from_parsed__mutmut_90, 
    'x__build_result_from_parsed__mutmut_91': x__build_result_from_parsed__mutmut_91, 
    'x__build_result_from_parsed__mutmut_92': x__build_result_from_parsed__mutmut_92, 
    'x__build_result_from_parsed__mutmut_93': x__build_result_from_parsed__mutmut_93, 
    'x__build_result_from_parsed__mutmut_94': x__build_result_from_parsed__mutmut_94, 
    'x__build_result_from_parsed__mutmut_95': x__build_result_from_parsed__mutmut_95, 
    'x__build_result_from_parsed__mutmut_96': x__build_result_from_parsed__mutmut_96, 
    'x__build_result_from_parsed__mutmut_97': x__build_result_from_parsed__mutmut_97, 
    'x__build_result_from_parsed__mutmut_98': x__build_result_from_parsed__mutmut_98, 
    'x__build_result_from_parsed__mutmut_99': x__build_result_from_parsed__mutmut_99
}
x__build_result_from_parsed__mutmut_orig.__name__ = 'x__build_result_from_parsed'


def _try_parse_json(raw: str) -> dict | None:
    args = [raw]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x__try_parse_json__mutmut_orig, x__try_parse_json__mutmut_mutants, args, kwargs, None)


def x__try_parse_json__mutmut_orig(raw: str) -> dict | None:
    """Attempt to parse JSON, trying raw first then extracting from code blocks."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    match = _JSON_BLOCK_RE.search(raw)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def x__try_parse_json__mutmut_1(raw: str) -> dict | None:
    """Attempt to parse JSON, trying raw first then extracting from code blocks."""
    try:
        return json.loads(None)
    except (json.JSONDecodeError, ValueError):
        pass

    match = _JSON_BLOCK_RE.search(raw)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def x__try_parse_json__mutmut_2(raw: str) -> dict | None:
    """Attempt to parse JSON, trying raw first then extracting from code blocks."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    match = None
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def x__try_parse_json__mutmut_3(raw: str) -> dict | None:
    """Attempt to parse JSON, trying raw first then extracting from code blocks."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    match = _JSON_BLOCK_RE.search(None)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def x__try_parse_json__mutmut_4(raw: str) -> dict | None:
    """Attempt to parse JSON, trying raw first then extracting from code blocks."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    match = _JSON_BLOCK_RE.search(raw)
    if match:
        try:
            return json.loads(None)
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def x__try_parse_json__mutmut_5(raw: str) -> dict | None:
    """Attempt to parse JSON, trying raw first then extracting from code blocks."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    match = _JSON_BLOCK_RE.search(raw)
    if match:
        try:
            return json.loads(match.group(None))
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def x__try_parse_json__mutmut_6(raw: str) -> dict | None:
    """Attempt to parse JSON, trying raw first then extracting from code blocks."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    match = _JSON_BLOCK_RE.search(raw)
    if match:
        try:
            return json.loads(match.group(2))
        except (json.JSONDecodeError, ValueError):
            pass

    return None

x__try_parse_json__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x__try_parse_json__mutmut_1': x__try_parse_json__mutmut_1, 
    'x__try_parse_json__mutmut_2': x__try_parse_json__mutmut_2, 
    'x__try_parse_json__mutmut_3': x__try_parse_json__mutmut_3, 
    'x__try_parse_json__mutmut_4': x__try_parse_json__mutmut_4, 
    'x__try_parse_json__mutmut_5': x__try_parse_json__mutmut_5, 
    'x__try_parse_json__mutmut_6': x__try_parse_json__mutmut_6
}
x__try_parse_json__mutmut_orig.__name__ = 'x__try_parse_json'


def validate_comments(
    comments: list[ReviewComment],
    valid_lines: dict[str, set[int]],
) -> tuple[list[ReviewComment], list[ReviewComment]]:
    args = [comments, valid_lines]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x_validate_comments__mutmut_orig, x_validate_comments__mutmut_mutants, args, kwargs, None)


def x_validate_comments__mutmut_orig(
    comments: list[ReviewComment],
    valid_lines: dict[str, set[int]],
) -> tuple[list[ReviewComment], list[ReviewComment]]:
    """Split comments into valid (on diff lines) and invalid (outside diff).

    Returns:
        Tuple of (valid_comments, invalid_comments).
    """
    valid: list[ReviewComment] = []
    invalid: list[ReviewComment] = []
    for c in comments:
        file_lines = valid_lines.get(c.path, set())
        if c.line in file_lines:
            valid.append(c)
        else:
            invalid.append(c)
    return valid, invalid


def x_validate_comments__mutmut_1(
    comments: list[ReviewComment],
    valid_lines: dict[str, set[int]],
) -> tuple[list[ReviewComment], list[ReviewComment]]:
    """Split comments into valid (on diff lines) and invalid (outside diff).

    Returns:
        Tuple of (valid_comments, invalid_comments).
    """
    valid: list[ReviewComment] = None
    invalid: list[ReviewComment] = []
    for c in comments:
        file_lines = valid_lines.get(c.path, set())
        if c.line in file_lines:
            valid.append(c)
        else:
            invalid.append(c)
    return valid, invalid


def x_validate_comments__mutmut_2(
    comments: list[ReviewComment],
    valid_lines: dict[str, set[int]],
) -> tuple[list[ReviewComment], list[ReviewComment]]:
    """Split comments into valid (on diff lines) and invalid (outside diff).

    Returns:
        Tuple of (valid_comments, invalid_comments).
    """
    valid: list[ReviewComment] = []
    invalid: list[ReviewComment] = None
    for c in comments:
        file_lines = valid_lines.get(c.path, set())
        if c.line in file_lines:
            valid.append(c)
        else:
            invalid.append(c)
    return valid, invalid


def x_validate_comments__mutmut_3(
    comments: list[ReviewComment],
    valid_lines: dict[str, set[int]],
) -> tuple[list[ReviewComment], list[ReviewComment]]:
    """Split comments into valid (on diff lines) and invalid (outside diff).

    Returns:
        Tuple of (valid_comments, invalid_comments).
    """
    valid: list[ReviewComment] = []
    invalid: list[ReviewComment] = []
    for c in comments:
        file_lines = None
        if c.line in file_lines:
            valid.append(c)
        else:
            invalid.append(c)
    return valid, invalid


def x_validate_comments__mutmut_4(
    comments: list[ReviewComment],
    valid_lines: dict[str, set[int]],
) -> tuple[list[ReviewComment], list[ReviewComment]]:
    """Split comments into valid (on diff lines) and invalid (outside diff).

    Returns:
        Tuple of (valid_comments, invalid_comments).
    """
    valid: list[ReviewComment] = []
    invalid: list[ReviewComment] = []
    for c in comments:
        file_lines = valid_lines.get(None, set())
        if c.line in file_lines:
            valid.append(c)
        else:
            invalid.append(c)
    return valid, invalid


def x_validate_comments__mutmut_5(
    comments: list[ReviewComment],
    valid_lines: dict[str, set[int]],
) -> tuple[list[ReviewComment], list[ReviewComment]]:
    """Split comments into valid (on diff lines) and invalid (outside diff).

    Returns:
        Tuple of (valid_comments, invalid_comments).
    """
    valid: list[ReviewComment] = []
    invalid: list[ReviewComment] = []
    for c in comments:
        file_lines = valid_lines.get(c.path, None)
        if c.line in file_lines:
            valid.append(c)
        else:
            invalid.append(c)
    return valid, invalid


def x_validate_comments__mutmut_6(
    comments: list[ReviewComment],
    valid_lines: dict[str, set[int]],
) -> tuple[list[ReviewComment], list[ReviewComment]]:
    """Split comments into valid (on diff lines) and invalid (outside diff).

    Returns:
        Tuple of (valid_comments, invalid_comments).
    """
    valid: list[ReviewComment] = []
    invalid: list[ReviewComment] = []
    for c in comments:
        file_lines = valid_lines.get(set())
        if c.line in file_lines:
            valid.append(c)
        else:
            invalid.append(c)
    return valid, invalid


def x_validate_comments__mutmut_7(
    comments: list[ReviewComment],
    valid_lines: dict[str, set[int]],
) -> tuple[list[ReviewComment], list[ReviewComment]]:
    """Split comments into valid (on diff lines) and invalid (outside diff).

    Returns:
        Tuple of (valid_comments, invalid_comments).
    """
    valid: list[ReviewComment] = []
    invalid: list[ReviewComment] = []
    for c in comments:
        file_lines = valid_lines.get(c.path, )
        if c.line in file_lines:
            valid.append(c)
        else:
            invalid.append(c)
    return valid, invalid


def x_validate_comments__mutmut_8(
    comments: list[ReviewComment],
    valid_lines: dict[str, set[int]],
) -> tuple[list[ReviewComment], list[ReviewComment]]:
    """Split comments into valid (on diff lines) and invalid (outside diff).

    Returns:
        Tuple of (valid_comments, invalid_comments).
    """
    valid: list[ReviewComment] = []
    invalid: list[ReviewComment] = []
    for c in comments:
        file_lines = valid_lines.get(c.path, set())
        if c.line not in file_lines:
            valid.append(c)
        else:
            invalid.append(c)
    return valid, invalid


def x_validate_comments__mutmut_9(
    comments: list[ReviewComment],
    valid_lines: dict[str, set[int]],
) -> tuple[list[ReviewComment], list[ReviewComment]]:
    """Split comments into valid (on diff lines) and invalid (outside diff).

    Returns:
        Tuple of (valid_comments, invalid_comments).
    """
    valid: list[ReviewComment] = []
    invalid: list[ReviewComment] = []
    for c in comments:
        file_lines = valid_lines.get(c.path, set())
        if c.line in file_lines:
            valid.append(None)
        else:
            invalid.append(c)
    return valid, invalid


def x_validate_comments__mutmut_10(
    comments: list[ReviewComment],
    valid_lines: dict[str, set[int]],
) -> tuple[list[ReviewComment], list[ReviewComment]]:
    """Split comments into valid (on diff lines) and invalid (outside diff).

    Returns:
        Tuple of (valid_comments, invalid_comments).
    """
    valid: list[ReviewComment] = []
    invalid: list[ReviewComment] = []
    for c in comments:
        file_lines = valid_lines.get(c.path, set())
        if c.line in file_lines:
            valid.append(c)
        else:
            invalid.append(None)
    return valid, invalid

x_validate_comments__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x_validate_comments__mutmut_1': x_validate_comments__mutmut_1, 
    'x_validate_comments__mutmut_2': x_validate_comments__mutmut_2, 
    'x_validate_comments__mutmut_3': x_validate_comments__mutmut_3, 
    'x_validate_comments__mutmut_4': x_validate_comments__mutmut_4, 
    'x_validate_comments__mutmut_5': x_validate_comments__mutmut_5, 
    'x_validate_comments__mutmut_6': x_validate_comments__mutmut_6, 
    'x_validate_comments__mutmut_7': x_validate_comments__mutmut_7, 
    'x_validate_comments__mutmut_8': x_validate_comments__mutmut_8, 
    'x_validate_comments__mutmut_9': x_validate_comments__mutmut_9, 
    'x_validate_comments__mutmut_10': x_validate_comments__mutmut_10
}
x_validate_comments__mutmut_orig.__name__ = 'x_validate_comments'


def run_review(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    args = [pr]# type: ignore
    kwargs = {'dry_run': dry_run, 'project_dir': project_dir}# type: ignore
    return _mutmut_trampoline(x_run_review__mutmut_orig, x_run_review__mutmut_mutants, args, kwargs, None)


def x_run_review__mutmut_orig(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_1(
    pr: int,
    *,
    dry_run: bool = True,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_2(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = None
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_3(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(None)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_4(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = None
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_5(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(None)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_6(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = None
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_7(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(None)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_8(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = None

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_9(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(None)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_10(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = None
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_11(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(None, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_12(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, None, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_13(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, None, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_14(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, None)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_15(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_16(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_17(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_18(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, )
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_19(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = None

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_20(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(None, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_21(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, None, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_22(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, None, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_23(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, None)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_24(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_25(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_26(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_27(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, )

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_28(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = None

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_29(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(None, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_30(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, None)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_31(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_32(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, )

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_33(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = None
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_34(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary = "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_35(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary -= "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_36(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "XX\n\n---\n**Comments on lines outside diff (could not post inline):**\nXX"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_37(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_38(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**COMMENTS ON LINES OUTSIDE DIFF (COULD NOT POST INLINE):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_39(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary = f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_40(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary -= f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_41(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = None

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_42(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(None, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_43(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, None)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_44(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_45(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, )

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_46(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments - invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_47(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = None

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_48(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=None,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_49(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=None,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_50(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=None,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_51(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=None,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_52(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=None,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_53(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=None,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_54(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_55(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_56(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_57(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_58(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_59(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_60(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(None)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_61(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 1

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_62(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = None
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_63(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = None
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_64(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["XXheadRefOidXX"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_65(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headrefoid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_66(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["HEADREFOID"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_67(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(None, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_68(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, None, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_69(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, None, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_70(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, None, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_71(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, None)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_72(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_73(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_74(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_75(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_76(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, )
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_77(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(None, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_78(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, None)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_79(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_80(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, )
    print(f"Review posted for PR #{pr}: {verdict}")
    return 0


def x_run_review__mutmut_81(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(None)
    return 0


def x_run_review__mutmut_82(
    pr: int,
    *,
    dry_run: bool = False,
    project_dir: Path | None = None,
) -> int:
    """Execute the full review pipeline.

    Dispatches to agentic or oneshot mode based on config.

    Returns 0 on success, 1 on failure.
    """
    config = load_config(project_dir)
    diff = get_pr_diff(pr)
    pr_meta = get_pr_metadata(pr)
    valid_lines = parse_diff_hunks(diff)

    if config.agentic:
        result = _run_agentic_review(config, diff, pr_meta, pr)
    else:
        result = _run_oneshot_review(config, diff, pr_meta, pr)

    valid_comments, invalid_comments = validate_comments(result.comments, valid_lines)

    # Append invalid comments to summary body
    summary = result.summary
    if invalid_comments:
        summary += "\n\n---\n**Comments on lines outside diff (could not post inline):**\n"
        for c in invalid_comments:
            summary += f"\n- `{c.path}:{c.line}` ({c.severity}): {c.body}"

    # Determine final verdict based on severity threshold
    verdict = _compute_verdict(valid_comments + invalid_comments, config)

    final = ReviewResult(
        verdict=verdict,
        summary=summary,
        comments=valid_comments,
        model=result.model,
        timestamp=result.timestamp,
        pr=pr,
    )

    if dry_run:
        _print_dry_run(final)
        return 0

    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    post_review(pr, final, owner, repo, commit_sha)
    save_review(final, project_dir)
    print(f"Review posted for PR #{pr}: {verdict}")
    return 1

x_run_review__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x_run_review__mutmut_1': x_run_review__mutmut_1, 
    'x_run_review__mutmut_2': x_run_review__mutmut_2, 
    'x_run_review__mutmut_3': x_run_review__mutmut_3, 
    'x_run_review__mutmut_4': x_run_review__mutmut_4, 
    'x_run_review__mutmut_5': x_run_review__mutmut_5, 
    'x_run_review__mutmut_6': x_run_review__mutmut_6, 
    'x_run_review__mutmut_7': x_run_review__mutmut_7, 
    'x_run_review__mutmut_8': x_run_review__mutmut_8, 
    'x_run_review__mutmut_9': x_run_review__mutmut_9, 
    'x_run_review__mutmut_10': x_run_review__mutmut_10, 
    'x_run_review__mutmut_11': x_run_review__mutmut_11, 
    'x_run_review__mutmut_12': x_run_review__mutmut_12, 
    'x_run_review__mutmut_13': x_run_review__mutmut_13, 
    'x_run_review__mutmut_14': x_run_review__mutmut_14, 
    'x_run_review__mutmut_15': x_run_review__mutmut_15, 
    'x_run_review__mutmut_16': x_run_review__mutmut_16, 
    'x_run_review__mutmut_17': x_run_review__mutmut_17, 
    'x_run_review__mutmut_18': x_run_review__mutmut_18, 
    'x_run_review__mutmut_19': x_run_review__mutmut_19, 
    'x_run_review__mutmut_20': x_run_review__mutmut_20, 
    'x_run_review__mutmut_21': x_run_review__mutmut_21, 
    'x_run_review__mutmut_22': x_run_review__mutmut_22, 
    'x_run_review__mutmut_23': x_run_review__mutmut_23, 
    'x_run_review__mutmut_24': x_run_review__mutmut_24, 
    'x_run_review__mutmut_25': x_run_review__mutmut_25, 
    'x_run_review__mutmut_26': x_run_review__mutmut_26, 
    'x_run_review__mutmut_27': x_run_review__mutmut_27, 
    'x_run_review__mutmut_28': x_run_review__mutmut_28, 
    'x_run_review__mutmut_29': x_run_review__mutmut_29, 
    'x_run_review__mutmut_30': x_run_review__mutmut_30, 
    'x_run_review__mutmut_31': x_run_review__mutmut_31, 
    'x_run_review__mutmut_32': x_run_review__mutmut_32, 
    'x_run_review__mutmut_33': x_run_review__mutmut_33, 
    'x_run_review__mutmut_34': x_run_review__mutmut_34, 
    'x_run_review__mutmut_35': x_run_review__mutmut_35, 
    'x_run_review__mutmut_36': x_run_review__mutmut_36, 
    'x_run_review__mutmut_37': x_run_review__mutmut_37, 
    'x_run_review__mutmut_38': x_run_review__mutmut_38, 
    'x_run_review__mutmut_39': x_run_review__mutmut_39, 
    'x_run_review__mutmut_40': x_run_review__mutmut_40, 
    'x_run_review__mutmut_41': x_run_review__mutmut_41, 
    'x_run_review__mutmut_42': x_run_review__mutmut_42, 
    'x_run_review__mutmut_43': x_run_review__mutmut_43, 
    'x_run_review__mutmut_44': x_run_review__mutmut_44, 
    'x_run_review__mutmut_45': x_run_review__mutmut_45, 
    'x_run_review__mutmut_46': x_run_review__mutmut_46, 
    'x_run_review__mutmut_47': x_run_review__mutmut_47, 
    'x_run_review__mutmut_48': x_run_review__mutmut_48, 
    'x_run_review__mutmut_49': x_run_review__mutmut_49, 
    'x_run_review__mutmut_50': x_run_review__mutmut_50, 
    'x_run_review__mutmut_51': x_run_review__mutmut_51, 
    'x_run_review__mutmut_52': x_run_review__mutmut_52, 
    'x_run_review__mutmut_53': x_run_review__mutmut_53, 
    'x_run_review__mutmut_54': x_run_review__mutmut_54, 
    'x_run_review__mutmut_55': x_run_review__mutmut_55, 
    'x_run_review__mutmut_56': x_run_review__mutmut_56, 
    'x_run_review__mutmut_57': x_run_review__mutmut_57, 
    'x_run_review__mutmut_58': x_run_review__mutmut_58, 
    'x_run_review__mutmut_59': x_run_review__mutmut_59, 
    'x_run_review__mutmut_60': x_run_review__mutmut_60, 
    'x_run_review__mutmut_61': x_run_review__mutmut_61, 
    'x_run_review__mutmut_62': x_run_review__mutmut_62, 
    'x_run_review__mutmut_63': x_run_review__mutmut_63, 
    'x_run_review__mutmut_64': x_run_review__mutmut_64, 
    'x_run_review__mutmut_65': x_run_review__mutmut_65, 
    'x_run_review__mutmut_66': x_run_review__mutmut_66, 
    'x_run_review__mutmut_67': x_run_review__mutmut_67, 
    'x_run_review__mutmut_68': x_run_review__mutmut_68, 
    'x_run_review__mutmut_69': x_run_review__mutmut_69, 
    'x_run_review__mutmut_70': x_run_review__mutmut_70, 
    'x_run_review__mutmut_71': x_run_review__mutmut_71, 
    'x_run_review__mutmut_72': x_run_review__mutmut_72, 
    'x_run_review__mutmut_73': x_run_review__mutmut_73, 
    'x_run_review__mutmut_74': x_run_review__mutmut_74, 
    'x_run_review__mutmut_75': x_run_review__mutmut_75, 
    'x_run_review__mutmut_76': x_run_review__mutmut_76, 
    'x_run_review__mutmut_77': x_run_review__mutmut_77, 
    'x_run_review__mutmut_78': x_run_review__mutmut_78, 
    'x_run_review__mutmut_79': x_run_review__mutmut_79, 
    'x_run_review__mutmut_80': x_run_review__mutmut_80, 
    'x_run_review__mutmut_81': x_run_review__mutmut_81, 
    'x_run_review__mutmut_82': x_run_review__mutmut_82
}
x_run_review__mutmut_orig.__name__ = 'x_run_review'


def _run_oneshot_review(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    args = [config, diff, pr_meta, pr]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x__run_oneshot_review__mutmut_orig, x__run_oneshot_review__mutmut_mutants, args, kwargs, None)


def x__run_oneshot_review__mutmut_orig(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = build_messages(diff, config, pr_meta)
    raw_response = call_openrouter(messages, config.model)
    return parse_response(raw_response, config.model, pr)


def x__run_oneshot_review__mutmut_1(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = None
    raw_response = call_openrouter(messages, config.model)
    return parse_response(raw_response, config.model, pr)


def x__run_oneshot_review__mutmut_2(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = build_messages(None, config, pr_meta)
    raw_response = call_openrouter(messages, config.model)
    return parse_response(raw_response, config.model, pr)


def x__run_oneshot_review__mutmut_3(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = build_messages(diff, None, pr_meta)
    raw_response = call_openrouter(messages, config.model)
    return parse_response(raw_response, config.model, pr)


def x__run_oneshot_review__mutmut_4(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = build_messages(diff, config, None)
    raw_response = call_openrouter(messages, config.model)
    return parse_response(raw_response, config.model, pr)


def x__run_oneshot_review__mutmut_5(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = build_messages(config, pr_meta)
    raw_response = call_openrouter(messages, config.model)
    return parse_response(raw_response, config.model, pr)


def x__run_oneshot_review__mutmut_6(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = build_messages(diff, pr_meta)
    raw_response = call_openrouter(messages, config.model)
    return parse_response(raw_response, config.model, pr)


def x__run_oneshot_review__mutmut_7(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = build_messages(diff, config, )
    raw_response = call_openrouter(messages, config.model)
    return parse_response(raw_response, config.model, pr)


def x__run_oneshot_review__mutmut_8(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = build_messages(diff, config, pr_meta)
    raw_response = None
    return parse_response(raw_response, config.model, pr)


def x__run_oneshot_review__mutmut_9(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = build_messages(diff, config, pr_meta)
    raw_response = call_openrouter(None, config.model)
    return parse_response(raw_response, config.model, pr)


def x__run_oneshot_review__mutmut_10(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = build_messages(diff, config, pr_meta)
    raw_response = call_openrouter(messages, None)
    return parse_response(raw_response, config.model, pr)


def x__run_oneshot_review__mutmut_11(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = build_messages(diff, config, pr_meta)
    raw_response = call_openrouter(config.model)
    return parse_response(raw_response, config.model, pr)


def x__run_oneshot_review__mutmut_12(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = build_messages(diff, config, pr_meta)
    raw_response = call_openrouter(messages, )
    return parse_response(raw_response, config.model, pr)


def x__run_oneshot_review__mutmut_13(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = build_messages(diff, config, pr_meta)
    raw_response = call_openrouter(messages, config.model)
    return parse_response(None, config.model, pr)


def x__run_oneshot_review__mutmut_14(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = build_messages(diff, config, pr_meta)
    raw_response = call_openrouter(messages, config.model)
    return parse_response(raw_response, None, pr)


def x__run_oneshot_review__mutmut_15(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = build_messages(diff, config, pr_meta)
    raw_response = call_openrouter(messages, config.model)
    return parse_response(raw_response, config.model, None)


def x__run_oneshot_review__mutmut_16(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = build_messages(diff, config, pr_meta)
    raw_response = call_openrouter(messages, config.model)
    return parse_response(config.model, pr)


def x__run_oneshot_review__mutmut_17(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = build_messages(diff, config, pr_meta)
    raw_response = call_openrouter(messages, config.model)
    return parse_response(raw_response, pr)


def x__run_oneshot_review__mutmut_18(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the original single-shot review (diff → LLM JSON → result)."""
    messages = build_messages(diff, config, pr_meta)
    raw_response = call_openrouter(messages, config.model)
    return parse_response(raw_response, config.model, )

x__run_oneshot_review__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x__run_oneshot_review__mutmut_1': x__run_oneshot_review__mutmut_1, 
    'x__run_oneshot_review__mutmut_2': x__run_oneshot_review__mutmut_2, 
    'x__run_oneshot_review__mutmut_3': x__run_oneshot_review__mutmut_3, 
    'x__run_oneshot_review__mutmut_4': x__run_oneshot_review__mutmut_4, 
    'x__run_oneshot_review__mutmut_5': x__run_oneshot_review__mutmut_5, 
    'x__run_oneshot_review__mutmut_6': x__run_oneshot_review__mutmut_6, 
    'x__run_oneshot_review__mutmut_7': x__run_oneshot_review__mutmut_7, 
    'x__run_oneshot_review__mutmut_8': x__run_oneshot_review__mutmut_8, 
    'x__run_oneshot_review__mutmut_9': x__run_oneshot_review__mutmut_9, 
    'x__run_oneshot_review__mutmut_10': x__run_oneshot_review__mutmut_10, 
    'x__run_oneshot_review__mutmut_11': x__run_oneshot_review__mutmut_11, 
    'x__run_oneshot_review__mutmut_12': x__run_oneshot_review__mutmut_12, 
    'x__run_oneshot_review__mutmut_13': x__run_oneshot_review__mutmut_13, 
    'x__run_oneshot_review__mutmut_14': x__run_oneshot_review__mutmut_14, 
    'x__run_oneshot_review__mutmut_15': x__run_oneshot_review__mutmut_15, 
    'x__run_oneshot_review__mutmut_16': x__run_oneshot_review__mutmut_16, 
    'x__run_oneshot_review__mutmut_17': x__run_oneshot_review__mutmut_17, 
    'x__run_oneshot_review__mutmut_18': x__run_oneshot_review__mutmut_18
}
x__run_oneshot_review__mutmut_orig.__name__ = 'x__run_oneshot_review'


def _run_agentic_review(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    args = [config, diff, pr_meta, pr]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x__run_agentic_review__mutmut_orig, x__run_agentic_review__mutmut_mutants, args, kwargs, None)


def x__run_agentic_review__mutmut_orig(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_1(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = None
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_2(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = None
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_3(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["XXheadRefOidXX"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_4(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headrefoid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_5(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["HEADREFOID"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_6(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = None

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_7(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=None, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_8(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=None, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_9(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=None, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_10(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=None)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_11(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_12(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_13(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_14(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, )

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_15(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = None

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_16(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(None, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_17(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, None, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_18(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, None)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_19(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_20(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_21(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, )

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_22(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(None):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_23(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = ""
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_24(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration != config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_25(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations + 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_26(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 2:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_27(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = None

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_28(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"XXtypeXX": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_29(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"TYPE": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_30(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "XXfunctionXX", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_31(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "FUNCTION", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_32(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "XXfunctionXX": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_33(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "FUNCTION": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_34(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"XXnameXX": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_35(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"NAME": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_36(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "XXsubmit_reviewXX"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_37(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "SUBMIT_REVIEW"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_38(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = None
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_39(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                None,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_40(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                None,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_41(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=None,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_42(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=None,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_43(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_44(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_45(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_46(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_47(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning(None)
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_48(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("XXAgentic API call failed, falling back to oneshot reviewXX")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_49(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("agentic api call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_50(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("AGENTIC API CALL FAILED, FALLING BACK TO ONESHOT REVIEW")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_51(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(None, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_52(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, None, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_53(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, None, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_54(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, None)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_55(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_56(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_57(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_58(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, )

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_59(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = None
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_60(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "XXroleXX": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_61(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "ROLE": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_62(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "XXassistantXX",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_63(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "ASSISTANT",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_64(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "XXcontentXX": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_65(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "CONTENT": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_66(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "XXtool_callsXX": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_67(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "TOOL_CALLS": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_68(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "XXidXX": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_69(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "ID": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_70(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "XXtypeXX": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_71(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "TYPE": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_72(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "XXfunctionXX",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_73(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "FUNCTION",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_74(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "XXfunctionXX": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_75(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "FUNCTION": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_76(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"XXnameXX": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_77(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"NAME": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_78(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "XXargumentsXX": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_79(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "ARGUMENTS": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_80(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(None)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_81(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name != "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_82(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "XXsubmit_reviewXX":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_83(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "SUBMIT_REVIEW":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_84(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(None, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_85(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, None, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_86(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, None)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_87(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_88(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_89(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, )

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_90(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = None
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_91(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(None, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_92(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, None, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_93(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, None)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_94(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_95(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_96(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_97(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    None
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_98(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "XXroleXX": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_99(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "ROLE": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_100(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "XXtoolXX",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_101(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "TOOL",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_102(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "XXtool_call_idXX": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_103(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "TOOL_CALL_ID": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_104(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "XXcontentXX": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_105(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "CONTENT": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_106(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            break

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_107(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(None, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_108(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, None, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_109(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, None)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_110(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_111(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_112(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, )

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_113(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        return

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_114(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        None,
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_115(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        None,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_116(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_117(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_118(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "XXAgentic loop exhausted %d iterations without submit_reviewXX",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_119(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_120(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "AGENTIC LOOP EXHAUSTED %D ITERATIONS WITHOUT SUBMIT_REVIEW",
        config.max_iterations,
    )
    return parse_response("", config.model, pr)


def x__run_agentic_review__mutmut_121(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response(None, config.model, pr)


def x__run_agentic_review__mutmut_122(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", None, pr)


def x__run_agentic_review__mutmut_123(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, None)


def x__run_agentic_review__mutmut_124(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response(config.model, pr)


def x__run_agentic_review__mutmut_125(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", pr)


def x__run_agentic_review__mutmut_126(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("", config.model, )


def x__run_agentic_review__mutmut_127(
    config: ReviewConfig,
    diff: str,
    pr_meta: dict[str, str],
    pr: int,
) -> ReviewResult:
    """Run the agentic tool-use review loop.

    The LLM can call tools to gather context before submitting its review.
    Falls back to oneshot on tool-use API errors.
    """
    owner, repo = get_repo_info()
    commit_sha = pr_meta["headRefOid"]
    tool_ctx = ToolContext(pr=pr, owner=owner, repo=repo, commit_sha=commit_sha)

    messages: list[dict[str, Any]] = build_agentic_messages(diff, config, pr_meta)

    for iteration in range(config.max_iterations):
        # On the last iteration, force submit_review
        tool_choice: dict[str, Any] | str | None = None
        if iteration == config.max_iterations - 1:
            tool_choice = {"type": "function", "function": {"name": "submit_review"}}

        try:
            response = call_openrouter_tools(
                messages,
                config.model,
                tools=TOOL_DEFINITIONS,
                tool_choice=tool_choice,
            )
        except RuntimeError:
            logger.warning("Agentic API call failed, falling back to oneshot review")
            return _run_oneshot_review(config, diff, pr_meta, pr)

        # Check for tool calls
        if response.tool_calls:
            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                if tc.name == "submit_review":
                    return parse_submit_review_args(tc.arguments, config.model, pr)

                # Execute tool and append result
                tool_result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )
            continue

        # No tool calls — model returned content directly (fallback parse)
        if response.content:
            return parse_response(response.content, config.model, pr)

        # Empty response — shouldn't happen, but handle gracefully
        break

    # Max iterations exhausted without submit_review — parse last content if available
    logger.warning(
        "Agentic loop exhausted %d iterations without submit_review",
        config.max_iterations,
    )
    return parse_response("XXXX", config.model, pr)

x__run_agentic_review__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x__run_agentic_review__mutmut_1': x__run_agentic_review__mutmut_1, 
    'x__run_agentic_review__mutmut_2': x__run_agentic_review__mutmut_2, 
    'x__run_agentic_review__mutmut_3': x__run_agentic_review__mutmut_3, 
    'x__run_agentic_review__mutmut_4': x__run_agentic_review__mutmut_4, 
    'x__run_agentic_review__mutmut_5': x__run_agentic_review__mutmut_5, 
    'x__run_agentic_review__mutmut_6': x__run_agentic_review__mutmut_6, 
    'x__run_agentic_review__mutmut_7': x__run_agentic_review__mutmut_7, 
    'x__run_agentic_review__mutmut_8': x__run_agentic_review__mutmut_8, 
    'x__run_agentic_review__mutmut_9': x__run_agentic_review__mutmut_9, 
    'x__run_agentic_review__mutmut_10': x__run_agentic_review__mutmut_10, 
    'x__run_agentic_review__mutmut_11': x__run_agentic_review__mutmut_11, 
    'x__run_agentic_review__mutmut_12': x__run_agentic_review__mutmut_12, 
    'x__run_agentic_review__mutmut_13': x__run_agentic_review__mutmut_13, 
    'x__run_agentic_review__mutmut_14': x__run_agentic_review__mutmut_14, 
    'x__run_agentic_review__mutmut_15': x__run_agentic_review__mutmut_15, 
    'x__run_agentic_review__mutmut_16': x__run_agentic_review__mutmut_16, 
    'x__run_agentic_review__mutmut_17': x__run_agentic_review__mutmut_17, 
    'x__run_agentic_review__mutmut_18': x__run_agentic_review__mutmut_18, 
    'x__run_agentic_review__mutmut_19': x__run_agentic_review__mutmut_19, 
    'x__run_agentic_review__mutmut_20': x__run_agentic_review__mutmut_20, 
    'x__run_agentic_review__mutmut_21': x__run_agentic_review__mutmut_21, 
    'x__run_agentic_review__mutmut_22': x__run_agentic_review__mutmut_22, 
    'x__run_agentic_review__mutmut_23': x__run_agentic_review__mutmut_23, 
    'x__run_agentic_review__mutmut_24': x__run_agentic_review__mutmut_24, 
    'x__run_agentic_review__mutmut_25': x__run_agentic_review__mutmut_25, 
    'x__run_agentic_review__mutmut_26': x__run_agentic_review__mutmut_26, 
    'x__run_agentic_review__mutmut_27': x__run_agentic_review__mutmut_27, 
    'x__run_agentic_review__mutmut_28': x__run_agentic_review__mutmut_28, 
    'x__run_agentic_review__mutmut_29': x__run_agentic_review__mutmut_29, 
    'x__run_agentic_review__mutmut_30': x__run_agentic_review__mutmut_30, 
    'x__run_agentic_review__mutmut_31': x__run_agentic_review__mutmut_31, 
    'x__run_agentic_review__mutmut_32': x__run_agentic_review__mutmut_32, 
    'x__run_agentic_review__mutmut_33': x__run_agentic_review__mutmut_33, 
    'x__run_agentic_review__mutmut_34': x__run_agentic_review__mutmut_34, 
    'x__run_agentic_review__mutmut_35': x__run_agentic_review__mutmut_35, 
    'x__run_agentic_review__mutmut_36': x__run_agentic_review__mutmut_36, 
    'x__run_agentic_review__mutmut_37': x__run_agentic_review__mutmut_37, 
    'x__run_agentic_review__mutmut_38': x__run_agentic_review__mutmut_38, 
    'x__run_agentic_review__mutmut_39': x__run_agentic_review__mutmut_39, 
    'x__run_agentic_review__mutmut_40': x__run_agentic_review__mutmut_40, 
    'x__run_agentic_review__mutmut_41': x__run_agentic_review__mutmut_41, 
    'x__run_agentic_review__mutmut_42': x__run_agentic_review__mutmut_42, 
    'x__run_agentic_review__mutmut_43': x__run_agentic_review__mutmut_43, 
    'x__run_agentic_review__mutmut_44': x__run_agentic_review__mutmut_44, 
    'x__run_agentic_review__mutmut_45': x__run_agentic_review__mutmut_45, 
    'x__run_agentic_review__mutmut_46': x__run_agentic_review__mutmut_46, 
    'x__run_agentic_review__mutmut_47': x__run_agentic_review__mutmut_47, 
    'x__run_agentic_review__mutmut_48': x__run_agentic_review__mutmut_48, 
    'x__run_agentic_review__mutmut_49': x__run_agentic_review__mutmut_49, 
    'x__run_agentic_review__mutmut_50': x__run_agentic_review__mutmut_50, 
    'x__run_agentic_review__mutmut_51': x__run_agentic_review__mutmut_51, 
    'x__run_agentic_review__mutmut_52': x__run_agentic_review__mutmut_52, 
    'x__run_agentic_review__mutmut_53': x__run_agentic_review__mutmut_53, 
    'x__run_agentic_review__mutmut_54': x__run_agentic_review__mutmut_54, 
    'x__run_agentic_review__mutmut_55': x__run_agentic_review__mutmut_55, 
    'x__run_agentic_review__mutmut_56': x__run_agentic_review__mutmut_56, 
    'x__run_agentic_review__mutmut_57': x__run_agentic_review__mutmut_57, 
    'x__run_agentic_review__mutmut_58': x__run_agentic_review__mutmut_58, 
    'x__run_agentic_review__mutmut_59': x__run_agentic_review__mutmut_59, 
    'x__run_agentic_review__mutmut_60': x__run_agentic_review__mutmut_60, 
    'x__run_agentic_review__mutmut_61': x__run_agentic_review__mutmut_61, 
    'x__run_agentic_review__mutmut_62': x__run_agentic_review__mutmut_62, 
    'x__run_agentic_review__mutmut_63': x__run_agentic_review__mutmut_63, 
    'x__run_agentic_review__mutmut_64': x__run_agentic_review__mutmut_64, 
    'x__run_agentic_review__mutmut_65': x__run_agentic_review__mutmut_65, 
    'x__run_agentic_review__mutmut_66': x__run_agentic_review__mutmut_66, 
    'x__run_agentic_review__mutmut_67': x__run_agentic_review__mutmut_67, 
    'x__run_agentic_review__mutmut_68': x__run_agentic_review__mutmut_68, 
    'x__run_agentic_review__mutmut_69': x__run_agentic_review__mutmut_69, 
    'x__run_agentic_review__mutmut_70': x__run_agentic_review__mutmut_70, 
    'x__run_agentic_review__mutmut_71': x__run_agentic_review__mutmut_71, 
    'x__run_agentic_review__mutmut_72': x__run_agentic_review__mutmut_72, 
    'x__run_agentic_review__mutmut_73': x__run_agentic_review__mutmut_73, 
    'x__run_agentic_review__mutmut_74': x__run_agentic_review__mutmut_74, 
    'x__run_agentic_review__mutmut_75': x__run_agentic_review__mutmut_75, 
    'x__run_agentic_review__mutmut_76': x__run_agentic_review__mutmut_76, 
    'x__run_agentic_review__mutmut_77': x__run_agentic_review__mutmut_77, 
    'x__run_agentic_review__mutmut_78': x__run_agentic_review__mutmut_78, 
    'x__run_agentic_review__mutmut_79': x__run_agentic_review__mutmut_79, 
    'x__run_agentic_review__mutmut_80': x__run_agentic_review__mutmut_80, 
    'x__run_agentic_review__mutmut_81': x__run_agentic_review__mutmut_81, 
    'x__run_agentic_review__mutmut_82': x__run_agentic_review__mutmut_82, 
    'x__run_agentic_review__mutmut_83': x__run_agentic_review__mutmut_83, 
    'x__run_agentic_review__mutmut_84': x__run_agentic_review__mutmut_84, 
    'x__run_agentic_review__mutmut_85': x__run_agentic_review__mutmut_85, 
    'x__run_agentic_review__mutmut_86': x__run_agentic_review__mutmut_86, 
    'x__run_agentic_review__mutmut_87': x__run_agentic_review__mutmut_87, 
    'x__run_agentic_review__mutmut_88': x__run_agentic_review__mutmut_88, 
    'x__run_agentic_review__mutmut_89': x__run_agentic_review__mutmut_89, 
    'x__run_agentic_review__mutmut_90': x__run_agentic_review__mutmut_90, 
    'x__run_agentic_review__mutmut_91': x__run_agentic_review__mutmut_91, 
    'x__run_agentic_review__mutmut_92': x__run_agentic_review__mutmut_92, 
    'x__run_agentic_review__mutmut_93': x__run_agentic_review__mutmut_93, 
    'x__run_agentic_review__mutmut_94': x__run_agentic_review__mutmut_94, 
    'x__run_agentic_review__mutmut_95': x__run_agentic_review__mutmut_95, 
    'x__run_agentic_review__mutmut_96': x__run_agentic_review__mutmut_96, 
    'x__run_agentic_review__mutmut_97': x__run_agentic_review__mutmut_97, 
    'x__run_agentic_review__mutmut_98': x__run_agentic_review__mutmut_98, 
    'x__run_agentic_review__mutmut_99': x__run_agentic_review__mutmut_99, 
    'x__run_agentic_review__mutmut_100': x__run_agentic_review__mutmut_100, 
    'x__run_agentic_review__mutmut_101': x__run_agentic_review__mutmut_101, 
    'x__run_agentic_review__mutmut_102': x__run_agentic_review__mutmut_102, 
    'x__run_agentic_review__mutmut_103': x__run_agentic_review__mutmut_103, 
    'x__run_agentic_review__mutmut_104': x__run_agentic_review__mutmut_104, 
    'x__run_agentic_review__mutmut_105': x__run_agentic_review__mutmut_105, 
    'x__run_agentic_review__mutmut_106': x__run_agentic_review__mutmut_106, 
    'x__run_agentic_review__mutmut_107': x__run_agentic_review__mutmut_107, 
    'x__run_agentic_review__mutmut_108': x__run_agentic_review__mutmut_108, 
    'x__run_agentic_review__mutmut_109': x__run_agentic_review__mutmut_109, 
    'x__run_agentic_review__mutmut_110': x__run_agentic_review__mutmut_110, 
    'x__run_agentic_review__mutmut_111': x__run_agentic_review__mutmut_111, 
    'x__run_agentic_review__mutmut_112': x__run_agentic_review__mutmut_112, 
    'x__run_agentic_review__mutmut_113': x__run_agentic_review__mutmut_113, 
    'x__run_agentic_review__mutmut_114': x__run_agentic_review__mutmut_114, 
    'x__run_agentic_review__mutmut_115': x__run_agentic_review__mutmut_115, 
    'x__run_agentic_review__mutmut_116': x__run_agentic_review__mutmut_116, 
    'x__run_agentic_review__mutmut_117': x__run_agentic_review__mutmut_117, 
    'x__run_agentic_review__mutmut_118': x__run_agentic_review__mutmut_118, 
    'x__run_agentic_review__mutmut_119': x__run_agentic_review__mutmut_119, 
    'x__run_agentic_review__mutmut_120': x__run_agentic_review__mutmut_120, 
    'x__run_agentic_review__mutmut_121': x__run_agentic_review__mutmut_121, 
    'x__run_agentic_review__mutmut_122': x__run_agentic_review__mutmut_122, 
    'x__run_agentic_review__mutmut_123': x__run_agentic_review__mutmut_123, 
    'x__run_agentic_review__mutmut_124': x__run_agentic_review__mutmut_124, 
    'x__run_agentic_review__mutmut_125': x__run_agentic_review__mutmut_125, 
    'x__run_agentic_review__mutmut_126': x__run_agentic_review__mutmut_126, 
    'x__run_agentic_review__mutmut_127': x__run_agentic_review__mutmut_127
}
x__run_agentic_review__mutmut_orig.__name__ = 'x__run_agentic_review'


def _compute_verdict(comments: list[ReviewComment], config: ReviewConfig) -> str:
    args = [comments, config]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x__compute_verdict__mutmut_orig, x__compute_verdict__mutmut_mutants, args, kwargs, None)


def x__compute_verdict__mutmut_orig(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = {"error"}
    if config.severity_threshold == "warning":
        blocking.add("warning")

    has_blocking = any(c.severity in blocking for c in comments)

    if has_blocking:
        return "request_changes"
    if config.auto_approve:
        return "approve"
    return "request_changes"


def x__compute_verdict__mutmut_1(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = None
    if config.severity_threshold == "warning":
        blocking.add("warning")

    has_blocking = any(c.severity in blocking for c in comments)

    if has_blocking:
        return "request_changes"
    if config.auto_approve:
        return "approve"
    return "request_changes"


def x__compute_verdict__mutmut_2(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = {"XXerrorXX"}
    if config.severity_threshold == "warning":
        blocking.add("warning")

    has_blocking = any(c.severity in blocking for c in comments)

    if has_blocking:
        return "request_changes"
    if config.auto_approve:
        return "approve"
    return "request_changes"


def x__compute_verdict__mutmut_3(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = {"ERROR"}
    if config.severity_threshold == "warning":
        blocking.add("warning")

    has_blocking = any(c.severity in blocking for c in comments)

    if has_blocking:
        return "request_changes"
    if config.auto_approve:
        return "approve"
    return "request_changes"


def x__compute_verdict__mutmut_4(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = {"error"}
    if config.severity_threshold != "warning":
        blocking.add("warning")

    has_blocking = any(c.severity in blocking for c in comments)

    if has_blocking:
        return "request_changes"
    if config.auto_approve:
        return "approve"
    return "request_changes"


def x__compute_verdict__mutmut_5(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = {"error"}
    if config.severity_threshold == "XXwarningXX":
        blocking.add("warning")

    has_blocking = any(c.severity in blocking for c in comments)

    if has_blocking:
        return "request_changes"
    if config.auto_approve:
        return "approve"
    return "request_changes"


def x__compute_verdict__mutmut_6(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = {"error"}
    if config.severity_threshold == "WARNING":
        blocking.add("warning")

    has_blocking = any(c.severity in blocking for c in comments)

    if has_blocking:
        return "request_changes"
    if config.auto_approve:
        return "approve"
    return "request_changes"


def x__compute_verdict__mutmut_7(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = {"error"}
    if config.severity_threshold == "warning":
        blocking.add(None)

    has_blocking = any(c.severity in blocking for c in comments)

    if has_blocking:
        return "request_changes"
    if config.auto_approve:
        return "approve"
    return "request_changes"


def x__compute_verdict__mutmut_8(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = {"error"}
    if config.severity_threshold == "warning":
        blocking.add("XXwarningXX")

    has_blocking = any(c.severity in blocking for c in comments)

    if has_blocking:
        return "request_changes"
    if config.auto_approve:
        return "approve"
    return "request_changes"


def x__compute_verdict__mutmut_9(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = {"error"}
    if config.severity_threshold == "warning":
        blocking.add("WARNING")

    has_blocking = any(c.severity in blocking for c in comments)

    if has_blocking:
        return "request_changes"
    if config.auto_approve:
        return "approve"
    return "request_changes"


def x__compute_verdict__mutmut_10(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = {"error"}
    if config.severity_threshold == "warning":
        blocking.add("warning")

    has_blocking = None

    if has_blocking:
        return "request_changes"
    if config.auto_approve:
        return "approve"
    return "request_changes"


def x__compute_verdict__mutmut_11(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = {"error"}
    if config.severity_threshold == "warning":
        blocking.add("warning")

    has_blocking = any(None)

    if has_blocking:
        return "request_changes"
    if config.auto_approve:
        return "approve"
    return "request_changes"


def x__compute_verdict__mutmut_12(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = {"error"}
    if config.severity_threshold == "warning":
        blocking.add("warning")

    has_blocking = any(c.severity not in blocking for c in comments)

    if has_blocking:
        return "request_changes"
    if config.auto_approve:
        return "approve"
    return "request_changes"


def x__compute_verdict__mutmut_13(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = {"error"}
    if config.severity_threshold == "warning":
        blocking.add("warning")

    has_blocking = any(c.severity in blocking for c in comments)

    if has_blocking:
        return "XXrequest_changesXX"
    if config.auto_approve:
        return "approve"
    return "request_changes"


def x__compute_verdict__mutmut_14(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = {"error"}
    if config.severity_threshold == "warning":
        blocking.add("warning")

    has_blocking = any(c.severity in blocking for c in comments)

    if has_blocking:
        return "REQUEST_CHANGES"
    if config.auto_approve:
        return "approve"
    return "request_changes"


def x__compute_verdict__mutmut_15(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = {"error"}
    if config.severity_threshold == "warning":
        blocking.add("warning")

    has_blocking = any(c.severity in blocking for c in comments)

    if has_blocking:
        return "request_changes"
    if config.auto_approve:
        return "XXapproveXX"
    return "request_changes"


def x__compute_verdict__mutmut_16(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = {"error"}
    if config.severity_threshold == "warning":
        blocking.add("warning")

    has_blocking = any(c.severity in blocking for c in comments)

    if has_blocking:
        return "request_changes"
    if config.auto_approve:
        return "APPROVE"
    return "request_changes"


def x__compute_verdict__mutmut_17(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = {"error"}
    if config.severity_threshold == "warning":
        blocking.add("warning")

    has_blocking = any(c.severity in blocking for c in comments)

    if has_blocking:
        return "request_changes"
    if config.auto_approve:
        return "approve"
    return "XXrequest_changesXX"


def x__compute_verdict__mutmut_18(comments: list[ReviewComment], config: ReviewConfig) -> str:
    """Determine verdict based on comment severities and config threshold."""
    blocking = {"error"}
    if config.severity_threshold == "warning":
        blocking.add("warning")

    has_blocking = any(c.severity in blocking for c in comments)

    if has_blocking:
        return "request_changes"
    if config.auto_approve:
        return "approve"
    return "REQUEST_CHANGES"

x__compute_verdict__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x__compute_verdict__mutmut_1': x__compute_verdict__mutmut_1, 
    'x__compute_verdict__mutmut_2': x__compute_verdict__mutmut_2, 
    'x__compute_verdict__mutmut_3': x__compute_verdict__mutmut_3, 
    'x__compute_verdict__mutmut_4': x__compute_verdict__mutmut_4, 
    'x__compute_verdict__mutmut_5': x__compute_verdict__mutmut_5, 
    'x__compute_verdict__mutmut_6': x__compute_verdict__mutmut_6, 
    'x__compute_verdict__mutmut_7': x__compute_verdict__mutmut_7, 
    'x__compute_verdict__mutmut_8': x__compute_verdict__mutmut_8, 
    'x__compute_verdict__mutmut_9': x__compute_verdict__mutmut_9, 
    'x__compute_verdict__mutmut_10': x__compute_verdict__mutmut_10, 
    'x__compute_verdict__mutmut_11': x__compute_verdict__mutmut_11, 
    'x__compute_verdict__mutmut_12': x__compute_verdict__mutmut_12, 
    'x__compute_verdict__mutmut_13': x__compute_verdict__mutmut_13, 
    'x__compute_verdict__mutmut_14': x__compute_verdict__mutmut_14, 
    'x__compute_verdict__mutmut_15': x__compute_verdict__mutmut_15, 
    'x__compute_verdict__mutmut_16': x__compute_verdict__mutmut_16, 
    'x__compute_verdict__mutmut_17': x__compute_verdict__mutmut_17, 
    'x__compute_verdict__mutmut_18': x__compute_verdict__mutmut_18
}
x__compute_verdict__mutmut_orig.__name__ = 'x__compute_verdict'


def _print_dry_run(result: ReviewResult) -> None:
    args = [result]# type: ignore
    kwargs = {}# type: ignore
    return _mutmut_trampoline(x__print_dry_run__mutmut_orig, x__print_dry_run__mutmut_mutants, args, kwargs, None)


def x__print_dry_run__mutmut_orig(result: ReviewResult) -> None:
    """Print review result to stdout without posting."""
    print(f"=== Dry Run: PR #{result.pr} ===")
    print(f"Verdict: {result.verdict}")
    print(f"Model: {result.model}")
    print(f"\n{result.summary}")
    if result.comments:
        print(f"\n--- {len(result.comments)} inline comment(s) ---")
        for c in result.comments:
            print(f"  [{c.severity}] {c.path}:{c.line} — {c.body}")


def x__print_dry_run__mutmut_1(result: ReviewResult) -> None:
    """Print review result to stdout without posting."""
    print(None)
    print(f"Verdict: {result.verdict}")
    print(f"Model: {result.model}")
    print(f"\n{result.summary}")
    if result.comments:
        print(f"\n--- {len(result.comments)} inline comment(s) ---")
        for c in result.comments:
            print(f"  [{c.severity}] {c.path}:{c.line} — {c.body}")


def x__print_dry_run__mutmut_2(result: ReviewResult) -> None:
    """Print review result to stdout without posting."""
    print(f"=== Dry Run: PR #{result.pr} ===")
    print(None)
    print(f"Model: {result.model}")
    print(f"\n{result.summary}")
    if result.comments:
        print(f"\n--- {len(result.comments)} inline comment(s) ---")
        for c in result.comments:
            print(f"  [{c.severity}] {c.path}:{c.line} — {c.body}")


def x__print_dry_run__mutmut_3(result: ReviewResult) -> None:
    """Print review result to stdout without posting."""
    print(f"=== Dry Run: PR #{result.pr} ===")
    print(f"Verdict: {result.verdict}")
    print(None)
    print(f"\n{result.summary}")
    if result.comments:
        print(f"\n--- {len(result.comments)} inline comment(s) ---")
        for c in result.comments:
            print(f"  [{c.severity}] {c.path}:{c.line} — {c.body}")


def x__print_dry_run__mutmut_4(result: ReviewResult) -> None:
    """Print review result to stdout without posting."""
    print(f"=== Dry Run: PR #{result.pr} ===")
    print(f"Verdict: {result.verdict}")
    print(f"Model: {result.model}")
    print(None)
    if result.comments:
        print(f"\n--- {len(result.comments)} inline comment(s) ---")
        for c in result.comments:
            print(f"  [{c.severity}] {c.path}:{c.line} — {c.body}")


def x__print_dry_run__mutmut_5(result: ReviewResult) -> None:
    """Print review result to stdout without posting."""
    print(f"=== Dry Run: PR #{result.pr} ===")
    print(f"Verdict: {result.verdict}")
    print(f"Model: {result.model}")
    print(f"\n{result.summary}")
    if result.comments:
        print(None)
        for c in result.comments:
            print(f"  [{c.severity}] {c.path}:{c.line} — {c.body}")


def x__print_dry_run__mutmut_6(result: ReviewResult) -> None:
    """Print review result to stdout without posting."""
    print(f"=== Dry Run: PR #{result.pr} ===")
    print(f"Verdict: {result.verdict}")
    print(f"Model: {result.model}")
    print(f"\n{result.summary}")
    if result.comments:
        print(f"\n--- {len(result.comments)} inline comment(s) ---")
        for c in result.comments:
            print(None)

x__print_dry_run__mutmut_mutants : ClassVar[MutantDict] = { # type: ignore
'x__print_dry_run__mutmut_1': x__print_dry_run__mutmut_1, 
    'x__print_dry_run__mutmut_2': x__print_dry_run__mutmut_2, 
    'x__print_dry_run__mutmut_3': x__print_dry_run__mutmut_3, 
    'x__print_dry_run__mutmut_4': x__print_dry_run__mutmut_4, 
    'x__print_dry_run__mutmut_5': x__print_dry_run__mutmut_5, 
    'x__print_dry_run__mutmut_6': x__print_dry_run__mutmut_6
}
x__print_dry_run__mutmut_orig.__name__ = 'x__print_dry_run'
