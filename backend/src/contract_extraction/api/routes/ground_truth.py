"""Ground truth: expected values per document and field, and the document's contract types, compared with
run results."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from ...persistence import models as m
from ...persistence.repositories import DocumentRepo
from ...persistence.repositories.ground_truth import GroundTruthRepo
from ..deps import SessionDep
from ..schemas import ContractTypeOut, ContractTypesSet, FieldSetRef, GroundTruthItem, GroundTruthOut, GroundTruthSet

router = APIRouter(prefix="/documents/{document_id}/ground-truth", tags=["ground truth"])


def _item(field: m.Field, label: m.GroundTruth | None) -> GroundTruthItem:
    return GroundTruthItem(
        field_id=field.id, field_key=field.key, field_label=field.label, value_type=field.value_type,
        type_spec=field.type_spec, value_schema=field.value_schema, priority=field.priority,
        expected_value=label.expected_value if label else None,
        notes=label.notes if label else None, updated_at=label.updated_at if label else None,
    )


def _type(t: m.ContractType) -> ContractTypeOut:
    return ContractTypeOut(key=t.key, label=t.label, description=t.description, is_fallback=t.is_fallback,
                           field_keys=[mb.field.key for mb in t.members])


@router.get("", response_model=GroundTruthOut)
def list_ground_truth(document_id: uuid.UUID, session: SessionDep, field_set_id: uuid.UUID | None = None):
    """Every enabled field of a field set (the default pipeline's by default) with the document's label, if
    any, plus the set's contract types and the document's labelled ones."""
    DocumentRepo(session).get(document_id)
    repo = GroundTruthRepo(session)
    fs = repo.field_set(field_set_id)
    return GroundTruthOut(field_set=FieldSetRef(id=fs.id, name=fs.name, version=fs.version),
                          items=[_item(f, gt) for f, gt in repo.labels(document_id, fs)],
                          contract_types=[_type(t) for t in fs.contract_types],
                          expected_contract_types=[t.key for t in repo.contract_types(document_id, fs)])


@router.put("/contract-types", response_model=list[str])
def set_contract_types(document_id: uuid.UUID, body: ContractTypesSet, session: SessionDep,
                       field_set_id: uuid.UUID | None = None):
    """Replace the document's labelled contract types (keys of the default pipeline's field set by default)."""
    DocumentRepo(session).get(document_id)
    repo = GroundTruthRepo(session)
    return [t.key for t in repo.set_contract_types(document_id, repo.field_set(field_set_id), body.contract_types)]


@router.put("/{field_id}", response_model=GroundTruthItem)
def set_ground_truth(document_id: uuid.UUID, field_id: uuid.UUID, body: GroundTruthSet,
                     session: SessionDep):
    """Create or replace a label. 422 for null or a value that does not fit the field's type; use "" for a
    value that is not in the contract."""
    DocumentRepo(session).get(document_id)
    return _item(*GroundTruthRepo(session).set(document_id, field_id, body.expected_value, body.notes))


@router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_ground_truth(document_id: uuid.UUID, field_id: uuid.UUID, session: SessionDep):
    DocumentRepo(session).get(document_id)
    GroundTruthRepo(session).delete(document_id, field_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
