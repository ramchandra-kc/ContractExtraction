"""Ground truth: human-labelled expected values per document and field.

A label is any JSON value except null that fits the field's value schema. The empty string means "not
in this contract" and matches a not_found outcome in ``v_run_evaluation`` (exact match); evaluation.py
adds partial credit. A document can also be labelled with its contract types, to measure classification.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ...core.errors import InvalidInput, NotFound
from ...extraction.validation import conform
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
        if expected_value != "":
            expected_value, problems = conform(expected_value, field.value_schema or {})
            if problems:
                raise InvalidInput(f"The label does not fit the type of {field.key!r} ({field.type_spec}): "
                                   + "; ".join(problems[:3]))
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

    def contract_types(self, document_id: uuid.UUID, field_set: m.FieldSet) -> list[m.ContractType]:
        """The document's labelled contract types in the field set, in catalogue order."""
        return list(self.session.scalars(
            select(m.ContractType).join(m.DocumentContractType, m.DocumentContractType.contract_type_id == m.ContractType.id)
            .where(m.DocumentContractType.document_id == document_id, m.ContractType.field_set_id == field_set.id)
            .order_by(m.ContractType.position)))

    def set_contract_types(self, document_id: uuid.UUID, field_set: m.FieldSet, keys: list[str]) -> list[m.ContractType]:
        """Replace the document's labelled contract types in the field set ([] clears them)."""
        known = {t.key: t for t in field_set.contract_types}
        unknown = [k for k in keys if k not in known]
        if unknown:
            raise InvalidInput(f"Unknown contract type(s) {unknown}; known: {sorted(known)}")
        self.session.execute(delete(m.DocumentContractType).where(
            m.DocumentContractType.document_id == document_id,
            m.DocumentContractType.contract_type_id.in_([t.id for t in known.values()])))
        self.session.add_all(m.DocumentContractType(document_id=document_id, contract_type_id=known[k].id)
                             for k in dict.fromkeys(keys))
        self.session.flush()
        return self.contract_types(document_id, field_set)

    def delete(self, document_id: uuid.UUID, field_id: uuid.UUID) -> None:
        result = self.session.execute(
            delete(m.GroundTruth).where(m.GroundTruth.document_id == document_id, m.GroundTruth.field_id == field_id))
        if result.rowcount == 0:
            raise NotFound("No ground truth for this field")
