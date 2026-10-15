from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from contract_extraction.core.errors import InvalidInput
from contract_extraction.domain.config import Field, RetrievalConfig
from contract_extraction.domain.enums import FieldResultStatus, JudgeIssue, Verdict
from contract_extraction.extraction.judge import parse_verdict
from contract_extraction.extraction.parsing import field_value, parse_json_lenient
from contract_extraction.extraction.prompts import build_context, extraction_prompt, judge_prompt
from contract_extraction.extraction.retrieval import Hit, Retriever
from contract_extraction.pipeline.options import RunOptions, narrow
from contract_extraction.persistence.repositories import ConfigRepo
from contract_extraction.providers.base import Point, SearchHit

FIELD = Field(id=uuid.uuid4(), key="payment_terms", label="Payment Terms", value_type="text",
              user_prompt="Extract payment_terms as JSON.\n", position=1, queries=("payment terms", "invoice due"))


def rc(top_k=5, threshold="0.5", expansion=True, per_query_top=3, min_score="0.3") -> RetrievalConfig:
    return RetrievalConfig(id=uuid.uuid4(), name="RAGX", top_k=top_k, score_threshold=Decimal(threshold),
                           query_expansion=expansion, per_query_top=per_query_top, min_score=Decimal(min_score))


class FakeStore:
    """Returns scripted hits per query vector (the vector is [query index])."""

    def __init__(self, results: dict[int, list[tuple[str, float]]]):
        self.results = results
        self.ids = {name: uuid.uuid4() for hits in results.values() for name, _ in hits}
        self.limits: list[int] = []

    def search(self, collection, vector, limit):
        self.limits.append(limit)
        return [SearchHit(self.ids[name], score, {"page": 1, "text": f"text of {name}"})
                for name, score in self.results.get(int(vector[0]), [])[:limit]]


class IndexEmbedder:
    def __init__(self):
        self.seen: list[str] = []
        self.queries: dict[str, int] = {}

    def embed(self, texts):
        self.seen.extend(texts)
        return [[float(self.queries.setdefault(t, len(self.queries)))] for t in texts]


def test_retrieval_merges_dedupes_and_ranks():
    emb = IndexEmbedder()
    store = FakeStore({0: [("a", 0.9), ("b", 0.6), ("c", 0.4)], 1: [("b", 0.8), ("d", 0.7)]})
    hits = Retriever(store, "col", emb).retrieve(FIELD, rc(top_k=3))

    assert [h.text for h in hits] == ["text of a", "text of b", "text of d"]
    assert [h.score for h in hits] == [0.9, 0.8, 0.7]
    assert hits[1].matched_query == "invoice due", "dedupe keeps the best score and its query"
    assert store.limits == [3, 3]


def test_retrieval_without_expansion_uses_label():
    emb = IndexEmbedder()
    hits = Retriever(FakeStore({0: [("a", 0.9)]}), "col", emb).retrieve(FIELD, rc(expansion=False))
    assert emb.seen == ["Payment Terms"] and hits[0].matched_query is None


def test_retrieval_thresholds_and_cache():
    emb = IndexEmbedder()
    retriever = Retriever(FakeStore({0: [("a", 0.55), ("b", 0.45)], 1: []}), "col", emb)
    assert [h.text for h in retriever.retrieve(FIELD, rc(threshold="0.5"))] == ["text of a"]
    assert [h.text for h in retriever.retrieve(FIELD, rc(threshold="0.4", min_score="0.5"))] == ["text of a"]
    assert [h.text for h in retriever.retrieve(FIELD, rc(threshold="0.4", min_score="0.3"))] == ["text of a", "text of b"]
    assert emb.seen == ["payment terms", "invoice due"], "query embeddings are cached across configs"


def test_prompts():
    hits = [Hit(uuid.uuid4(), 0.9, 1, "Invoices are payable in 30 days.", None), Hit(uuid.uuid4(), 0.8, 1, "tiny", None)]
    context = build_context(hits)
    assert context == "Invoices are payable in 30 days.\n"
    assert extraction_prompt(FIELD, context) == "Extract payment_terms as JSON.\n<<<\nInvoices are payable in 30 days.\n\n>>>"
    assert judge_prompt(FIELD, context, '{"payment_terms": "30 days"}').startswith("Question: Extract Payment Terms\nContext: ")


CATALOGUE_FIELD = Field(id=uuid.uuid4(), key="late_payment_interest", label="Late payment interest",
                        description="Interest or fees on overdue amounts", value_type="json",
                        type_spec="object: rate, basis", position=2,
                        value_schema={"type": "object", "properties": {"rate": {}, "basis": {}}})


def test_generic_prompt_for_catalogue_fields():
    prompt = extraction_prompt(CATALOGUE_FIELD, "ctx")
    assert prompt.startswith("Task: From the given contract text chunks, extract the following field:\nlate_payment_interest\n")
    assert "Interest or fees on overdue amounts" in prompt
    assert "An object with the keys rate, basis; null for keys the text does not state." in prompt
    assert 'JSON Format:\n{"late_payment_interest": {"rate": null, "basis": null}}\nInput Chunks:<<<\nctx\n>>>' in prompt
    assert judge_prompt(CATALOGUE_FIELD, "ctx", "{}").startswith(
        "Question: Extract Late payment interest (Interest or fees on overdue amounts)\n")


