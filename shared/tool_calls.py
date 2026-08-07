"""Parse tool calls requested by an LLM."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def parse_tool_calls(raw: str) -> list[dict[str, Any]]:
    """Parse a JSON tool-call array, returning no calls for invalid output."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()

    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []

    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        logger.warning("Could not parse tool-call response as JSON (len=%d)", len(raw))
        return []

    if not isinstance(parsed, list):
        return []
    return [call for call in parsed if isinstance(call, dict) and isinstance(call.get("name"), str)]
