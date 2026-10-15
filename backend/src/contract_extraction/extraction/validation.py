"""Checking an extracted value against its field's JSON Schema (the subset the catalogue generates).

Checked: JSON types (including nullable ``["string", "null"]``), enums, object properties, array
items and numeric bounds. Not checked: ``format`` and ``pattern`` (dates, durations, ISO codes),
which the prompt asks for but a correct value in another notation should not be thrown away for.

Enum values are normalised before checking ("One Way" → "one_way"), so near-misses still count.
"""

from __future__ import annotations

import re
from typing import Any

_JSON_TYPES = {"string": str, "boolean": bool, "object": dict, "array": list}


def _matches(value: Any, kind: str) -> bool:
    if kind == "null":
        return value is None
    if kind == "integer":
        return (isinstance(value, int) and not isinstance(value, bool)) or (isinstance(value, float) and value.is_integer())
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _JSON_TYPES.get(kind, object))


def _enum_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


def conform(value: Any, schema: dict[str, Any], path: str = "value") -> tuple[Any, list[str]]:
    """``value`` with enum strings normalised, and the problems found (empty when it fits the schema)."""
    if not schema:
        return value, []
    kinds = schema.get("type")
    kinds = [kinds] if isinstance(kinds, str) else list(kinds or [])
    if kinds and not any(_matches(value, k) for k in kinds):
        return value, [f"{path}: expected {' or '.join(kinds)}, got {type(value).__name__}"]
    if value is None:
        return value, []

    errors: list[str] = []
    if "enum" in schema and isinstance(value, str):
        allowed = {_enum_key(e): e for e in schema["enum"]}
        if value not in schema["enum"]:
            if _enum_key(value) in allowed:
                value = allowed[_enum_key(value)]
            else:
                errors.append(f"{path}: {value!r} is not one of {schema['enum']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} is below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} is above {schema['maximum']}")
    if isinstance(value, dict):
        out = dict(value)
        for key, sub in schema.get("properties", {}).items():
            if key in out:
                out[key], sub_errors = conform(out[key], sub, f"{path}.{key}")
                errors += sub_errors
        value = out
    if isinstance(value, list) and "items" in schema:
        items = []
        for i, item in enumerate(value):
            item, sub_errors = conform(item, schema["items"], f"{path}[{i}]")
            items.append(item)
            errors += sub_errors
        value = items
    return value, errors