@pytest.mark.parametrize("spec, expected", [
    ("enum: mutual, one_way", '"mutual | one_way"'),
    ("list of: name, rate", '[{"name": null, "rate": null}]'),
    ("strings", '[""]'),
    ("bool", "true"),
    ("money", '{"amount": 0, "currency": ""}'),
])
def test_generic_prompt_json_shapes(spec, expected):
    from contract_extraction.catalogue import value_schema

    f = CATALOGUE_FIELD.model_copy(update={"type_spec": spec, "value_schema": value_schema(spec)})
    assert f'{{"late_payment_interest": {expected}}}' in extraction_prompt(f, "")


def test_classifier_parsing():
    from decimal import Decimal

    from contract_extraction.extraction.classify import Candidate, parse_classification, select

    known = {"msa", "sow", "nda", "other"}
    got = parse_classification('Sure: {"types": [{"key": "SOW", "confidence": "85%", "evidence": "Statement of Work No. 4"},'
                               ' {"key": "msa", "confidence": 0.4}, {"key": "lease", "confidence": 0.99},'
                               ' {"key": "sow", "confidence": 0.1}, "nda"]}', known)
    assert [(c.key, float(c.confidence)) for c in got] == [("nda", 1.0), ("sow", 0.85), ("msa", 0.4)], \
        "unknown keys dropped, repeats keep the best, best first"
    assert got[1].evidence == "Statement of Work No. 4"
    assert [c.key for c in parse_classification('{"key": "msa"}', known)] == ["msa"], "missing confidence = 0.5"
    assert parse_classification('{"types": [{"key": "msa", "confidence": 7}]}', known)[0].confidence == Decimal("0.07")
    assert parse_classification("no idea", known) == []
    cands = [Candidate("msa", Decimal("0.9"), None), Candidate("other", Decimal("0.8"), None), Candidate("sow", Decimal("0.5"), None)]
    assert select(cands, Decimal("0.5"), "other") == ["msa", "sow"]
    assert select(cands, Decimal("0.95"), "other") == []


def test_opening_text():
    from contract_extraction.extraction.classify import opening_text

    chunks = [(1, "Title page"), (2, "Recitals"), (4, "Schedule")]
    assert opening_text(chunks, 2) == "Title page\nRecitals"
    assert opening_text(chunks, 9, max_chars=12) == "Title page\nR"
    assert opening_text([(10, "late start")], 3) == "late start"


@pytest.mark.parametrize("value, schema, expected, problems", [
    ("One Way", {"type": "string", "enum": ["mutual", "one_way"]}, "one_way", []),
    ("both", {"type": "string", "enum": ["mutual", "one_way"]}, "both", ["value: 'both' is not one of ['mutual', 'one_way']"]),
    ({"amount": "5", "currency": "AUD"}, {"type": "object", "properties": {"amount": {"type": ["number", "null"]}}},
     {"amount": "5", "currency": "AUD"}, ["value.amount: expected number or null, got str"]),
    ([{"role": "Dev", "rate": 1}], {"type": "array", "items": {"type": "object", "properties": {"role": {}, "rate": {}}}},
     [{"role": "Dev", "rate": 1}], []),
    (101, {"type": "number", "minimum": 0, "maximum": 100}, 101, ["value: 101 is above 100"]),
    (3.0, {"type": "integer"}, 3.0, []),
    (True, {"type": "number"}, True, ["value: expected number, got bool"]),
    ("anything", {}, "anything", []),
])
def test_conform(value, schema, expected, problems):
    from contract_extraction.extraction.validation import conform

    assert conform(value, schema) == (expected, problems)


def test_fields_for_types(session):
    fs = ConfigRepo(session).resolve_pipeline().field_set
    nda = fs.fields_for_types(["nda"])
    assert len(nda) == 42 and nda[0].key == "document_status", "P1 first"
    union = fs.fields_for_types(["msa", "sow"])
    assert len({f.key for f in union}) == len(union) == 66 + 10, "SOW adds only its own fields to the MSA's"
    assert [f.key for f in fs.fields_for_types([])] == [f.key for f in fs.fields_for_types(["other"])]
    p1 = fs.fields_for_types(["saas"], min_priority="P1")
    assert "service_levels" not in {f.key for f in p1}, "P2 for SaaS, even though it is P1 for an MSA"
    assert "service_levels" in {f.key for f in fs.fields_for_types(["saas", "msa"], min_priority="P1")}
    with pytest.raises(ValueError, match="Unknown contract type"):
        fs.fields_for_types(["lease"])


