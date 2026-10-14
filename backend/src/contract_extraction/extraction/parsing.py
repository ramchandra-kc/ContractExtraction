"""Turning model answers into field values."""

from __future__ import annotations

import json
import re
from typing import Any

from ..domain.enums import FieldResultStatus

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)
_EMPTY_WORDS = {"", "n/a", "na", "none", "null", "not found", "not available", "not specified", "not mentioned", "unknown"}


def parse_json_lenient(text: str) -> Any | None:
    """JSON from a model answer, tolerating code fences and surrounding prose. None when there is none."""
    text = (text or "").strip()
    if not text:
        return None
    candidates = [text, *(m.group(1).strip() for m in _FENCE.finditer(text))]
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start, end = text.find(open_ch), text.rfind(close_ch)
        if 0 <= start < end:
            candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return None


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().strip(".").casefold() in _EMPTY_WORDS
    if isinstance(value, (list, dict)):
        return all(is_empty(v) for v in (value.values() if isinstance(value, dict) else value))
    return False


def field_value(answer: str, key: str) -> tuple[FieldResultStatus, Any | None]:
    """Status and value for ``key`` in an extraction answer.

    The value is the answer's ``key`` entry, or its only entry; a non-JSON answer is kept as text.
    """
    parsed = parse_json_lenient(answer)
    if isinstance(parsed, dict):
        if key in parsed:
            value = parsed[key]
        elif len(parsed) == 1:
            value = next(iter(parsed.values()))
        else:
            value = parsed
    elif parsed is not None:
        value = parsed
    else:
        value = (answer or "").strip()
    if is_empty(value):
        return FieldResultStatus.NOT_FOUND, None
    return FieldResultStatus.EXTRACTED, value
