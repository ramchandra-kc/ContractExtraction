"""Documents: registration (deduplicated by content hash) and lookup."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.errors import NotFound
from ...domain.enums import DocumentFormat
from ...storage import FileStorage, StagedFile
from .. import models as m


class DocumentRepo:
    def __init__(self, session: Session):
        self.session = session

    def register(self, staged: StagedFile, storage: FileStorage, title: str | None = None, *,
                 fmt: DocumentFormat = DocumentFormat.PDF, mime_type: str = "application/pdf") -> tuple[m.Document, bool]:
        """Store a staged upload as a document. Returns ``(document, created)``.

        ``fmt`` and ``mime_type`` come from format detection (``decomposition.converters.detect``).
        The same content (sha256) is stored once: uploading it again discards the staged
        file and returns the existing document with ``created=False``.
        """
        existing = self.get_by_sha256(staged.sha256)
        if existing is not None:
            storage.discard(staged)
            return existing, False

        doc = m.Document(original_filename=staged.filename, title=title, sha256=staged.sha256,
                         size_bytes=staged.size_bytes, storage_path="", format=fmt.value, mime_type=mime_type)
        try:
            with self.session.begin_nested():
                self.session.add(doc)
                self.session.flush()  # assigns the DOCnnn code
        except IntegrityError:
            # Another upload of the same file won the race.
            storage.discard(staged)
            winner = self.get_by_sha256(staged.sha256)
            if winner is None:
                raise
            return winner, False

        doc.storage_path = storage.commit_source(staged, doc.code)
        self.session.flush()
        return doc, True

    def get(self, document_id: uuid.UUID) -> m.Document:
        doc = self.session.get(m.Document, document_id)
        if doc is None:
            raise NotFound(f"Document {document_id} not found")
        return doc

    def get_by_code(self, code: str) -> m.Document:
        doc = self.session.scalars(select(m.Document).where(m.Document.code == code)).one_or_none()
        if doc is None:
            raise NotFound(f"Document {code} not found")
        return doc

    def get_by_sha256(self, sha256: str) -> m.Document | None:
        return self.session.scalars(select(m.Document).where(m.Document.sha256 == sha256)).one_or_none()

    def add_tags(self, document_id: uuid.UUID, tags: list[str]) -> list[str]:
        """Add tags the document does not have yet; returns its tags."""
        doc = self.get(document_id)
        new = [t for t in dict.fromkeys(tags) if t not in doc.tags]
        if new:
            doc.tags = [*doc.tags, *new]
            self.session.flush()
        return doc.tags

    def remove_tags(self, document_id: uuid.UUID, tags: list[str]) -> list[str]:
        doc = self.get(document_id)
        if any(t in doc.tags for t in tags):
            doc.tags = [t for t in doc.tags if t not in tags]
            self.session.flush()
        return doc.tags

    def with_tag(self, tag: str) -> Sequence[m.Document]:
        """Documents carrying the tag, by code."""
        return self.session.scalars(
            select(m.Document).where(m.Document.tags.contains([tag])).order_by(m.Document.code)).all()

    def list(self, limit: int = 25, offset: int = 0, q: str | None = None) -> tuple[Sequence[m.Document], int]:
        """Newest first, with the total count for paging.

        ``q`` keeps documents whose code, title or original filename contains it (case-insensitive).
        """
        where = []
        if q and q.strip():
            pattern = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            where.append(or_(*(col.ilike(pattern, escape="\\") for col in
                               (m.Document.code, m.Document.title, m.Document.original_filename))))
        rows = self.session.scalars(
            select(m.Document).where(*where)
            .order_by(m.Document.created_at.desc(), m.Document.code.desc()).limit(limit).offset(offset)
        ).all()
        total = self.session.scalar(select(func.count()).select_from(m.Document).where(*where)) or 0
        return rows, total
