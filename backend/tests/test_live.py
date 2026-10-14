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
