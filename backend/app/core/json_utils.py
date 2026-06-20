"""
JSON parsing utilities — robust extraction from LLM responses.

LLMs sometimes wrap JSON in markdown code fences, add preamble text,
or return trailing commas. This module handles all those cases cleanly.
"""
import re
import json
from typing import Any, Optional


def extract_json(text: str) -> Optional[Any]:
    """
    Extract and parse the first valid JSON object or array from an LLM response.

    Handles:
    - ```json ... ``` fences
    - ``` ... ``` fences (no language tag)
    - Inline JSON with surrounding text
    - Trailing commas (common LLM mistake)

    Returns the parsed object, or None if no valid JSON found.
    """
    if not text:
        return None

    # 1. Try ```json ... ``` fence
    m = re.search(r"```json\s*([\s\S]*?)```", text, re.IGNORECASE)
    if m:
        return _try_parse(m.group(1).strip())

    # 2. Try ``` ... ``` fence (any language)
    m = re.search(r"```\w*\s*([\s\S]*?)```", text)
    if m:
        result = _try_parse(m.group(1).strip())
        if result is not None:
            return result

    # 3. Try to find a raw JSON object {...} or array [...]
    m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if m:
        return _try_parse(m.group(1).strip())

    # 4. Last resort — try parsing the entire stripped text
    return _try_parse(text.strip())


def _try_parse(s: str) -> Optional[Any]:
    """Try to parse a JSON string, with a trailing-comma fix pass."""
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # Remove trailing commas before } or ]  (common LLM mistake)
        fixed = re.sub(r",\s*([}\]])", r"\1", s)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return None
