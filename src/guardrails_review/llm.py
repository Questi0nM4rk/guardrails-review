"""OpenRouter HTTP client. Zero external dependencies."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_TIMEOUT_SECONDS = 120


def call_openrouter(
    messages: list[dict[str, str]],
    model: str,
    *,
    json_mode: bool = True,
) -> str:
    """Send a chat completion request to OpenRouter and return the response content.

    Args:
        messages: List of message dicts with "role" and "content" keys.
        model: OpenRouter model identifier (e.g. "openai/gpt-4o").
        json_mode: When True, request JSON output format from the model.

    Returns:
        The text content from choices[0].message.content.

    Raises:
        ValueError: If OPENROUTER_KEY environment variable is not set.
        RuntimeError: On HTTP error responses (includes status code and body).
        TimeoutError: When the request times out.
    """
    key = os.environ.get("OPENROUTER_KEY")
    if not key:
        msg = "OPENROUTER_KEY environment variable is not set"
        raise ValueError(msg)

    body: dict[str, object] = {
        "model": model,
        "messages": messages,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

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

    response_data = json.loads(resp.read().decode())
    return response_data["choices"][0]["message"]["content"]
