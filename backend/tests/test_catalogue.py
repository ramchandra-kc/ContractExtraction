"""The field catalogue document, its parser, and the generated seed SQL."""

from __future__ import annotations

import pytest

from contract_extraction import catalogue as c
from contract_extraction.core.settings import BACKEND_ROOT
from contract_extraction.domain.enums import Priority, ValueType

ROOT = BACKEND_ROOT.parent
DOC = ROOT / "docs" / "contract_types_and_fields.md"
QUERIES = ROOT / "docs" / "contract_field_queries.json"
SEED = ROOT / "docker" / "seed_catalogue.sql"


@pytest.fixture(scope="module")
def cat() -> c.Catalogue:
    return c.load(DOC)


def test_seed_is_generated_from_the_document(cat):
    assert SEED.read_text(encoding="utf-8") == c.to_sql(cat, c.load_queries(QUERIES)), (
        "docker/seed_catalogue.sql is out of date; run `uv run contract-extraction gen-catalogue` in backend/")


def test_document_shape(cat):
    sizes = {t.key: len(t.members) for t in cat.types}
    assert sizes == {"nda": 42, "msa": 66, "sow": 44, "saas": 65, "employment": 51, "contractor": 66, "goods_purchase": 56,
                     "supply_distribution": 70, "property_lease": 44, "equipment_lease": 42, "loan": 38, "ip_license": 68,
                     "jv_partnership": 52, "share_asset_purchase": 48, "franchise": 61, "construction": 46, "dpa": 35,
                     "amendment": 26, "other": 44}
    assert len(cat.fields) == 286 and cat.fallback.key == "other"
    groups = {}
    for t in cat.types:
        for mb in t.members:
            groups.setdefault(mb.group, set()).add(mb.key)
    assert {g: len(k) for g, k in groups.items() if g != "specific"} == {
        "core": 22, "commercial": 12, "risk_liability": 10, "restrictive_covenants": 7, "ip_data": 6}
    assert {mb.group for mb in cat.fallback.members} == {"core", "commercial", "risk_liability"}
    assert all(t.description for t in cat.types)


def test_field_definitions(cat):
    sl = cat.fields["service_levels"]
    assert sl.priority == Priority.P1, "highest priority among the types using it"
    assert {(t.key, mb.priority) for t in cat.types for mb in t.members if mb.key == "service_levels"} == {
        ("msa", Priority.P1), ("saas", Priority.P2)}
    assert {"franchise_territory", "franchise_royalty", "dpa_audit_rights", "territory", "royalty", "audit_rights"} <= set(cat.fields)
    assert cat.fields["wi_insurance"].label == "W&I insurance"
    assert cat.fields["total_contract_value"].value_type == ValueType.MONEY


@pytest.mark.parametrize("spec, schema, vtype", [
    ("text", {"type": "string"}, ValueType.TEXT),
    ("strings", {"type": "array", "items": {"type": "string"}}, ValueType.LIST),
    ("bool", {"type": "boolean"}, ValueType.BOOLEAN),
    ("percent", {"type": "number", "minimum": 0, "maximum": 100}, ValueType.NUMBER),
    ("date", {"type": "string", "format": "date"}, ValueType.DATE),
    ("enum: mutual, one_way", {"type": "string", "enum": ["mutual", "one_way"]}, ValueType.TEXT),
    ("object: rate, basis", {"type": "object", "properties": {"rate": {}, "basis": {}}}, ValueType.JSON),
    ("list of: role, rate", {"type": "array", "items": {"type": "object", "properties": {"role": {}, "rate": {}}}}, ValueType.JSON),
])
def test_type_specs(spec, schema, vtype):
    assert c.value_schema(spec) == schema and c.value_type(spec) == vtype


def test_composite_types_are_typed_and_nullable():
    money = c.value_schema("money")
    assert money["properties"]["amount"] == {"type": ["number", "null"]}
    assert c.value_schema("restriction")["properties"]["exists"] == {"type": ["boolean", "null"]}
    assert c.value_type("relative_date") == ValueType.JSON


def _doc(*sections: str) -> str:
    return "# Catalogue\n\n" + "\n\n".join(sections)


NDA = """## 1. NDA

**Identify by:** Confidentiality agreement.

### Core

| Field | Type | Priority | Description |
|---|---|---|---|
| `title` | string | P3 | Document title |

### NDA-Specific

| Field | Type | Priority | Description |
|---|---|---|---|
| `purpose` | text | P1 | Permitted purpose |"""

OTHER = """## 2. Other

**Identify by:** Anything else.

**Includes:** Core"""


def test_parse_minimal_document():
    cat = c.parse(_doc(NDA, OTHER))
    assert [t.key for t in cat.types] == ["nda", "other"]
    assert [(mb.key, mb.group) for mb in cat.types[0].members] == [("title", "core"), ("purpose", "specific")]
    assert [mb.key for mb in cat.fallback.members] == ["title"]
    sql = c.to_sql(cat, {"purpose": ["what may it be used for"]})
    assert "('purpose', 1, 'what may it be used for')" in sql and "('title', 1, 'Title')" in sql


@pytest.mark.parametrize("doc, error", [
    (_doc(NDA), "Exactly one fallback"),
    (_doc(NDA.replace("| text |", "| texts |"), OTHER), "Unknown field type 'texts'"),
    (_doc(NDA.replace("**Identify by:** Confidentiality agreement.\n", ""), OTHER), "no **Identify by:** line"),
    (_doc(NDA, OTHER.replace("Core", "Commercial")), "unknown group 'Commercial'"),
    (_doc(NDA, NDA.replace("## 1. NDA", "## 2. DPA").replace("Document title", "Title"), OTHER), "differs from its first"),
    (_doc(NDA, NDA.replace("## 1. NDA", "## 2. DPA").replace("NDA-Specific", "DPA-Specific")
          .replace("| text | P1 | Permitted purpose", "| strings | P1 | Purposes"), OTHER), "'purpose' in 'DPA' is defined as"),
    (_doc(NDA.replace("| `title` | string", "| `title` | string | P3 | Again |\n| `title` | string"), OTHER), "twice"),
])
def test_parse_rejects_inconsistent_documents(doc, error):
    with pytest.raises(c.CatalogueError, match=error.replace("*", r"\*").replace("(", r"\(")):
        c.parse(doc)


def test_parse_queries():
    assert c.parse_queries('{"queries": ["late fees", " late  fees ", "", 3, "interest on overdue"]}', 5) == [
        "late fees", "interest on overdue"]
    assert c.parse_queries('["a", "b", "c"]', 2) == ["a", "b"]
    assert c.parse_queries("no json", 3) == []
