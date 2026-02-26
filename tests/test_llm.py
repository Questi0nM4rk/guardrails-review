"""Tests for guardrails_review.llm module."""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import MagicMock
import urllib.error
import urllib.request

import pytest

from guardrails_review.llm import call_openrouter, call_openrouter_tools


def _make_response(
    content: str | None,
    tool_calls: list[Any] | None = None,
    finish_reason: str = "stop",
) -> io.BytesIO:
    """Build a fake HTTP response body matching OpenRouter's format."""
    message: dict[str, Any] = {"content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    payload = {
        "choices": [{"message": message, "finish_reason": finish_reason}],
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

    body = json.loads(captured_req[0].data)  # type: ignore[arg-type]
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

    body = json.loads(captured_req[0].data)  # type: ignore[arg-type]
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
            hdrs=MagicMock(),
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


def test_call_openrouter_urlerror_non_timeout_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-timeout URLError is re-raised as-is (not wrapped in TimeoutError)."""
    monkeypatch.setenv("OPENROUTER_KEY", "sk-test-key")

    def fake_urlopen(*_args: Any, **_kwargs: Any) -> None:
        raise urllib.error.URLError(reason=ConnectionRefusedError("connection refused"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(urllib.error.URLError, match="connection refused"):
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


# --- Tool-use tests ---


def test_call_with_tools_returns_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLMResponse contains parsed ToolCall objects from model response."""
    monkeypatch.setenv("OPENROUTER_KEY", "sk-test-key")

    tool_calls_data = [
        {
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": '{"path": "src/main.py"}',
            },
        },
    ]
    fake_resp = _make_response(
        None, tool_calls=tool_calls_data, finish_reason="tool_calls"
    )
    monkeypatch.setattr(urllib.request, "urlopen", _stub_urlopen(fake_resp))

    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]
    result = call_openrouter_tools(
        messages=[{"role": "user", "content": "review this"}],
        model="test-model",
        tools=tools,
    )

    assert result.finish_reason == "tool_calls"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_123"
    assert result.tool_calls[0].name == "read_file"
    assert result.tool_calls[0].arguments == '{"path": "src/main.py"}'
    assert result.content is None


def test_call_with_tools_returns_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model returning content (no tool calls) has content and empty tool_calls."""
    monkeypatch.setenv("OPENROUTER_KEY", "sk-test-key")

    fake_resp = _make_response("Here is my review", finish_reason="stop")
    monkeypatch.setattr(urllib.request, "urlopen", _stub_urlopen(fake_resp))

    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]
    result = call_openrouter_tools(
        messages=[{"role": "user", "content": "review this"}],
        model="test-model",
        tools=tools,
    )

    assert result.finish_reason == "stop"
    assert result.content == "Here is my review"
    assert result.tool_calls == []


def test_tool_choice_parameter(monkeypatch: pytest.MonkeyPatch) -> None:
    """tool_choice is included in the request body when provided."""
    monkeypatch.setenv("OPENROUTER_KEY", "sk-test-key")
    captured_req: list[urllib.request.Request] = []

    def fake_urlopen(req: urllib.request.Request, **_kwargs: Any) -> io.BytesIO:
        captured_req.append(req)
        return _make_response("ok")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    forced_choice = {"type": "function", "function": {"name": "submit_review"}}
    tools = [
        {"type": "function", "function": {"name": "submit_review", "parameters": {}}}
    ]
    call_openrouter_tools(
        messages=[{"role": "user", "content": "hi"}],
        model="test-model",
        tools=tools,
        tool_choice=forced_choice,
    )

    body = json.loads(captured_req[0].data)  # type: ignore[arg-type]
    assert body["tool_choice"] == forced_choice
    assert "tools" in body
    assert "response_format" not in body


def test_tools_disables_json_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tools omit response_format even with json_mode=True."""
    monkeypatch.setenv("OPENROUTER_KEY", "sk-test-key")
    captured_req: list[urllib.request.Request] = []

    def fake_urlopen(req: urllib.request.Request, **_kwargs: Any) -> io.BytesIO:
        captured_req.append(req)
        return _make_response("ok")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]
    call_openrouter(
        messages=[{"role": "user", "content": "hi"}],
        model="test-model",
        json_mode=True,
        tools=tools,
    )

    body = json.loads(captured_req[0].data)  # type: ignore[arg-type]
    assert "response_format" not in body
    assert "tools" in body
