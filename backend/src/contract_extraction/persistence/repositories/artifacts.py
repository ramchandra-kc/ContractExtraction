"""Processing artifacts: decompositions with their pages and images, vector indexes with their chunks."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ...core.errors import NotFound
from ...domain.enums import IndexStatus
from .. import models as m


@dataclass(frozen=True)
class NewPage:
    page_number: int
    text: str
    text_format: str
    header: str | None = None
    footer: str | None = None
    width: float | None = None
    height: float | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class NewImage:
    page_number: int
    file_name: str
    storage_path: str
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class NewChunk:
    id: uuid.UUID
    chunk_index: int
    page_start: int
    page_end: int
    char_start: int | None
    char_end: int | None
    text: str
    search_text: str
    headings: str = ""


class DecompositionRepo:
    def __init__(self, session: Session):
        self.session = session

    def create(self, decomposition_id: uuid.UUID, document_id: uuid.UUID, config_id: uuid.UUID,
               config_snapshot: dict[str, Any], storage_dir: str, duration_ms: int,
               pages: list[NewPage], images: list[NewImage]) -> m.Decomposition:
        dec = m.Decomposition(id=decomposition_id, document_id=document_id, decomposition_config_id=config_id,
                              config_snapshot=config_snapshot, storage_dir=storage_dir, page_count=len(pages),
                              duration_ms=duration_ms)
        self.session.add(dec)
        page_ids: dict[int, uuid.UUID] = {}
        for p in pages:
            row = m.Page(id=uuid.uuid4(), decomposition_id=dec.id, page_number=p.page_number, text=p.text,
                         text_format=p.text_format, header=p.header, footer=p.footer, width=p.width, height=p.height,
                         metadata_=p.metadata or {})
            page_ids[p.page_number] = row.id
            self.session.add(row)
        for img in images:
            self.session.add(m.PageImage(page_id=page_ids[img.page_number], file_name=img.file_name,
                                         storage_path=img.storage_path, width=img.width, height=img.height))
        self.session.flush()
        return dec

    def get(self, decomposition_id: uuid.UUID) -> m.Decomposition:
        dec = self.session.get(m.Decomposition, decomposition_id)
        if dec is None:
            raise NotFound(f"Decomposition {decomposition_id} not found")
        return dec

    def latest_for_document(self, document_id: uuid.UUID, config_id: uuid.UUID | None = None) -> m.Decomposition | None:
        q = select(m.Decomposition).where(m.Decomposition.document_id == document_id)
        if config_id:
            q = q.where(m.Decomposition.decomposition_config_id == config_id)
        return self.session.scalars(q.order_by(m.Decomposition.created_at.desc()).limit(1)).first()

    def pages(self, decomposition_id: uuid.UUID) -> Sequence[m.Page]:
        return self.session.scalars(
            select(m.Page).where(m.Page.decomposition_id == decomposition_id).order_by(m.Page.page_number)
        ).all()

    def images(self, decomposition_id: uuid.UUID) -> Sequence[m.PageImage]:
        return self.session.scalars(
            select(m.PageImage).join(m.Page).where(m.Page.decomposition_id == decomposition_id)
            .order_by(m.Page.page_number, m.PageImage.file_name)
        ).all()


class IndexRepo:
    def __init__(self, session: Session):
        self.session = session

    def find(self, decomposition_id: uuid.UUID, index_config_id: uuid.UUID) -> m.VectorIndex | None:
        return self.session.scalars(select(m.VectorIndex).where(
            m.VectorIndex.decomposition_id == decomposition_id, m.VectorIndex.index_config_id == index_config_id,
        )).one_or_none()

    def get(self, index_id: uuid.UUID) -> m.VectorIndex:
        idx = self.session.get(m.VectorIndex, index_id)
        if idx is None:
            raise NotFound(f"Vector index {index_id} not found")
        return idx

    def create(self, decomposition_id: uuid.UUID, index_config_id: uuid.UUID, vector_store: str, collection_name: str,
               embedding_model_id: uuid.UUID, dimension: int) -> m.VectorIndex:
        idx = m.VectorIndex(decomposition_id=decomposition_id, index_config_id=index_config_id, vector_store=vector_store,
                            collection_name=collection_name, embedding_model_id=embedding_model_id, dimension=dimension,
                            status=IndexStatus.BUILDING)
        self.session.add(idx)
        self.session.flush()
        return idx

    def delete(self, index_id: uuid.UUID) -> None:
        self.session.execute(delete(m.VectorIndex).where(m.VectorIndex.id == index_id))

    def add_chunks(self, index_id: uuid.UUID, chunks: list[NewChunk]) -> None:
        self.session.add_all(
            m.Chunk(id=c.id, vector_index_id=index_id, chunk_index=c.chunk_index, page_start=c.page_start,
                    page_end=c.page_end, char_start=c.char_start, char_end=c.char_end, text=c.text,
                    search_text=c.search_text, headings=c.headings)
            for c in chunks
        )
        self.session.flush()

    def chunks(self, index_id: uuid.UUID) -> Sequence[m.Chunk]:
        return self.session.scalars(
            select(m.Chunk).where(m.Chunk.vector_index_id == index_id).order_by(m.Chunk.chunk_index)
        ).all()

    def chunks_by_ids(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, m.Chunk]:
        if not ids:
            return {}
        return {c.id: c for c in self.session.scalars(select(m.Chunk).where(m.Chunk.id.in_(ids)))}

    def set_status(self, index_id: uuid.UUID, status: IndexStatus, chunk_count: int | None = None,
                   error: str | None = None) -> None:
        idx = self.get(index_id)
        idx.status = status
        idx.error = error
        if chunk_count is not None:
            idx.chunk_count = chunk_count
        self.session.flush()
