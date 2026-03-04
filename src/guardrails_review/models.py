"""Fetch model metadata from OpenRouter. Zero external dependencies."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_FALLBACK_CONTEXT_LENGTH = 128_000
_TIMEOUT_SECONDS = 10


def get_model_context_length(model_id: str) -> int:
    """Query OpenRouter ``/api/v1/models/<id>`` for context window size.

    No auth needed.  Returns ``context_length`` for the model.
    Falls back to 128,000 on network error or model not found.

    Args:
        model_id: OpenRouter model identifier (e.g. ``"anthropic/claude-sonnet-4"``).

    Returns:
        Context window size in tokens.
    """
    url = f"{_OPENROUTER_MODELS_URL}/{model_id}"
    req = urllib.request.Request(url, method="GET")

    try:
        resp = urllib.request.urlopen(  # nosec B310  # nosemgrep: dynamic-urllib-use-detected
            req, timeout=_TIMEOUT_SECONDS
        )
        data = json.loads(resp.read().decode())
        ctx_length: int = data["data"]["context_length"]
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
    ):
        logger.warning(
            "Failed to fetch context length for %s, using fallback %d",
            model_id,
            _FALLBACK_CONTEXT_LENGTH,
        )
        return _FALLBACK_CONTEXT_LENGTH

    return ctx_length
