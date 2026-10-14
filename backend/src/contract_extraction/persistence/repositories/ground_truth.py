"""Ground truth: human-labelled expected values per document and field.

A label is any JSON value except null. The empty string means "not in this contract" and matches a
not_found outcome in ``v_run_evaluation``. Matching itself lives only in that view.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ...core.errors import InvalidInput, NotFound
from .. import models as m


class GroundTruthRepo:
    def __init__(self, session: Session):
        self.session = session

    def field_set(self, field_set_id: uuid.UUID | None = None) -> m.FieldSet:
        """The given field set, or the default pipeline's (read from its row, so labeling works even when
        the pipeline cannot be resolved, e.g. with a disabled provider)."""
        if field_set_id is not None:
            fs = self.session.get(m.FieldSet, field_set_id)
            if fs is None:
                raise NotFound(f"Field set {field_set_id} not found")
            return fs
        fs = self.session.scalars(
            select(m.FieldSet).join(m.PipelineConfig, m.PipelineConfig.field_set_id == m.FieldSet.id)
            .where(m.PipelineConfig.is_default)
        ).one_or_none()
        if fs is None:
            raise NotFound("No default pipeline config")
        return fs

    def labels(self, document_id: uuid.UUID, field_set: m.FieldSet) -> list[tuple[m.Field, m.GroundTruth | None]]:
        """Every enabled field of the set in position order, with its label for the document (or None)."""
        rows = self.session.execute(
            select(m.Field, m.GroundTruth)
            .outerjoin(m.GroundTruth, and_(m.GroundTruth.field_id == m.Field.id, m.GroundTruth.document_id == document_id))
            .where(m.Field.field_set_id == field_set.id, m.Field.is_enabled)
            .order_by(m.Field.position)
        ).all()
        return [(f, gt) for f, gt in rows]

    def set(self, document_id: uuid.UUID, field_id: uuid.UUID, expected_value: Any,
            notes: str | None = None) -> tuple[m.Field, m.GroundTruth]:
        """Create or replace the label of one field."""
        field = self.session.get(m.Field, field_id)
        if field is None:
            raise NotFound(f"Field {field_id} not found")
        if expected_value is None:
            raise InvalidInput('expected_value must not be null; use "" for a value that is not in this contract')
        stmt = insert(m.GroundTruth).values(document_id=document_id, field_id=field_id,
                                            expected_value=expected_value, notes=notes)
        self.session.execute(stmt.on_conflict_do_update(
            constraint="uq_ground_truth_document_id_field_id",
            set_={"expected_value": stmt.excluded.expected_value, "notes": stmt.excluded.notes},
        ))
        label = self.session.scalars(
            select(m.GroundTruth).where(m.GroundTruth.document_id == document_id, m.GroundTruth.field_id == field_id)
            .execution_options(populate_existing=True)
        ).one()
        return field, label

    def delete(self, document_id: uuid.UUID, field_id: uuid.UUID) -> None:
        result = self.session.execute(
            delete(m.GroundTruth).where(m.GroundTruth.document_id == document_id, m.GroundTruth.field_id == field_id))
        if result.rowcount == 0:
            raise NotFound("No ground truth for this field")
