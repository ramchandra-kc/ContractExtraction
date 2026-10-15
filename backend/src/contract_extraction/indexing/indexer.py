"""Indexing stage: pages → chunks → embeddings → vector collection, with chunk rows as the record.

Chunks are embedded by their search text (``chunking.search_text``); the payload keeps the original
text, which is what the extraction model reads.

``chunks`` rows are the source of truth (``chunks.id`` is the point id in the store), so a
ready index whose collection has disappeared (e.g. Qdrant volume wiped) is rebuilt from its
rows with the same ids, keeping retrieval evidence of earlier runs valid.

Each step commits on its own: the 'building' row is visible while embeddings run, and a
failure is recorded as 'failed' with the error.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from ..core.errors import InvalidConfig
from ..domain.config import IndexConfig
from ..domain.enums import IndexStatus
from ..persistence import models as m
from ..persistence.db import Database
from ..persistence.repositories.artifacts import DecompositionRepo, IndexRepo, NewChunk
from ..providers.base import Embedder, Point, VectorStore
from .chunking import TextChunk, chunk_page, page_section

log = logging.getLogger(__name__)
_UNSAFE = re.compile(r"[^a-z0-9_-]+")


@dataclass(frozen=True)
class IndexOutcome:
    vector_index_id: uuid.UUID
    collection_name: str
    chunk_count: int
    reused: bool


def collection_name(document_code: str, decomposition_id: uuid.UUID, config_name: str) -> str:
    return _UNSAFE.sub("-", f"ce-{document_code}-{decomposition_id.hex[:8]}-{config_name}".lower())


def _embed_all(embedder: Embedder, texts: list[str], batch_size: int, dimension: int) -> list[list[float]]:
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = embedder.embed(texts[i:i + batch_size])
        for v in batch:
            if len(v) != dimension:
                raise InvalidConfig(f"Embedding has {len(v)} dimensions; llm_models.embedding_dimension says {dimension}")
        vectors.extend(batch)
    return vectors


def _chunk_pages(pages: Iterable[m.Page], size: int, overlap: int) -> list[TextChunk]:
    """Chunks of every page, each page starting in the section the previous one ended in."""
    out: list[TextChunk] = []
    section: str | None = None
    for p in pages:
        out += chunk_page(p.page_number, p.text, p.text_format, size, overlap, section)
        section = page_section(p.text, p.text_format, section)
    return out


def _payload(document_code: str, decomposition_id: uuid.UUID, c: NewChunk) -> dict:
    return {"document_code": document_code, "decomposition_id": str(decomposition_id), "chunk_index": c.chunk_index,
            "page": c.page_start, "text": c.text}


def build_index(db: Database, decomposition_id: uuid.UUID, document_code: str, cfg: IndexConfig,
                embedder: Embedder, store: VectorStore) -> IndexOutcome:
    dimension = cfg.embedding_model.embedding_dimension
    if not dimension:
        raise InvalidConfig(f"Embedding model {cfg.embedding_model.name!r} has no embedding_dimension")

    with db.session() as s:
        repo = IndexRepo(s)
        existing = repo.find(decomposition_id, cfg.id)
        if existing is not None and existing.status == IndexStatus.READY:
            if store.exists(existing.collection_name):
                log.info("Reusing index %s (%d chunks)", existing.collection_name, existing.chunk_count)
                return IndexOutcome(existing.id, existing.collection_name, existing.chunk_count, reused=True)
            # Ready in the database but gone from the store: re-embed the stored chunks under the same ids.
            index_id, name, from_rows = existing.id, existing.collection_name, True
            chunks = [NewChunk(c.id, c.chunk_index, c.page_start, c.page_end, c.char_start, c.char_end, c.text,
                               c.search_text, c.headings)
                      for c in repo.chunks(existing.id)]
            log.warning("Collection %s is missing; rebuilding it from %d stored chunks", name, len(chunks))
        else:
            if existing is not None:  # building or failed: never used by a run, start over
                repo.delete(existing.id)
                s.flush()
            name, from_rows = collection_name(document_code, decomposition_id, cfg.name), False
            index_id = repo.create(decomposition_id, cfg.id, cfg.vector_store, name, cfg.embedding_model.id, dimension).id
            pieces = _chunk_pages(DecompositionRepo(s).pages(decomposition_id), cfg.chunk_size, cfg.chunk_overlap)
            chunks = [NewChunk(uuid.uuid4(), i, c.page_number, c.page_number, c.char_start, c.char_end, c.text,
                               c.search_text, c.headings)
                      for i, c in enumerate(pieces)]

    try:
        vectors = _embed_all(embedder, [c.search_text for c in chunks], cfg.batch_size, dimension)
        if not from_rows and store.exists(name):
            store.delete_collection(name)  # leftover of an earlier failed attempt
        store.ensure_collection(name, dimension, cfg.distance)
        store.upsert(name, [Point(c.id, v, _payload(document_code, decomposition_id, c))
                            for c, v in zip(chunks, vectors, strict=True)])
        with db.session() as s:
            repo = IndexRepo(s)
            if not from_rows:
                repo.add_chunks(index_id, chunks)
            repo.set_status(index_id, IndexStatus.READY, chunk_count=len(chunks))
    except Exception as exc:
        with db.session() as s:
            IndexRepo(s).set_status(index_id, IndexStatus.FAILED, error=f"{exc.__class__.__name__}: {exc}")
        raise

    log.info("Indexed %s: %d chunks into %s", document_code, len(chunks), name)
    return IndexOutcome(index_id, name, len(chunks), reused=False)
