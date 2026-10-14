"""Ingestion: PDF → document → decomposition → vector index, driven by a resolved pipeline config.

Each stage reuses earlier work: the same file is one document (sha256), the latest
decomposition made with the same decomposition config is reused unless ``redecompose``,
and a ready index for (decomposition, index config) is reused.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from .core.errors import InvalidInput
from .core.settings import Settings
from .decomposition.service import decompose
from .domain.config import DecompositionConfig, PipelineConfig
from .indexing.indexer import IndexOutcome, build_index
from .persistence.db import Database
from .persistence.repositories import DocumentRepo
from .persistence.repositories.artifacts import DecompositionRepo
from .providers import factory
from .providers.base import Embedder, VectorStore
from .storage import FileStorage

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestResult:
    document_id: uuid.UUID
    document_code: str
    document_created: bool
    decomposition_id: uuid.UUID
    decomposition_reused: bool
    page_count: int
    index: IndexOutcome


def register_file(db: Database, storage: FileStorage, settings: Settings, pdf_path: Path) -> tuple[uuid.UUID, str, bool]:
    if not pdf_path.is_file():
        raise InvalidInput(f"File not found: {pdf_path}")
    with pdf_path.open("rb") as fh:
        staged = storage.stage(fh, pdf_path.name, settings.storage.max_upload_mb * 1024 * 1024)
    with db.session() as s:
        doc, created = DocumentRepo(s).register(staged, storage)
        return doc.id, doc.code, created


def ingest(
    db: Database,
    storage: FileStorage,
    settings: Settings,
    pipeline: PipelineConfig,
    *,
    pdf_path: Path | None = None,
    document_id: uuid.UUID | None = None,
    redecompose: bool = False,
    embedder: Embedder | None = None,
    store: VectorStore | None = None,
) -> IngestResult:
    """Ingest a new file (``pdf_path``) or an existing document (``document_id``)."""
    if (pdf_path is None) == (document_id is None):
        raise InvalidInput("Pass exactly one of pdf_path or document_id")

    created = False
    if pdf_path is not None:
        document_id, _, created = register_file(db, storage, settings, pdf_path)

    dec = ensure_decomposition(db, storage, document_id, pipeline.decomposition, redecompose)
    outcome = build_index(
        db, dec.decomposition_id, dec.document_code, pipeline.index,
        embedder or factory.embedder(pipeline.index.embedding_model, settings),
        store or factory.vector_store(pipeline.index.vector_store, settings),
    )
    return IngestResult(document_id, dec.document_code, created, dec.decomposition_id, dec.reused, dec.page_count, outcome)


@dataclass(frozen=True)
class DecompositionOutcome:
    document_code: str
    decomposition_id: uuid.UUID
    page_count: int
    reused: bool


def ensure_decomposition(db: Database, storage: FileStorage, document_id: uuid.UUID, cfg: DecompositionConfig,
                         redecompose: bool = False) -> DecompositionOutcome:
    """The latest decomposition of the document made with ``cfg``, or a new one."""
    with db.session() as s:
        doc = DocumentRepo(s).get(document_id)
        previous = None if redecompose else DecompositionRepo(s).latest_for_document(doc.id, cfg.id)
        if previous is not None:
            log.info("Reusing decomposition %s of %s", previous.id, doc.code)
            return DecompositionOutcome(doc.code, previous.id, previous.page_count, reused=True)
        dec = decompose(s, doc, cfg, storage)
        return DecompositionOutcome(doc.code, dec.id, dec.page_count, reused=False)
