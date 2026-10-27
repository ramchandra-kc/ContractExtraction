"""Retrieval-only evaluation against the test database, with the hash embedder and memory store of test_executor."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from contract_extraction import retrieval_eval
from contract_extraction.core.errors import NotFound
from contract_extraction.labels import notes_for
from contract_extraction.persistence.repositories import ConfigRepo, DocumentRepo
from contract_extraction.persistence.repositories.ground_truth import GroundTruthRepo
from test_executor import Harness
from test_experiments import LABELS, _docs


@pytest.fixture
def harness(db, storage, tmp_path):
    return Harness(db, storage, tmp_path, "reval")


def test_variants_copy_configs_per_top_k_and_threshold(db):
    with db.session() as s:
        rag02, rag07 = ConfigRepo(s).resolve_retrievals(["RAG02", "RAG07"])
        with pytest.raises(NotFound, match="RAG99"):
            ConfigRepo(s).resolve_retrievals(["RAG02", "RAG99"])
    assert retrieval_eval.variants([rag02]) == [rag02]
    vs = retrieval_eval.variants([rag02, rag07], [3, 10], [0.0])
    assert [v.name for v in vs] == ["RAG02 k=3 t=0", "RAG02 k=10 t=0", "RAG07 k=3 t=0", "RAG07 k=10 t=0"]
    assert (vs[1].top_k, vs[1].score_threshold, vs[1].min_score, vs[1].query_expansion) == (10, Decimal("0"), Decimal("0"), True)
    assert vs[2].keyword_search and vs[2].anchor_chunks == rag07.anchor_chunks, "other settings kept"


def test_evaluate_scores_evidence_without_llm_calls(db, storage, harness, tmp_path):
    tag, codes = _docs(db, storage, harness, tmp_path, LABELS)
    quotes = {(0, "title"): "made between Acme Pty Ltd (the Customer) and Contoso Limited",
              (1, "payment_terms"): "invoices are payable within thirty (30) days of receipt",
              (1, "title"): "a clause about liquidated damages for late delivery of the goods"}  # in no chunk
    with db.session() as s:
        repo = GroundTruthRepo(s)
        fields = {f.key: f for f in repo.field_set().fields}
        for (i, key), quote in quotes.items():
            doc = DocumentRepo(s).get_by_code(codes[i])
            repo.set(doc.id, fields[key].id, LABELS[i][key], notes_for({"confidence": "high", "evidence": quote}, "test"))
        docs = list(DocumentRepo(s).with_tag(tag))
        configs = retrieval_eval.variants(ConfigRepo(s).resolve_retrievals(["RAG02"]), [1, 5], [0.0])
        s.expunge_all()

    no_chat = replace(harness.providers, chat=lambda p: pytest.fail(f"LLM client requested: {p.name}"))
    rows = retrieval_eval.evaluate(db, storage, harness.settings, no_chat, None, docs, configs, report=lambda _: None)
    assert len(rows) == 3 * 2, "the three quoted labels × two variants; doc 1's absent label has no quote"
    by = {r["retrieval_config"]: r for r in retrieval_eval.summary(rows)}
    wide, narrow = by["RAG02 k=5 t=0"], by["RAG02 k=1 t=0"]
    assert wide["labels"] == 3 and wide["documents"] == 2
    assert wide["recall"] == round(2 / 3, 4) and wide["not_indexed"] == round(1 / 3, 4), "3 chunks per document: k=5 gets all"
    assert narrow["mean_hits"] == 1 and narrow["recall"] <= wide["recall"]
    assert narrow["recall"] == narrow["recall_at_1"] and wide["recall_at_1"] <= wide["recall_at_3"] == wide["recall"]
    lost = [r for r in rows if r.field == "title" and r.document == codes[1]]
    assert all(r.evidence_indexed is False and r.evidence_rank is None for r in lost)

    types = retrieval_eval.summary(rows, ("retrieval_config", "value_type"))
    assert {(t["retrieval_config"], t["value_type"]) for t in types} >= {("RAG02 k=5 t=0", "text")}
