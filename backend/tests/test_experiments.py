"""Experiments against the test database: design validation, the runner (queueing, rotation, resume, retries)
and the results, with runs executed by the worker and scripted models (see test_executor).

These tests commit; every test uses its own tag, documents and experiment name.
"""

from __future__ import annotations

import csv
import json
import uuid

import pytest
from sqlalchemy import func, update

from contract_extraction import experiments
from contract_extraction.core.errors import Conflict, InvalidInput, NotFound
from contract_extraction.domain.enums import Priority, RunState
from contract_extraction.ingestion import register_file
from contract_extraction.persistence import models as m
from contract_extraction.persistence.repositories import ConfigRepo, DocumentRepo, RunRepo
from contract_extraction.persistence.repositories.experiments import ExperimentRepo
from contract_extraction.persistence.repositories.ground_truth import GroundTruthRepo
from contract_extraction.worker import Worker
from helpers import BODY, make_pdf
from test_executor import Harness

PIPELINES = ["default", "local-fast"]


@pytest.fixture(autouse=True)
def empty_queue(db):
    with db.session() as s:
        s.execute(update(m.Run).where(m.Run.state.in_(["queued", "running"])).values(state="cancelled", finished_at=func.now()))


@pytest.fixture
def harness(db, storage, tmp_path):
    return Harness(db, storage, tmp_path, "exp")


def _docs(db, storage, harness, tmp_path, labels: list[dict]) -> tuple[str, list[str]]:
    """One tagged document per label dict (field key → expected value); returns the tag and the codes."""
    tag, codes = f"exp-{uuid.uuid4().hex[:8]}", []
    for i, doc_labels in enumerate(labels):
        pdf = make_pdf(tmp_path / f"{tag}-{i}.pdf", pages=[f"{b} {tag} {i}." for b in BODY])
        doc_id, code, _ = register_file(db, storage, harness.settings, pdf)
        codes.append(code)
        with db.session() as s:
            DocumentRepo(s).add_tags(doc_id, [tag])
            repo = GroundTruthRepo(s)
            fields = {f.key: f for f in repo.field_set().fields}
            for key, value in doc_labels.items():
                repo.set(doc_id, fields[key].id, value)
            repo.set_contract_types(doc_id, repo.field_set(), ["msa"])
    return tag, codes


def _process(db, storage, harness):
    """The 'sleep' between runner steps: execute every queued run like a worker (thresholds loosened as in test_api)."""
    while True:
        with db.session() as s:
            for run in RunRepo(s).list(state="queued")[0]:
                snap = dict(run.config_snapshot)
                snap["retrievals"] = [{**r, "score_threshold": "0", "min_score": "0"} for r in snap["retrievals"]]
                run.config_snapshot = snap
        if not Worker(db, storage, harness.settings, harness.providers, worker_id="exp-test").run_once():
            return


LABELS = [
    {"title": "Acme Pty Ltd", "payment_terms": ""},                        # title right, absence right
    {"title": "Other Co", "payment_terms": {"due_period": "P30D"}},         # title wrong, payment terms missed
]


def _create(db, tag, name=None, **kw):
    name = name or f"exp-{uuid.uuid4().hex[:8]}"
    with db.session() as s:
        experiments.create(s, name, pipelines=kw.pop("pipelines", PIPELINES), tag=tag, retrievals=["RAG07"], **kw)
    return name


def test_create_fixes_documents_and_fields(db, storage, harness, tmp_path):
    tag, codes = _docs(db, storage, harness, tmp_path, LABELS)
    name = _create(db, tag, repeats=2, hypothesis="per-field beats group")
    with db.session() as s:
        exp = ExperimentRepo(s).get_by_name(name)
        design = experiments.Design.model_validate(exp.design)
        assert exp.hypothesis == "per-field beats group"
        assert [d.code for d in design.documents] == codes
        assert all(d.fields == ["title", "payment_terms"] for d in design.documents), "labelled fields, catalogue order"
        assert (design.pipelines, design.repeats, design.retrievals, design.tag) == (PIPELINES, 2, ["RAG07"], tag)

    with db.session() as s:  # a label added later doesn't change the experiment
        doc = DocumentRepo(s).get_by_code(codes[0])
        repo = GroundTruthRepo(s)
        repo.set(doc.id, next(f.id for f in repo.field_set().fields if f.key == "governing_law"), "AU-NSW")
        assert experiments.Design.model_validate(ExperimentRepo(s).get_by_name(name).design).documents[0].fields == \
            ["title", "payment_terms"]


def test_create_validates(db, storage, harness, tmp_path):
    tag, _ = _docs(db, storage, harness, tmp_path, [{"title": "Acme Pty Ltd"}])
    unlabelled, _ = _docs(db, storage, harness, tmp_path, [{}])
    name = _create(db, tag)
    with pytest.raises(Conflict):
        _create(db, tag, name=name)
    with pytest.raises(InvalidInput, match="no labels"):
        _create(db, unlabelled)
    with pytest.raises(InvalidInput, match="No documents"):
        _create(db, "no-such-tag")
    with pytest.raises(InvalidInput, match="min_priority"):
        _create(db, tag, min_priority=Priority.P1)
    with pytest.raises(InvalidInput, match="Unknown RAG config"):
        with db.session() as s:
            experiments.create(s, "bad-rag", pipelines=PIPELINES, tag=tag, retrievals=["RAG01"])  # not in local-fast
    with pytest.raises(NotFound):
        _create(db, tag, pipelines=["no-such-pipeline"])

    name = _create(db, unlabelled, fields="types", min_priority=Priority.P1)  # contract types are labelled
    with db.session() as s:
        fields = experiments.Design.model_validate(ExperimentRepo(s).get_by_name(name).design).documents[0].fields
        msa_p1 = ConfigRepo(s).resolve_pipeline().field_set.fields_for_types(["msa"], Priority.P1)
        assert fields and fields == [f.key for f in msa_p1]


