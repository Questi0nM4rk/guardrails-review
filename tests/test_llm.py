"""Tests for guardrails_review.llm module."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from typing import Any
from unittest.mock import MagicMock

import pytest

from guardrails_review.llm import call_openrouter


def _make_response(content: str) -> io.BytesIO:
    """Build a fake HTTP response body matching OpenRouter's format."""
    payload = {
        "choices": [{"message": {"content": content}}],
    }
    return io.BytesIO(json.dumps(payload).encode())


def _stub_urlopen(resp: io.BytesIO) -> Any:
    """Return a urlopen replacement that ignores all args and returns *resp*."""

    def _inner(*_args: Any, **_kwargs: Any) -> io.BytesIO:
        return resp

    return _inner


def test_call_openrouter_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid response returns the content string from choices[0].message.content."""
    monkeypatch.setenv("OPENROUTER_KEY", "sk-test-key")

    fake_resp = _make_response('{"verdict": "approve"}')
    fake_resp.status = 200  # type: ignore[attr-defined]
    monkeypatch.setattr(urllib.request, "urlopen", _stub_urlopen(fake_resp))

    result = call_openrouter(
        messages=[{"role": "user", "content": "hello"}],
        model="openai/gpt-4o",
    )

    assert result == '{"verdict": "approve"}'


def test_call_openrouter_json_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """When json_mode=True (default), request body includes response_format."""
    monkeypatch.setenv("OPENROUTER_KEY", "sk-test-key")
    captured_req: list[urllib.request.Request] = []

    def fake_urlopen(req: urllib.request.Request, **_kwargs: Any) -> io.BytesIO:
        captured_req.append(req)
        return _make_response("ok")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    call_openrouter(
        messages=[{"role": "user", "content": "hi"}],
        model="test-model",
        json_mode=True,
    )

    body = json.loads(captured_req[0].data)
    assert "response_format" in body
    assert body["response_format"] == {"type": "json_object"}


def test_call_openrouter_no_json_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """When json_mode=False, request body omits response_format."""
    monkeypatch.setenv("OPENROUTER_KEY", "sk-test-key")
    captured_req: list[urllib.request.Request] = []

    def fake_urlopen(req: urllib.request.Request, **_kwargs: Any) -> io.BytesIO:
        captured_req.append(req)
        return _make_response("ok")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    call_openrouter(
        messages=[{"role": "user", "content": "hi"}],
        model="test-model",
        json_mode=False,
    )

    body = json.loads(captured_req[0].data)
    assert "response_format" not in body


def test_call_openrouter_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Raises ValueError when OPENROUTER_KEY is not set."""
    monkeypatch.delenv("OPENROUTER_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENROUTER_KEY"):
        call_openrouter(
            messages=[{"role": "user", "content": "hi"}],
            model="test-model",
        )


def test_call_openrouter_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Raises RuntimeError on HTTP errors, including status code and body."""
    monkeypatch.setenv("OPENROUTER_KEY", "sk-test-key")

    def fake_urlopen(*_args: Any, **_kwargs: Any) -> None:
        raise urllib.error.HTTPError(
            url="https://openrouter.ai/api/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs=MagicMock(),  # type: ignore[arg-type]
            fp=io.BytesIO(b'{"error": "rate limited"}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="429") as exc_info:
        call_openrouter(
            messages=[{"role": "user", "content": "hi"}],
            model="test-model",
        )
    assert "rate limited" in str(exc_info.value)


def test_call_openrouter_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Raises TimeoutError when urllib times out."""
    monkeypatch.setenv("OPENROUTER_KEY", "sk-test-key")

    def fake_urlopen(*_args: Any, **_kwargs: Any) -> None:
        raise urllib.error.URLError(reason=TimeoutError("timed out"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(TimeoutError, match="timed out"):
        call_openrouter(
            messages=[{"role": "user", "content": "hi"}],
            model="test-model",
        )


def test_call_openrouter_sends_correct_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies Authorization and Content-Type headers are set correctly."""
    monkeypatch.setenv("OPENROUTER_KEY", "sk-my-secret")
    captured_req: list[urllib.request.Request] = []

    def fake_urlopen(req: urllib.request.Request, **_kwargs: Any) -> io.BytesIO:
        captured_req.append(req)
        return _make_response("ok")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    call_openrouter(
        messages=[{"role": "user", "content": "hi"}],
        model="test-model",
    )

    req = captured_req[0]
    assert req.get_header("Authorization") == "Bearer sk-my-secret"
    assert req.get_header("Content-type") == "application/json"
