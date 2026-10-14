"""Ground truth: expected values per document and field, compared with best values in run results."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from ...persistence import models as m
from ...persistence.repositories import DocumentRepo
from ...persistence.repositories.ground_truth import GroundTruthRepo
from ..deps import get_session
from ..schemas import FieldSetRef, GroundTruthItem, GroundTruthOut, GroundTruthSet

router = APIRouter(prefix="/documents/{document_id}/ground-truth", tags=["ground truth"])


def _item(field: m.Field, label: m.GroundTruth | None) -> GroundTruthItem:
    return GroundTruthItem(
        field_id=field.id, field_key=field.key, field_label=field.label, value_type=field.value_type,
        expected_value=label.expected_value if label else None,
        notes=label.notes if label else None, updated_at=label.updated_at if label else None,
    )


@router.get("", response_model=GroundTruthOut)
def list_ground_truth(document_id: uuid.UUID, field_set_id: uuid.UUID | None = None,
                      session: Session = Depends(get_session)):
    """Every enabled field of a field set (the default pipeline's by default) with the document's label, if any."""
    DocumentRepo(session).get(document_id)
    repo = GroundTruthRepo(session)
    fs = repo.field_set(field_set_id)
    return GroundTruthOut(field_set=FieldSetRef(id=fs.id, name=fs.name, version=fs.version),
                          items=[_item(f, gt) for f, gt in repo.labels(document_id, fs)])


@router.put("/{field_id}", response_model=GroundTruthItem)
def set_ground_truth(document_id: uuid.UUID, field_id: uuid.UUID, body: GroundTruthSet,
                     session: Session = Depends(get_session)):
    """Create or replace a label. 422 for null; use "" for a value that is not in the contract."""
    DocumentRepo(session).get(document_id)
    return _item(*GroundTruthRepo(session).set(document_id, field_id, body.expected_value, body.notes))


@router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_ground_truth(document_id: uuid.UUID, field_id: uuid.UUID, session: Session = Depends(get_session)):
    DocumentRepo(session).get(document_id)
    GroundTruthRepo(session).delete(document_id, field_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
