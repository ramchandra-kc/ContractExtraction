from __future__ import annotations

import io

import pytest
from sqlalchemy import func

from contract_extraction.core.errors import Conflict
from contract_extraction.domain.enums import RunKind, RunState
from contract_extraction.persistence.repositories import ConfigRepo, DocumentRepo, RunRepo


@pytest.fixture
def document(session, storage):
    doc, _ = DocumentRepo(session).register(storage.stage(io.BytesIO(b"%PDF run test"), "c.pdf"), storage)
    return doc


def test_enqueue_stores_snapshot(session, document):
    pipeline = ConfigRepo(session).resolve_pipeline()
    run = RunRepo(session).enqueue(document.id, pipeline, RunKind.FULL, {"note": "x"})

    assert run.state == RunState.QUEUED
    assert run.pipeline_config_id == pipeline.id
    assert run.config_snapshot["name"] == "default"
    assert len(run.config_snapshot["field_set"]["fields"]) == 286
    assert len(run.config_snapshot["field_set"]["contract_types"]) == 19
    assert run.options == {"note": "x"}
    assert RunRepo(session).list_for_document(document.id) == [run]


def test_second_active_run_conflicts(session, document):
    pipeline = ConfigRepo(session).resolve_pipeline()
    repo = RunRepo(session)
    first = repo.enqueue(document.id, pipeline)
    with pytest.raises(Conflict):
        repo.enqueue(document.id, pipeline)

    first.state, first.finished_at = RunState.CANCELLED, func.now()
    session.flush()
    assert repo.enqueue(document.id, pipeline).state == RunState.QUEUED
