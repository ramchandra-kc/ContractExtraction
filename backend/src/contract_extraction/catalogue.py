"""The field catalogue: contract types and their fields, parsed from docs/contract_types_and_fields.md.

The Markdown file is the source of truth. ``contract-extraction gen-catalogue`` parses it, checks it
and writes docker/seed_catalogue.sql, which loads the fields, contract types and their mapping into
the ``contract_fields`` field set created by seed.sql.

Document shape (one section per contract type)::

    ## 3. SOW
    **Identify by:** <how the classifier recognises the type>
    ### Core                      ← shared group: identical wherever it appears
    | `title` | string | P3 | Document title as written |
    ### SOW-Specific              ← the type's own fields
    ...
    ## 19. Other
    **Identify by:** ...
    **Includes:** Core, Commercial, Risk & Liability   ← the fallback type: shared groups by name

Checks: every type spec is known, a key repeated anywhere has the same spec and description
(priority may differ per type), shared groups are identical in every section, exactly one
fallback type exists.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .core.errors import AppError
from .domain.enums import Priority, ValueType

FIELD_SET = ("contract_fields", 1)

_TYPE = re.compile(r"^## \d+\. (.+?)\s*$")
_GROUP = re.compile(r"^### (.+?)\s*$")
_ROW = re.compile(r"^\| `([a-z][a-z0-9_]*)` \| (.+?) \| (P[123]) \| (.+?) \|\s*$")
_IDENTIFY = re.compile(r"^\*\*Identify by:\*\*\s*(.+?)\s*$")
_INCLUDES = re.compile(r"^\*\*Includes:\*\*\s*(.+?)\s*$")

_JURISDICTION = "^[A-Z]{2}(-[A-Z0-9]{1,3})?$"
_CURRENCY = "^[A-Z]{3}$"
_UPPER_WORDS = {"ip", "nda", "sow", "dpa", "jv", "mfn", "id", "sla", "po"}


class CatalogueError(AppError):
    """The catalogue document is malformed or inconsistent."""


@dataclass
class FieldDef:
    key: str
    type_spec: str
    description: str
    priority: Priority  # highest priority across the types that use the field
    position: int

    @property
    def label(self) -> str:
        words = self.key.split("_")
        out = [w.upper() if w in _UPPER_WORDS else "W&I" if w == "wi" else w for w in words]
        text = " ".join(out)
        return text[0].upper() + text[1:]

    @property
    def value_type(self) -> ValueType:
        return value_type(self.type_spec)

    @property
    def value_schema(self) -> dict[str, Any]:
        return value_schema(self.type_spec)


@dataclass
class Member:
    key: str
    group: str
    priority: Priority


@dataclass
class TypeDef:
    key: str
    label: str
    description: str
    is_fallback: bool
    position: int
    members: list[Member] = field(default_factory=list)


@dataclass
class Catalogue:
    types: list[TypeDef]
    fields: dict[str, FieldDef]

    @property
    def fallback(self) -> TypeDef:
        return next(t for t in self.types if t.is_fallback)


# ---- type specs -------------------------------------------------------------------------------------


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    if "type" in schema:
        return {**schema, "type": [schema["type"], "null"]}
    return schema


def _object(keys: list[str], typed: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    typed = typed or {}
    return {"type": "object", "properties": {k: _nullable(typed[k]) if k in typed else {} for k in keys}}


_STR = {"type": "string"}
_JUR = {"type": "string", "pattern": _JURISDICTION}
_DURATION = {"type": "string", "format": "duration"}
_MONEY = {"amount": {"type": "number"}, "currency": {"type": "string", "pattern": _CURRENCY}}
_PERIODS = ["hour", "day", "week", "month", "quarter", "year"]

SCALARS: dict[str, dict[str, Any]] = {
    "string": _STR,
    "text": _STR,
    "strings": {"type": "array", "items": _STR},
    "bool": {"type": "boolean"},
    "int": {"type": "integer"},
    "number": {"type": "number"},
    "percent": {"type": "number", "minimum": 0, "maximum": 100},
    "date": {"type": "string", "format": "date"},
    "duration": _DURATION,
    "language": {"type": "string", "pattern": "^[a-z]{2}$"},
    "jurisdiction": _JUR,
    "jurisdictions": {"type": "array", "items": _JUR},
    "party_refs": {"type": "array", "items": _STR},
    "money": _object(["amount", "currency"], _MONEY),
    "recurring_money": _object(["amount", "currency", "period"], {**_MONEY, "period": {"type": "string", "enum": _PERIODS}}),
    "relative_date": _object(["date", "relative_to", "offset"],
                             {"date": {"type": "string", "format": "date"}, "relative_to": _STR, "offset": _DURATION}),
    "restriction": _object(["exists", "restricted_party_refs", "scope", "territory", "duration"],
                           {"exists": {"type": "boolean"}, "restricted_party_refs": {"type": "array", "items": _STR},
                            "scope": _STR, "territory": _STR, "duration": _DURATION}),
}


def _split(rest: str) -> list[str]:
    return [p.strip() for p in rest.split(",") if p.strip()]


def value_schema(spec: str) -> dict[str, Any]:
    """JSON Schema for a type spec such as ``duration``, ``enum: a, b`` or ``list of: name, rate``."""
    spec = spec.strip()
    if spec in SCALARS:
        return SCALARS[spec]
    kind, sep, rest = spec.partition(":")
    parts = _split(rest)
    if sep and parts:
        if kind == "enum":
            return {"type": "string", "enum": parts}
        if kind == "object":
            return _object(parts)
        if kind == "list of":
            return {"type": "array", "items": _object(parts)}
    raise CatalogueError(f"Unknown field type {spec!r}; known: {sorted(SCALARS)}, enum: …, object: …, list of: …")


def value_type(spec: str) -> ValueType:
    """The coarse value type used by the UI and the evaluation views."""
    spec = spec.strip()
    if spec == "money":
        return ValueType.MONEY
    if spec in ("strings", "jurisdictions", "party_refs"):
        return ValueType.LIST
    if spec == "bool":
        return ValueType.BOOLEAN
    if spec in ("int", "number", "percent"):
        return ValueType.NUMBER
    if spec == "date":
        return ValueType.DATE
    if spec in ("relative_date", "recurring_money", "restriction") or spec.startswith(("object:", "list of:")):
        return ValueType.JSON
    return ValueType.TEXT


# ---- parsing ----------------------------------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def group_key(heading: str) -> str:
    """``Risk & Liability`` → ``risk_liability``; any ``<Type>-Specific`` heading → ``specific``."""
    return "specific" if heading.endswith("-Specific") else _slug(heading)


def parse(text: str) -> Catalogue:
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    group: str | None = None
    for n, line in enumerate(text.splitlines(), start=1):
        if m := _TYPE.match(line):
            current = {"label": m.group(1), "identify": None, "includes": None, "groups": {}, "line": n}
            sections.append(current)
            group = None
        elif current is None:
            continue
        elif m := _IDENTIFY.match(line):
            current["identify"] = m.group(1)
        elif m := _INCLUDES.match(line):
            current["includes"] = _split(m.group(1))
        elif m := _GROUP.match(line):
            group = m.group(1)
            current["groups"][group] = []
        elif m := _ROW.match(line):
            if group is None:
                raise CatalogueError(f"Line {n}: field row outside a ### group")
            key, spec, prio, desc = m.groups()
            value_schema(spec)  # rejects unknown types early, with the line number below
            current["groups"][group].append((key, spec.strip(), Priority(prio), desc.strip()))
        elif line.startswith("| `"):
            raise CatalogueError(f"Line {n}: cannot parse field row: {line!r}")

    if not sections:
        raise CatalogueError("No contract type sections (## N. Name) found")

    # Shared groups must be identical wherever they appear.
    shared: dict[str, list[tuple]] = {}
    for sec in sections:
        for name, rows in sec["groups"].items():
            if name.endswith("-Specific"):
                continue
            if name in shared and shared[name] != rows:
                raise CatalogueError(f"Group {name!r} in {sec['label']!r} differs from its first definition")
            shared.setdefault(name, rows)

    fields: dict[str, FieldDef] = {}
    types: list[TypeDef] = []
    for pos, sec in enumerate(sections, start=1):
        if not sec["identify"]:
            raise CatalogueError(f"{sec['label']!r} (line {sec['line']}) has no **Identify by:** line")
        groups: dict[str, list[tuple]] = dict(sec["groups"])
        if sec["includes"]:
            if groups:
                raise CatalogueError(f"{sec['label']!r} has both **Includes:** and its own field tables")
            for name in sec["includes"]:
                if name not in shared:
                    raise CatalogueError(f"{sec['label']!r} includes unknown group {name!r}; known: {sorted(shared)}")
                groups[name] = shared[name]
        t = TypeDef(key=_slug(sec["label"]), label=sec["label"], description=sec["identify"],
                    is_fallback=bool(sec["includes"]), position=pos)
        seen: set[str] = set()
        for name, rows in groups.items():
            for key, spec, prio, desc in rows:
                if key in seen:
                    raise CatalogueError(f"{t.label!r} lists {key!r} twice")
                seen.add(key)
                f = fields.get(key)
                if f is None:
                    fields[key] = FieldDef(key, spec, desc, prio, len(fields) + 1)
                elif (f.type_spec, f.description) != (spec, desc):
                    raise CatalogueError(
                        f"{key!r} in {t.label!r} is defined as ({spec!r}, {desc!r}) but earlier as "
                        f"({f.type_spec!r}, {f.description!r}); give it a type-specific key or one definition")
                else:
                    f.priority = min(f.priority, prio)
                t.members.append(Member(key, group_key(name), prio))
        if not t.members:
            raise CatalogueError(f"{t.label!r} has no fields")
        types.append(t)

    fallbacks = [t.label for t in types if t.is_fallback]
    if len(fallbacks) != 1:
        raise CatalogueError(f"Exactly one fallback type (a section with **Includes:**) is required; found {fallbacks}")
    if len({t.key for t in types}) != len(types):
        raise CatalogueError("Two contract types have the same key")
    return Catalogue(types=types, fields=fields)


def load(path: Path) -> Catalogue:
    return parse(path.read_text(encoding="utf-8"))


def default_queries(f: FieldDef) -> list[str]:
    """Search queries for a field without generated ones: its label and its description."""
    return list(dict.fromkeys([f.label, f.description]))


QUERY_SYSTEM = ("You write semantic search queries that find the passages of a contract stating a given data point. "
                "Return JSON only.")


def query_prompt(f: FieldDef, n: int) -> str:
    return (f"Data point: {f.key} ({f.label})\nDefinition: {f.description}\nValue type: {f.type_spec}\n\n"
            f"Write {n} different short search queries (4-10 words each) phrased the way contracts word this, "
            "e.g. clause headings and typical sentences. Vary the wording; no numbering.\n"
            'Return JSON: {"queries": ["...", "..."]}')


def parse_queries(text: str, n: int) -> list[str]:
    from .extraction.parsing import parse_json_lenient

    parsed = parse_json_lenient(text)
    items = parsed.get("queries") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        return []
    cleaned = [" ".join(str(q).split()) for q in items if isinstance(q, str) and q.strip()]
    return list(dict.fromkeys(cleaned))[:n]


def load_queries(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(isinstance(v, list) for v in data.values()):
        raise CatalogueError(f"{path} must map field keys to lists of queries")
    return data


def save_queries(path: Path, queries: dict[str, list[str]]) -> None:
    path.write_text(json.dumps(dict(sorted(queries.items())), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---- SQL --------------------------------------------------------------------------------------------


def _q(value: str | None) -> str:
    return "NULL" if value is None else "'" + value.replace("'", "''") + "'"


def _rows(rows: list[str]) -> str:
    return ",\n".join(f"    {r}" for r in rows)


def to_sql(cat: Catalogue, queries: dict[str, list[str]] | None = None, source: str = "docs/contract_types_and_fields.md") -> str:
    """Seed SQL that loads the catalogue into the field set created by seed.sql."""
    queries = queries or {}
    name, version = FIELD_SET
    fs = f"(SELECT id FROM field_sets WHERE name = {_q(name)} AND version = {version})"
    out = [
        f"-- GENERATED by `contract-extraction gen-catalogue` from {source}. Do not edit by hand:",
        "-- edit the document, regenerate, then recreate the database. Applied after seed.sql.",
        "",
        "BEGIN;",
        "",
        f"-- {len(cat.fields)} fields",
        "INSERT INTO fields (field_set_id, key, label, description, value_type, type_spec, value_schema, priority, position)",
        f"SELECT {fs}, v.key, v.label, v.description, v.value_type, v.type_spec, v.value_schema::jsonb, v.priority, v.position",
        "FROM (VALUES",
        _rows([f"({_q(f.key)}, {_q(f.label)}, {_q(f.description)}, {_q(f.value_type.value)}, {_q(f.type_spec)}, "
               f"{_q(json.dumps(f.value_schema, separators=(',', ':')))}, {_q(f.priority.value)}, {f.position})"
               for f in cat.fields.values()]),
        ") AS v (key, label, description, value_type, type_spec, value_schema, priority, position);",
        "",
        "-- Search queries (query expansion)",
        "INSERT INTO field_queries (field_id, position, query)",
        "SELECT f.id, v.position, v.query",
        "FROM fields f JOIN (VALUES",
        _rows([f"({_q(f.key)}, {i}, {_q(q)})"
               for f in cat.fields.values() for i, q in enumerate(queries.get(f.key) or default_queries(f), start=1)]),
        ") AS v (key, position, query) ON v.key = f.key",
        f"WHERE f.field_set_id = {fs};",
        "",
        f"-- {len(cat.types)} contract types ({cat.fallback.label} is the fallback)",
        "INSERT INTO contract_types (field_set_id, key, label, description, is_fallback, position)",
        f"SELECT {fs}, v.key, v.label, v.description, v.is_fallback, v.position",
        "FROM (VALUES",
        _rows([f"({_q(t.key)}, {_q(t.label)}, {_q(t.description)}, {'true' if t.is_fallback else 'false'}, {t.position})"
               for t in cat.types]),
        ") AS v (key, label, description, is_fallback, position);",
        "",
        "-- Fields each contract type expects, with the group and priority given in the document",
        "INSERT INTO contract_type_fields (contract_type_id, field_id, field_group, priority, position)",
        "SELECT t.id, f.id, v.field_group, v.priority, v.position",
        "FROM (VALUES",
        _rows([f"({_q(t.key)}, {_q(mb.key)}, {_q(mb.group)}, {_q(mb.priority.value)}, {i})"
               for t in cat.types for i, mb in enumerate(t.members, start=1)]),
        ") AS v (type_key, field_key, field_group, priority, position)",
        f"JOIN contract_types t ON t.key = v.type_key AND t.field_set_id = {fs}",
        f"JOIN fields f ON f.key = v.field_key AND f.field_set_id = {fs};",
        "",
        "COMMIT;",
        "",
    ]
    return "\n".join(out)
