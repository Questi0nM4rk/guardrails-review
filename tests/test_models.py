"""Tests for guardrails_review.models — model context length fetching."""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock
import urllib.error
import urllib.request

if TYPE_CHECKING:
    import pytest

from guardrails_review.models import get_model_context_length


def _stub_urlopen(resp: io.BytesIO) -> Any:
    """Return a urlopen replacement that returns *resp*."""

    def _inner(*_args: Any, **_kwargs: Any) -> io.BytesIO:
        return resp

    return _inner


def test_get_model_context_length_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns context_length from the OpenRouter API response."""
    payload = {"data": {"context_length": 200_000}}
    fake_resp = io.BytesIO(json.dumps(payload).encode())
    monkeypatch.setattr(urllib.request, "urlopen", _stub_urlopen(fake_resp))

    result = get_model_context_length("anthropic/claude-sonnet-4")

    assert result == 200_000


def test_get_model_context_length_fallback_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Returns 250_000 fallback on HTTP error."""

    def fake_urlopen(*_args: Any, **_kwargs: Any) -> None:
        raise urllib.error.HTTPError(
            url="https://openrouter.ai/api/v1/models/test",
            code=404,
            msg="Not Found",
            hdrs=MagicMock(),
            fp=io.BytesIO(b"not found"),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = get_model_context_length("nonexistent/model")

    assert result == 250_000


def test_get_model_context_length_fallback_on_url_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Returns 250_000 fallback on network error."""

    def fake_urlopen(*_args: Any, **_kwargs: Any) -> None:
        raise urllib.error.URLError("DNS resolution failed")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = get_model_context_length("test/model")

    assert result == 250_000


def test_get_model_context_length_fallback_on_bad_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Returns 250_000 fallback on malformed JSON."""
    fake_resp = io.BytesIO(b"not json at all")
    monkeypatch.setattr(urllib.request, "urlopen", _stub_urlopen(fake_resp))

    result = get_model_context_length("test/model")

    assert result == 250_000


def test_get_model_context_length_fallback_on_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Returns 250_000 fallback when response has no context_length."""
    payload = {"data": {"id": "test/model"}}  # no context_length key
    fake_resp = io.BytesIO(json.dumps(payload).encode())
    monkeypatch.setattr(urllib.request, "urlopen", _stub_urlopen(fake_resp))

    result = get_model_context_length("test/model")

    assert result == 250_000


def test_get_model_context_length_correct_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies the correct OpenRouter URL is queried."""
    captured_urls: list[str] = []

    def fake_urlopen(req: urllib.request.Request, **_kwargs: Any) -> io.BytesIO:
        captured_urls.append(req.full_url)
        payload = {"data": {"context_length": 100_000}}
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    get_model_context_length("anthropic/claude-sonnet-4")

    assert len(captured_urls) == 1
    assert (
        captured_urls[0]
        == "https://openrouter.ai/api/v1/models/anthropic/claude-sonnet-4"
    )
