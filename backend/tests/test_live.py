"""Against real services: CE_LIVE=1 uv run pytest -m live

Uses the default pipeline's embedding model (Ollama) and Qdrant from the backend settings
(QDRANT__URL; set it in config/.env.local when Qdrant is not on the default port).
"""

from __future__ import annotations

import os

import pytest

from contract_extraction.core.settings import load_settings
from contract_extraction.ingestion import ingest
from contract_extraction.persistence.repositories import ConfigRepo
from contract_extraction.providers import factory

from helpers import BODY, make_pdf

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.getenv("CE_LIVE"), reason="set CE_LIVE=1 to run against real Ollama and Qdrant"),
]


def test_ingest_with_real_services(db, storage, tmp_path):
    settings = load_settings("test")
    with db.session() as s:
        pipeline = ConfigRepo(s).resolve_pipeline()
    pdf = make_pdf(tmp_path / "live.pdf", pages=[b + " Live test." for b in BODY])

    result = ingest(db, storage, settings, pipeline, pdf_path=pdf)
    store = factory.vector_store(pipeline.index.vector_store, settings)
    try:
        query = factory.embedder(pipeline.index.embedding_model, settings).embed(["When are invoices payable?"])[0]
        hits = store.search(result.index.collection_name, query, 3)
        assert hits and hits[0].payload["page"] == 2
    finally:
        store.delete_collection(result.index.collection_name)


def test_extraction_with_real_models(db, storage, tmp_path):
    """One field under one RAG config with the real extraction and judge models."""
    from contract_extraction.domain.enums import RunKind, RunState
    from contract_extraction.ingestion import register_file
    from contract_extraction.persistence.repositories import RunRepo
    from contract_extraction.persistence.repositories.results import ResultRepo
    from contract_extraction.pipeline.executor import RunExecutor
    from contract_extraction.pipeline.options import RunOptions, narrow

    settings = load_settings("test")
    options = RunOptions(fields=["parties"], retrievals=["RAG02"])
    with db.session() as s:
        pipeline = narrow(ConfigRepo(s).resolve_pipeline(), options)
    pdf = make_pdf(tmp_path / "live-run.pdf", pages=[b + " Live run." for b in BODY])
    doc_id, _, _ = register_file(db, storage, settings, pdf)
    with db.session() as s:
        run_id = RunRepo(s).enqueue(doc_id, pipeline, RunKind.FULL, options.model_dump(exclude_defaults=True)).id

    assert RunExecutor(db, storage, settings).execute(run_id) == RunState.SUCCEEDED
    with db.session() as s:
        best = ResultRepo(s).best_values(run_id)
        collection = RunRepo(s).get(run_id).vector_index.collection_name
    try:
        assert len(best) == 1 and best[0]["status"] == "extracted"
        assert "Acme" in str(best[0]["value"])
        assert best[0]["verdict"] in ("PASS", "FAIL")
    finally:
        factory.vector_store(pipeline.index.vector_store, settings).delete_collection(collection)
