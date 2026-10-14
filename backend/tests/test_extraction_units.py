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
    n = narrow(p, RunOptions(fields=["payment_terms", "customer_name"], retrievals=["RAG07", "RAG02"], judge=False))
    assert [f.key for f in n.field_set.fields] == ["customer_name", "payment_terms"], "pipeline order is kept"
    assert [r.name for r in n.retrievals] == ["RAG02", "RAG07"], "priority order is kept"
    assert not n.judge_enabled and n.judge_profile is None
    assert n.snapshot()["judge_enabled"] is False
    with pytest.raises(InvalidInput, match="Unknown field"):
        narrow(p, RunOptions(fields=["nope"]))
    with pytest.raises(InvalidInput, match="No fields"):
        narrow(p, RunOptions(fields=[]))
    with pytest.raises(ValidationError):
        RunOptions.model_validate({"bogus": 1})
