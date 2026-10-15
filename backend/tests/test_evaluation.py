"""Ground truth (GroundTruthRepo) and the evaluation views v_best_values / v_run_evaluation."""

from __future__ import annotations

import io

import pytest
from sqlalchemy import delete, func, select, update

from contract_extraction.core.errors import InvalidInput, NotFound
from contract_extraction.domain.enums import RunState
from contract_extraction.persistence import models as m
from contract_extraction.persistence.repositories import DocumentRepo, RunRepo
from contract_extraction.persistence.repositories.ground_truth import GroundTruthRepo
from contract_extraction.persistence.repositories.results import ResultRepo
from test_executor import Harness


@pytest.fixture
def document(session, storage):
    doc, _ = DocumentRepo(session).register(storage.stage(io.BytesIO(b"%PDF ground truth"), "gt.pdf"), storage)
    return doc


def _field(session, key: str) -> m.Field:
    return session.scalars(select(m.Field).where(m.Field.key == key)).one()


def _best(session, run_id) -> dict[str, tuple]:
    return {b["field_key"]: (b["retrieval_config"], b["value"], b["expected_value"], b["exact_match"])
            for b in ResultRepo(session).best_values(run_id)}


# ---- repository ----------------------------------------------------------------------------------


def test_labels_cover_every_enabled_field_of_the_default_field_set(session, document):
    repo = GroundTruthRepo(session)
    fs = repo.field_set()
    assert (fs.name, fs.version) == ("contract_fields", 1)
    labels = repo.labels(document.id, fs)
    assert len(labels) == 286 and all(gt is None for _, gt in labels)
    assert [f.position for f, _ in labels] == sorted(f.position for f, _ in labels)


def test_set_creates_then_replaces(session, document):
    repo, field = GroundTruthRepo(session), _field(session, "title")
    _, first = repo.set(document.id, field.id, "Acme Pty Ltd", "from the preamble")
    _, second = repo.set(document.id, field.id, ["Acme", "Contoso"])
    assert second.id == first.id and second.expected_value == ["Acme", "Contoso"] and second.notes is None
    labelled = {f.key: gt for f, gt in repo.labels(document.id, repo.field_set()) if gt}
    assert list(labelled) == ["title"]


def test_set_rejects_null_and_unknown_fields(session, document):
    repo = GroundTruthRepo(session)
    with pytest.raises(InvalidInput, match="must not be null"):
        repo.set(document.id, _field(session, "title").id, None)
    with pytest.raises(NotFound):
        repo.set(document.id, document.id, "x")
    with pytest.raises(NotFound):
        repo.field_set(document.id)


def test_delete_and_cascade(session, document):
    repo, field = GroundTruthRepo(session), _field(session, "title")
    repo.set(document.id, field.id, "Acme")
    repo.delete(document.id, field.id)
    with pytest.raises(NotFound):
        repo.delete(document.id, field.id)

    repo.set(document.id, field.id, "Acme")
    session.delete(document)
    session.flush()
    assert session.scalar(select(func.count()).select_from(m.GroundTruth).where(m.GroundTruth.document_id == document.id)) == 0


# ---- views ---------------------------------------------------------------------------------------


def test_best_values_rank_by_the_run_snapshot_not_the_live_pipeline(db, storage, tmp_path, session):
    h = Harness(db, storage, tmp_path, "ranking")
    run_id = h.enqueue()  # RAG01, RAG02, RAG07: every config gets the same answers, so priority decides
    assert h.execute(run_id) == RunState.SUCCEEDED
    before = _best(session, run_id)
    assert before["title"][0] == before["payment_terms"][0] == "RAG01"

    default = select(m.PipelineConfig.id).where(m.PipelineConfig.is_default).scalar_subquery()
    pcr = m.PipelineConfigRetrieval
    session.execute(update(pcr).where(pcr.pipeline_config_id == default).values(position=-pcr.position))  # reverse
    assert _best(session, run_id) == before
    rag01 = select(m.RetrievalConfig.id).where(m.RetrievalConfig.name == "RAG01").scalar_subquery()
    session.execute(delete(pcr).where(pcr.pipeline_config_id == default, pcr.retrieval_config_id == rag01))
    assert _best(session, run_id) == before


def test_exact_match(db, storage, tmp_path, session):
    h = Harness(db, storage, tmp_path, "match")
    run_id = h.enqueue()
    assert h.execute(run_id) == RunState.SUCCEEDED
    doc_id = RunRepo(session).get(run_id).document_id
    repo = GroundTruthRepo(session)

    assert _best(session, run_id)["title"][2:] == (None, None), "unlabelled"
    repo.set(doc_id, _field(session, "title").id, "  acme pty LTD ")
    repo.set(doc_id, _field(session, "payment_terms").id, "")  # not in this contract; the run found nothing
    best = _best(session, run_id)
    assert best["title"][3] is True
    assert best["payment_terms"][1:] == (None, "", True)

    repo.set(doc_id, _field(session, "title").id, "Contoso Limited")
    assert _best(session, run_id)["title"][3] is False


def test_an_error_outcome_never_matches(db, storage, tmp_path, session):
    h = Harness(db, storage, tmp_path, "errmatch", fail_on="payment_terms")
    run_id = h.enqueue()
    assert h.execute(run_id) == RunState.SUCCEEDED
    doc_id = RunRepo(session).get(run_id).document_id
    GroundTruthRepo(session).set(doc_id, _field(session, "payment_terms").id, "")
    row = next(b for b in ResultRepo(session).best_values(run_id) if b["field_key"] == "payment_terms")
    assert row["status"] == "error" and row["value"] is None and row["exact_match"] is False