def test_batches_follow_the_document_groups(session):
    fs = ConfigRepo(session).resolve_pipeline().field_set
    fields = fs.fields_for_types(["msa", "sow"])
    batches = fs.batches(fields, ["msa", "sow"], max_fields=8)
    assert sorted(f.key for _, b in batches for f in b) == sorted(f.key for f in fields), "every field exactly once"
    names = [n for n, _ in batches]
    assert names[:3] == ["core 1/3", "core 2/3", "core 3/3"], "22 core fields split at 8"
    assert {"commercial 1/2", "msa 1/2", "sow 1/2"} <= set(names), "a type's own fields are named after it"
    assert all(len(b) <= 8 for _, b in batches)
    assert [n for n, _ in fs.batches(fields[:2], [], max_fields=8)] == ["core"]


def test_group_prompt():
    from contract_extraction.extraction.prompts import group_prompt

    prompt = group_prompt((FIELD, CATALOGUE_FIELD), "ctx")
    assert prompt.startswith("Task: From the given contract text chunks, extract the following fields:\n"
                             "payment_terms\nlate_payment_interest\n\nDefinitions:\n")
    assert "late_payment_interest (Late payment interest): Interest or fees on overdue amounts" in prompt
    assert 'JSON Format:\n{"payment_terms": "", "late_payment_interest": {"rate": null, "basis": null}}\nInput Chunks:<<<\nctx\n>>>' in prompt
    assert "Extract payment_terms as JSON." not in prompt, "hand-written prompts are not used in group mode"


def test_group_values():
    from contract_extraction.extraction.parsing import group_values

    got = group_values('```json\n{"a": "x", "b": null, "c": {"k": null}}\n```', ["a", "b", "c", "d"])
    assert got == {"a": (FieldResultStatus.EXTRACTED, "x"), "b": (FieldResultStatus.NOT_FOUND, None),
                   "c": (FieldResultStatus.NOT_FOUND, None), "d": (FieldResultStatus.NOT_FOUND, None)}
    assert group_values('["x"]', ["a"]) is None and group_values("nope", ["a"]) is None


def test_narrow_checks_contract_types(session):
    p = ConfigRepo(session).resolve_pipeline()
    assert narrow(p, RunOptions(contract_types=["msa", "sow"])).field_set == p.field_set, "types are chosen at run time"
    with pytest.raises(InvalidInput, match="Unknown contract type"):
        narrow(p, RunOptions(contract_types=["lease"]))
    with pytest.raises(InvalidInput, match="No contract types"):
        narrow(p, RunOptions(contract_types=[]))


@pytest.mark.parametrize("answer, expected", [
    ('{"payment_terms": "30 days"}', (FieldResultStatus.EXTRACTED, "30 days")),
    ('Sure!\n```json\n{"payment_terms": "30 days"}\n```', (FieldResultStatus.EXTRACTED, "30 days")),
    ('Here: {"terms": "net 30"} done', (FieldResultStatus.EXTRACTED, "net 30")),
    ('{"payment_terms": ""}', (FieldResultStatus.NOT_FOUND, None)),
    ('{"payment_terms": "N/A"}', (FieldResultStatus.NOT_FOUND, None)),
    ('{"payment_terms": [" ", null]}', (FieldResultStatus.NOT_FOUND, None)),
    ('{"payment_terms": ["30 days", "2% interest"]}', (FieldResultStatus.EXTRACTED, ["30 days", "2% interest"])),
    ("thirty days", (FieldResultStatus.EXTRACTED, "thirty days")),
    ("", (FieldResultStatus.NOT_FOUND, None)),
])
def test_field_value(answer, expected):
    assert field_value(answer, "payment_terms") == expected


def test_parse_json_lenient_gives_none_for_prose():
    assert parse_json_lenient("no json here") is None


def test_parse_verdict():
    ok = parse_verdict('{"status": "pass", "issue": "INCOMPLETE", "explanation": "Supported."}')
    assert (ok.verdict, ok.issue, ok.explanation) == (Verdict.PASS, JudgeIssue.NONE, "Supported.")
    fail = parse_verdict('```json\n{"status": "FAIL", "issue": "NO_CONTEXT", "explanation": "x"}\n```')
    assert (fail.verdict, fail.issue) == (Verdict.FAIL, JudgeIssue.NO_CONTEXT)
    assert parse_verdict("I think it's fine").verdict == Verdict.ERROR
    assert parse_verdict('{"status": "MAYBE"}').verdict == Verdict.ERROR
    assert parse_verdict('{"status": "FAIL", "issue": "WEIRD"}').issue is None


def test_narrow_options(session):
    p = ConfigRepo(session).resolve_pipeline()
    n = narrow(p, RunOptions(fields=["payment_terms", "title"], retrievals=["RAG07", "RAG02"], judge=False))
    assert [f.key for f in n.field_set.fields] == ["title", "payment_terms"], "pipeline order is kept"
    assert [r.name for r in n.retrievals] == ["RAG02", "RAG07"], "priority order is kept"
    assert not n.judge_enabled and n.judge_profile is None
    assert n.snapshot()["judge_enabled"] is False
    with pytest.raises(InvalidInput, match="Unknown field"):
        narrow(p, RunOptions(fields=["nope"]))
    with pytest.raises(InvalidInput, match="No fields"):
        narrow(p, RunOptions(fields=[]))
    with pytest.raises(ValidationError):
        RunOptions.model_validate({"bogus": 1})
