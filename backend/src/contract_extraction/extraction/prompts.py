"""User prompts for the extraction LLM and the judge. System prompts come from the run's config snapshot.

A field with a hand-written ``user_prompt`` uses it as is. Catalogue fields have none and get the
generic template below, built from the field's description, type and JSON Schema.
"""

from __future__ import annotations

import json
from typing import Any

from ..domain.config import Field
from .retrieval import Hit

# Hits with less text than this add nothing and are left out of the context.
MIN_CONTEXT_CHARS = 7

FORMAT_RULES = (
    "- Dates as YYYY-MM-DD; durations as ISO 8601 (P30D, P3Y, PT72H); money as an object "
    '{"amount": number, "currency": ISO 4217 code}; jurisdictions as ISO 3166 codes (AU-NSW, US-NY, GB); '
    "percentages on a 0-100 scale; language as an ISO 639-1 code."
)

# How a scalar catalogue type is described to the model.
_SCALAR_HELP = {
    "string": "A short text, verbatim where possible.",
    "text": "Free text: a short summary of the clause, or its wording when short.",
    "strings": "A list of short texts.",
    "bool": "true or false.",
    "int": "A whole number.",
    "number": "A number.",
    "percent": "A number on a 0-100 scale.",
    "date": "A date (YYYY-MM-DD).",
    "duration": "An ISO 8601 duration, e.g. P30D, P3Y, PT72H.",
    "language": "An ISO 639-1 language code, e.g. en.",
    "jurisdiction": "An ISO 3166 code, e.g. AU-NSW, US-NY, GB.",
    "jurisdictions": "A list of ISO 3166 codes.",
    "party_refs": "A list of party ids, as used in the parties list.",
    "relative_date": "An object: date (YYYY-MM-DD) when the text gives or implies a calendar date; "
                     "otherwise relative_to (the event, e.g. completion) and offset (ISO 8601 duration).",
    "money": "An object with amount (number) and currency (ISO 4217 code).",
    "recurring_money": "An object with amount (number), currency (ISO 4217 code) and period "
                       "(hour, day, week, month, quarter or year).",
    "restriction": "An object: exists (true/false), restricted_party_refs, scope, territory, duration (ISO 8601).",
}


def build_context(hits: list[Hit]) -> str:
    return "".join(f"{h.text}\n" for h in hits if len(h.text) >= MIN_CONTEXT_CHARS)


def _keys(schema: dict[str, Any]) -> str:
    return ", ".join(schema.get("properties", {}))


def value_help(field: Field) -> str:
    """One or two sentences telling the model what shape the value has."""
    spec = (field.type_spec or "").strip()
    schema = field.value_schema or {}
    if spec in _SCALAR_HELP:
        return _SCALAR_HELP[spec]
    if spec.startswith("enum:"):
        return "One of: " + ", ".join(schema.get("enum", [])) + "."
    if spec.startswith("object:"):
        return f"An object with the keys {_keys(schema)}; null for keys the text does not state."
    if spec.startswith("list of:"):
        return (f"A list of objects, each with the keys {_keys(schema.get('items', {}))}; "
                "null for keys the text does not state.")
    return "A short text."


def skeleton(schema: dict[str, Any]) -> Any:
    """An example value with the schema's shape, shown as the expected JSON format."""
    kinds = schema.get("type")
    kind = next((k for k in kinds if k != "null"), None) if isinstance(kinds, list) else kinds
    if "enum" in schema:
        return " | ".join(schema["enum"])
    if kind == "object":
        return {k: skeleton(v) if v else None for k, v in schema.get("properties", {}).items()}
    if kind == "array":
        return [skeleton(schema.get("items", {}))]
    if kind == "boolean":
        return True
    if kind in ("number", "integer"):
        return 0
    return ""


def generic_prompt(field: Field) -> str:
    example = json.dumps({field.key: skeleton(field.value_schema) if field.value_schema else ""}, ensure_ascii=False)
    lines = [
        "Task: From the given contract text chunks, extract the following field:",
        field.key,
        "",
        f"Definition of {field.key} ({field.label}):",
        field.description or field.label,
        "",
        "Value:",
        value_help(field),
        "",
        "Extraction rules:",
        "- Use only what the chunks state; do not infer, guess or invent values.",
        FORMAT_RULES,
        f"- If the chunks do not address {field.key}, return null.",
        "",
        "JSON Format:",
        example,
        "Input Chunks:",
    ]
    return "\n".join(lines)


def extraction_prompt(field: Field, context: str) -> str:
    return f"{field.user_prompt or generic_prompt(field)}<<<\n{context}\n>>>"


def group_prompt(fields: tuple[Field, ...], context: str) -> str:
    """One prompt for several fields (group extraction). Built from the fields' descriptions and types;
    hand-written field prompts are not used here."""
    example = {f.key: skeleton(f.value_schema) if f.value_schema else "" for f in fields}
    lines = ["Task: From the given contract text chunks, extract the following fields:", *(f.key for f in fields), "",
             "Definitions:"]
    for f in fields:
        lines += [f"{f.key} ({f.label}): {f.description or f.label}", f"  Value: {value_help(f)}"]
    lines += [
        "",
        "Extraction rules:",
        "- Use only what the chunks state; do not infer, guess or invent values.",
        FORMAT_RULES,
        "- Return every field listed; use null for a field the chunks do not address.",
        "",
        "JSON Format:",
        json.dumps(example, ensure_ascii=False),
        "Input Chunks:",
    ]
    return "\n".join(lines) + f"<<<\n{context}\n>>>"


def judge_prompt(field: Field, context: str, answer: str) -> str:
    question = f"Extract {field.label}" + (f" ({field.description})" if field.description else "")
    return f"Question: {question}\nContext: {context}\nAnswer: {answer}"
