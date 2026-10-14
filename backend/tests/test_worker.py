"""Worker, claiming, heartbeats, stale-run cleanup and cancellation (test database, scripted models)."""

from __future__ import annotations

import time

import pytest
from sqlalchemy import func, select, update

from contract_extraction.core.errors import Conflict
from contract_extraction.core.settings import WorkerSettings
from contract_extraction.domain.enums import RunState
from contract_extraction.persistence import models as m
from contract_extraction.persistence.repositories import RunRepo
from contract_extraction.pipeline.executor import RunExecutor
from contract_extraction.worker import Worker
from test_executor import Harness


@pytest.fixture(autouse=True)
def empty_queue(db):
    """Other tests may leave queued runs behind; start every test with an empty queue."""
    with db.session() as s:
        s.execute(update(m.Run).where(m.Run.state == "queued").values(state="cancelled", finished_at=func.now()))


def _run(db, run_id) -> m.Run:
    with db.session() as s:
        return RunRepo(s).get(run_id)


def test_concurrent_claims_get_different_runs(db, storage, tmp_path):
    first = Harness(db, storage, tmp_path, "claim-a").enqueue()
    second = Harness(db, storage, tmp_path, "claim-b").enqueue()
    with db.session() as a:
        run_a = RunRepo(a).claim_next("worker-a")  # row stays locked until this transaction ends
        with db.session() as b:
            run_b = RunRepo(b).claim_next("worker-b")
            assert run_b is not None and run_b.id != run_a.id
        assert {run_a.id, run_b.id} == {first, second}
        assert run_a.state == "running" and run_a.attempts == 1 and run_a.worker_id == "worker-a"
    with db.session() as s:
        assert RunRepo(s).claim_next("worker-c") is None


def test_inline_runs_are_never_claimable(db, storage, tmp_path):
    h = Harness(db, storage, tmp_path, "inline")
    from contract_extraction.ingestion import register_file
    from contract_extraction.pipeline.options import RunOptions

    options = RunOptions(fields=["customer_name"], retrievals=["RAG01"])
    doc_id, _, _ = register_file(db, storage, h.settings, h.pdf)
    with db.session() as s:
        run = RunRepo(s).enqueue(doc_id, h.pipeline(options), options=options.model_dump(exclude_defaults=True), start_as="cli")
        assert run.state == "running"
    with db.session() as s:
        assert RunRepo(s).claim_next("worker") is None


def test_stale_runs_are_failed(db, storage, tmp_path):
    stale = Harness(db, storage, tmp_path, "stale").enqueue()
    fresh = Harness(db, storage, tmp_path, "fresh").enqueue()
    with db.session() as s:
        repo = RunRepo(s)
        repo.start(stale, "dead-worker")
        repo.start(fresh, "live-worker")
        s.execute(update(m.Run).where(m.Run.id == stale).values(heartbeat_at=func.now() - func.make_interval(0, 0, 0, 0, 0, 10)))
    with db.session() as s:
        assert RunRepo(s).fail_stale(120) == [stale]
    run = _run(db, stale)
    assert run.state == "failed" and run.finished_at and "stopped responding" in run.error
    assert _run(db, fresh).state == "running"
    with db.session() as s:
        assert any("stopped responding" in e.message for e in RunRepo(s).events(stale))
        RunRepo(s).finish(fresh, RunState.CANCELLED)


def _fast_heartbeat(h: Harness) -> None:
    h.settings = h.settings.model_copy(update={"worker": WorkerSettings(heartbeat_seconds=0.05)})


def test_heartbeat_advances_during_slow_calls(db, storage, tmp_path):
    seen = []
    holder = {}

    def slow(n):
        if n == 1:
            seen.append(_run(db, holder["id"]).heartbeat_at)
            time.sleep(0.4)
            seen.append(_run(db, holder["id"]).heartbeat_at)

    h = Harness(db, storage, tmp_path, "heartbeat", on_call=slow)
    _fast_heartbeat(h)
    holder["id"] = run_id = h.enqueue()
    assert RunExecutor(db, storage, h.settings, h.providers).execute(run_id) == RunState.SUCCEEDED
    assert seen[1] > seen[0]


def test_executor_stops_when_its_run_was_failed_as_stale(db, storage, tmp_path):
    holder = {}

    def marked_stale_meanwhile(n):
        if n == 1:
            with db.session() as s:
                s.execute(update(m.Run).where(m.Run.id == holder["id"]).values(
                    state="failed", error="Worker stopped responding (test)", finished_at=func.now()))
            time.sleep(0.3)  # the heartbeat notices

    h = Harness(db, storage, tmp_path, "lost", on_call=marked_stale_meanwhile)
    _fast_heartbeat(h)
    holder["id"] = run_id = h.enqueue()
    assert RunExecutor(db, storage, h.settings, h.providers).execute(run_id) == RunState.FAILED
    run = _run(db, run_id)
    assert run.state == "failed" and run.error == "Worker stopped responding (test)", "outcome is not overwritten"
    with db.session() as s:
        results = s.scalar(select(func.count()).select_from(m.FieldResult).where(m.FieldResult.run_id == run_id))
    assert results == 1, "stopped at the next field"


def test_cancel(db, storage, tmp_path):
    queued = Harness(db, storage, tmp_path, "cancel-q").enqueue()
    running = Harness(db, storage, tmp_path, "cancel-r").enqueue()
    with db.session() as s:
        repo = RunRepo(s)
        assert repo.cancel(queued).state == "cancelled"
        repo.start(running, "w")
        assert repo.cancel(running).cancel_requested
        repo.finish(running, RunState.CANCELLED)
    with db.session() as s, pytest.raises(Conflict):
        RunRepo(s).cancel(queued)


def test_worker_processes_the_queue(db, storage, tmp_path):
    h = Harness(db, storage, tmp_path, "worker")
    run_id = h.enqueue()
    w = Worker(db, storage, h.settings, h.providers, worker_id="test-worker")
    assert w.run_once() == run_id
    run = _run(db, run_id)
    assert run.state == "succeeded" and run.worker_id == "test-worker" and run.progress_done == run.progress_total == 6
    assert w.run_once() is None


def test_stopped_worker_cancels_its_run_and_exits(db, storage, tmp_path):
    holder = {}
    h = Harness(db, storage, tmp_path, "shutdown", on_call=lambda n: holder["worker"].stop() if n == 1 else None)
    run_id = h.enqueue()
    w = holder["worker"] = Worker(db, storage, h.settings, h.providers)
    w.run_forever()  # returns once stopped
    run = _run(db, run_id)
    assert run.state == "cancelled"
    with db.session() as s:
        assert any("shutting down" in e.message for e in RunRepo(s).events(run_id))
