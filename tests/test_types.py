"""Tests for guardrails_review.types — TokenBudget and updated dataclasses."""

from __future__ import annotations

from guardrails_review.types import LLMResponse, ReviewConfig, TokenBudget

# --- TokenBudget ---


def test_token_budget_remaining_initial():
    """Remaining equals max_tokens when no usage recorded."""
    budget = TokenBudget(max_tokens=100_000)

    assert budget.remaining == 100_000


def test_token_budget_remaining_after_record():
    """Remaining reflects last_prompt_tokens after recording usage."""
    budget = TokenBudget(max_tokens=100_000)
    budget.record({"prompt_tokens": 40_000, "completion_tokens": 500})

    assert budget.remaining == 60_000


def test_token_budget_record_updates_cumulative_completions():
    """record() accumulates completion_tokens across calls."""
    budget = TokenBudget(max_tokens=100_000)
    budget.record({"prompt_tokens": 10_000, "completion_tokens": 200})
    budget.record({"prompt_tokens": 20_000, "completion_tokens": 300})

    assert budget.total_completion_tokens == 500
    # last_prompt_tokens is the LAST value, not cumulative
    assert budget.last_prompt_tokens == 20_000


def test_token_budget_record_none_is_noop():
    """record(None) does not change any values."""
    budget = TokenBudget(max_tokens=100_000)
    budget.record(None)

    assert budget.remaining == 100_000
    assert budget.total_completion_tokens == 0


def test_token_budget_record_empty_dict_is_noop():
    """record({}) does not change any values (get defaults to 0)."""
    budget = TokenBudget(max_tokens=100_000)
    budget.record({})

    assert budget.last_prompt_tokens == 0
    assert budget.total_completion_tokens == 0


def test_token_budget_can_continue_true_when_enough_room():
    """can_continue() returns True when remaining > estimated + reserve."""
    budget = TokenBudget(max_tokens=100_000, reserve_tokens=15_000)
    budget.record({"prompt_tokens": 50_000, "completion_tokens": 0})

    # remaining = 50_000. estimated_next=20_000 + reserve=15_000 = 35_000. 50k > 35k
    assert budget.can_continue(estimated_next=20_000) is True


def test_token_budget_can_continue_false_when_tight():
    """can_continue() returns False when remaining <= estimated + reserve."""
    budget = TokenBudget(max_tokens=100_000, reserve_tokens=15_000)
    budget.record({"prompt_tokens": 80_000, "completion_tokens": 0})

    # remaining = 20_000. estimated_next=20_000 + reserve=15_000 = 35_000. 20k < 35k
    assert budget.can_continue(estimated_next=20_000) is False


def test_token_budget_can_continue_default_estimated():
    """can_continue() uses default estimated_next=20_000."""
    budget = TokenBudget(max_tokens=100_000, reserve_tokens=15_000)
    budget.record({"prompt_tokens": 60_000, "completion_tokens": 0})

    # remaining = 40_000. default 20_000 + 15_000 = 35_000. 40k > 35k
    assert budget.can_continue() is True


def test_token_budget_at_threshold_true():
    """at_threshold(0.85) returns True when usage >= 85%."""
    budget = TokenBudget(max_tokens=100_000)
    budget.record({"prompt_tokens": 86_000, "completion_tokens": 0})

    assert budget.at_threshold(0.85) is True


def test_token_budget_at_threshold_false():
    """at_threshold(0.85) returns False when usage < 85%."""
    budget = TokenBudget(max_tokens=100_000)
    budget.record({"prompt_tokens": 50_000, "completion_tokens": 0})

    assert budget.at_threshold(0.85) is False


def test_token_budget_at_threshold_exact_boundary():
    """at_threshold returns True when exactly at boundary."""
    budget = TokenBudget(max_tokens=100_000)
    budget.record({"prompt_tokens": 85_000, "completion_tokens": 0})

    assert budget.at_threshold(0.85) is True


# --- LLMResponse.usage ---


def test_llm_response_usage_default_empty():
    """LLMResponse.usage defaults to empty dict."""
    resp = LLMResponse(content="hi")

    assert resp.usage == {}


def test_llm_response_usage_provided():
    """LLMResponse.usage stores provided usage dict."""
    usage = {"prompt_tokens": 100, "completion_tokens": 50}
    resp = LLMResponse(content="hi", usage=usage)

    assert resp.usage == usage


# --- ReviewConfig.max_iterations default ---


def test_review_config_max_iterations_default_30():
    """ReviewConfig.max_iterations defaults to 30."""
    config = ReviewConfig(model="test/m")

    assert config.max_iterations == 30
