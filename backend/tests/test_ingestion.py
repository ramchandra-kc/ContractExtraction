"""Ingestion against the test database with a fake embedder and the in-memory store.

These tests commit (the indexer works in several transactions), which is fine: the test
database is recreated for every test session.
"""

from __future__ import annotations

from contract_extraction.core.settings import load_settings
from contract_extraction.ingestion import ingest
from contract_extraction.persistence.repositories import ConfigRepo
from contract_extraction.persistence.repositories.artifacts import IndexRepo
from contract_extraction.providers.memory import MemoryStore

from helpers import BODY, HashEmbedder, make_pdf


def _pipeline(db):
    with db.session() as s:
        return ConfigRepo(s).resolve_pipeline()


def test_ingest_builds_and_reuses(db, storage, tmp_path):
    pdf = make_pdf(tmp_path / "ingest.pdf", pages=[b + " Ingest test one." for b in BODY])
    settings, pipeline, store, emb = load_settings("test"), _pipeline(db), MemoryStore(), HashEmbedder()

    first = ingest(db, storage, settings, pipeline, pdf_path=pdf, embedder=emb, store=store)
    assert first.document_created and not first.decomposition_reused and not first.index.reused
    assert first.page_count == 3 and first.index.chunk_count >= 3
    assert first.index.collection_name.startswith(f"ce-{first.document_code.lower()}-")

    with db.session() as s:
        chunks = IndexRepo(s).chunks(first.index.vector_index_id)
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
        assert {c.page_start for c in chunks} == {1, 2, 3}
        assert IndexRepo(s).get(first.index.vector_index_id).status == "ready"

    hits = store.search(first.index.collection_name, emb.embed(["payment terms invoices payable days"])[0], 1)
    assert hits[0].payload["page"] == 2 and "thirty (30) days" in hits[0].payload["text"]
    assert hits[0].id in {c.id for c in chunks}

    calls = emb.calls
    again = ingest(db, storage, settings, pipeline, pdf_path=pdf, embedder=emb, store=store)
    assert not again.document_created and again.document_id == first.document_id
    assert again.decomposition_reused and again.index.reused
    assert emb.calls == calls, "nothing re-embedded"


def test_missing_collection_is_rebuilt_with_same_ids(db, storage, tmp_path):
    pdf = make_pdf(tmp_path / "rebuild.pdf", pages=[b + " Rebuild test two." for b in BODY])
    settings, pipeline, store = load_settings("test"), _pipeline(db), MemoryStore()

    first = ingest(db, storage, settings, pipeline, pdf_path=pdf, embedder=HashEmbedder(), store=store)
    store.delete_collection(first.index.collection_name)

    again = ingest(db, storage, settings, pipeline, document_id=first.document_id, embedder=HashEmbedder(), store=store)
    assert not again.index.reused and again.index.vector_index_id == first.index.vector_index_id
    with db.session() as s:
        ids = {c.id for c in IndexRepo(s).chunks(first.index.vector_index_id)}
    hits = store.search(first.index.collection_name, HashEmbedder().embed(["force majeure"])[0], 10)
    assert {h.id for h in hits} <= ids and hits


def test_failed_embedding_marks_index_failed(db, storage, tmp_path):
    import pytest

    from contract_extraction.core.errors import InvalidConfig

    pdf = make_pdf(tmp_path / "fail.pdf", pages=[b + " Failure test three." for b in BODY])
    settings, pipeline = load_settings("test"), _pipeline(db)
    with pytest.raises(InvalidConfig, match="dimensions"):
        ingest(db, storage, settings, pipeline, pdf_path=pdf, embedder=HashEmbedder(dimension=8), store=MemoryStore())
    with db.session() as s:
        from sqlalchemy import select

        from contract_extraction.persistence import models as m

        statuses = s.scalars(select(m.VectorIndex.status).join(m.Decomposition).join(m.Document)
                             .where(m.Document.original_filename == "fail.pdf")).all()
    assert statuses == ["failed"]
