"""OpenRouter HTTP client. Zero external dependencies."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from guardrails_review.types import LLMResponse, ToolCall

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_TIMEOUT_SECONDS = 120


def call_openrouter(
    messages: list[dict[str, Any]],
    model: str,
    *,
    json_mode: bool = True,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | str | None = None,
) -> str:
    """Send a chat completion request to OpenRouter and return the response content.

    This is the backwards-compatible wrapper. When no tools are provided,
    it behaves exactly as before (returns content string).

    When tools are provided, use ``call_openrouter_tools()`` instead for
    the full ``LLMResponse`` with tool call support.

    Args:
        messages: List of message dicts with "role" and "content" keys.
        model: OpenRouter model identifier (e.g. "openai/gpt-4o").
        json_mode: When True, request JSON output format from the model.
        tools: Optional tool definitions for function calling.
        tool_choice: Optional tool choice directive.

    Returns:
        The text content from choices[0].message.content.

    Raises:
        ValueError: If OPENROUTER_KEY environment variable is not set.
        RuntimeError: On HTTP error responses (includes status code and body).
        TimeoutError: When the request times out.
    """
    response = _send_request(
        messages, model, json_mode=json_mode, tools=tools, tool_choice=tool_choice
    )
    return response.content or ""


def call_openrouter_tools(
    messages: list[dict[str, Any]],
    model: str,
    *,
    tools: list[dict[str, Any]],
    tool_choice: dict[str, Any] | str | None = None,
) -> LLMResponse:
    """Send a chat completion with tools and return the full structured response.

    Args:
        messages: List of message dicts (role/content, or tool results).
        model: OpenRouter model identifier.
        tools: Tool definitions in OpenRouter format.
        tool_choice: Optional tool choice directive.

    Returns:
        LLMResponse with content, tool_calls, and finish_reason.

    Raises:
        ValueError: If OPENROUTER_KEY environment variable is not set.
        RuntimeError: On HTTP error responses.
        TimeoutError: When the request times out.
    """
    return _send_request(messages, model, json_mode=False, tools=tools, tool_choice=tool_choice)


def _send_request(
    messages: list[dict[str, Any]],
    model: str,
    *,
    json_mode: bool = False,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | str | None = None,
) -> LLMResponse:
    """Send request to OpenRouter and parse the response into LLMResponse."""
    key = os.environ.get("OPENROUTER_KEY")
    if not key:
        msg = "OPENROUTER_KEY environment variable is not set"
        raise ValueError(msg)

    body: dict[str, object] = {
        "model": model,
        "messages": messages,
    }
    if json_mode and tools is None:
        body["response_format"] = {"type": "json_object"}
    if tools is not None:
        body["tools"] = tools
    if tool_choice is not None:
        body["tool_choice"] = tool_choice

    data = json.dumps(body).encode()

    req = urllib.request.Request(  # noqa: S310 — URL is a hardcoded HTTPS constant
        _OPENROUTER_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        resp = urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS)  # noqa: S310
    except urllib.error.HTTPError as exc:
        resp_body = exc.read().decode(errors="replace")
        msg = f"OpenRouter API error {exc.code}: {resp_body}"
        raise RuntimeError(msg) from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            msg = f"OpenRouter request timed out after {_TIMEOUT_SECONDS}s"
            raise TimeoutError(msg) from exc
        raise
    except TimeoutError as exc:
        msg = f"OpenRouter request timed out after {_TIMEOUT_SECONDS}s"
        raise TimeoutError(msg) from exc

    response_data = json.loads(resp.read().decode())
    return _parse_response(response_data)


def _parse_response(response_data: dict[str, Any]) -> LLMResponse:
    """Parse OpenRouter response JSON into an LLMResponse."""
    choice = response_data["choices"][0]
    message = choice["message"]
    finish_reason = choice.get("finish_reason", "stop")

    content = message.get("content")

    raw_tool_calls = message.get("tool_calls", [])
    tool_calls = [
        ToolCall(
            id=tc["id"],
            name=tc["function"]["name"],
            arguments=tc["function"]["arguments"],
        )
        for tc in raw_tool_calls
    ]

    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
    )