def test_runner_rotates_pipelines_and_finishes(db, storage, harness, tmp_path):
    tag, codes = _docs(db, storage, harness, tmp_path, LABELS)
    name = _create(db, tag, repeats=2)
    runner = experiments.ExperimentRunner(db, name)

    first = runner.step()
    assert (first.total, first.queued, first.pending, first.succeeded) == (8, 2, 6, 0), "one active run per document"
    with db.session() as s:
        queued = {r.document.code: r.config_snapshot["name"] for r in ExperimentRepo(s).runs(runner.experiment_id)}
        assert queued == {codes[0]: "default", codes[1]: "local-fast"}, "pipelines rotate per document"
        assert all(r.options["fields"] == ["title", "payment_terms"] and r.options["retrievals"] == ["RAG07"]
                   for r in ExperimentRepo(s).runs(runner.experiment_id))

    reports = []
    done = runner.run(poll=0, report=reports.append, sleep=lambda _: _process(db, storage, harness))
    assert done.finished and (done.succeeded, done.failed, done.given_up) == (8, 0, ())
    assert reports[0] == first and len(reports) > 2

    again = experiments.ExperimentRunner(db, name).step()  # a finished experiment queues nothing
    assert again.finished and again.queued == 0


def test_runner_retries_then_gives_up(db, storage, harness, tmp_path):
    tag, codes = _docs(db, storage, harness, tmp_path, LABELS[:1])
    name = _create(db, tag, pipelines=["default"])
    runner = experiments.ExperimentRunner(db, name, retries=1)

    def fail_queued():
        with db.session() as s:
            s.execute(update(m.Run).where(m.Run.experiment_id == runner.experiment_id, m.Run.state == "queued")
                      .values(state="failed", error="boom", finished_at=func.now()))

    runner.step()
    fail_queued()
    assert runner.step().queued == 1, "first failure: retried"
    fail_queued()
    gave_up = runner.step()
    assert gave_up.finished and gave_up.given_up == (f"{codes[0]}/default",) and gave_up.failed == 2

    resumed = experiments.ExperimentRunner(db, name)  # a new invocation tries again
    assert resumed.step().queued == 1
    assert resumed.cancel_queued() == 1


def test_results_split_value_and_absent_labels(db, storage, harness, tmp_path):
    tag, codes = _docs(db, storage, harness, tmp_path, LABELS)
    name = _create(db, tag, repeats=2)
    experiments.ExperimentRunner(db, name).run(poll=0, report=lambda p: None,
                                               sleep=lambda _: _process(db, storage, harness))
    with db.session() as s:
        c = experiments.collect(s, name)
    assert len(c.runs) == 8 and len(c.results) == 16
    assert sorted({r.repeat for r in c.runs}) == [1, 2]

    rows = {r["pipeline"]: r for r in experiments.summary(c)}
    assert set(rows) == set(PIPELINES)
    for r in rows.values():
        # per run: title right (doc 1) and wrong (doc 2), payment terms missed (doc 2), absence right (doc 1)
        assert (r["runs_succeeded"], r["documents"], r["value_labels"], r["absent_labels"]) == (4, 2, 6, 2)
        assert (r["value_exact"], r["value_missed"], r["absent_correct"], r["invented"]) == (0.3333, 0.3333, 1.0, 0.0)
        assert r["value_score_sd"] == 0.0 and r["snapshots"] == 1
    assert rows["default"]["judge_pass"] == 4 and rows["default"]["judge_pass_correct"] == 0.5, "PASS on both titles"
    assert rows["default"]["llm_calls_per_run"] > 0 and rows["local-fast"]["judge_pass"] == 0, "local-fast has no judge"

    fields = {(r["pipeline"], r["field"]): r for r in experiments.per_field(c)}
    assert fields[("default", "title")]["value_exact"] == 0.5
    assert fields[("default", "payment_terms")]["absent_correct"] == 1.0

    files = experiments.export(c, tmp_path / "out")
    assert [f.name for f in files] == ["results.csv", "runs.csv", "fields.csv", "summary.csv", "experiment.json"]
    with (tmp_path / "out" / "results.csv").open() as fh:
        results = list(csv.DictReader(fh))
    assert len(results) == 16 and {r["label"] for r in results} == {"value", "absent"}
    assert json.loads(next(r for r in results if r["field"] == "payment_terms" and r["label"] == "value")["expected"]) \
        == {"due_period": "P30D"}
    assert json.loads((tmp_path / "out" / "experiment.json").read_text())["design"]["repeats"] == 2


def test_run_state_is_kept_for_unfinished_runs(db, storage, harness, tmp_path):
    tag, _ = _docs(db, storage, harness, tmp_path, LABELS[:1])
    name = _create(db, tag, pipelines=["default"])
    experiments.ExperimentRunner(db, name).step()
    with db.session() as s:
        c = experiments.collect(s, name)
    assert [(r.state, r.repeat) for r in c.runs] == [(RunState.QUEUED, None)]
    assert experiments.summary(c)[0]["runs_succeeded"] == 0
