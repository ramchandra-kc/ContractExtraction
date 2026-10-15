"""Runs: enqueueing, lookup and execution state. Claiming and stale-run recovery come with the worker (Phase 4)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.errors import Conflict, NotFound
from ...domain.config import PipelineConfig
from ...domain.enums import EventLevel, RunKind, RunStage, RunState
from .. import models as m

_ACTIVE = (RunState.QUEUED, RunState.RUNNING)


class RunRepo:
    def __init__(self, session: Session):
        self.session = session

    def enqueue(
        self,
        document_id: uuid.UUID,
        pipeline: PipelineConfig,
        kind: RunKind = RunKind.FULL,
        options: dict[str, Any] | None = None,
        experiment_id: uuid.UUID | None = None,
        max_attempts: int = 1,
        start_as: str | None = None,
    ) -> m.Run:
        """Queue a run with the resolved pipeline stored as its config snapshot.

        With ``start_as`` (a worker id) the run is started in the same transaction, so no
        worker can claim it in between (used by the inline CLI path).
        Raises ``Conflict`` when the document already has a queued or running run.
        """
        active = self.active_for_document(document_id)
        if active is not None:
            raise Conflict(f"Document already has a {active.state} run ({active.id})")
        run = m.Run(document_id=document_id, pipeline_config_id=pipeline.id, experiment_id=experiment_id,
                    kind=kind, options=options or {}, config_snapshot=pipeline.snapshot(), max_attempts=max_attempts)
        try:
            with self.session.begin_nested():
                self.session.add(run)
                self.session.flush()
        except IntegrityError as exc:
            # uq_runs_active_document: a concurrent request queued a run first.
            if "uq_runs_active_document" in str(exc.orig):
                raise Conflict("Document already has an active run") from None
            raise
        if start_as:
            self._mark_running(run, start_as)
        return run

    def get(self, run_id: uuid.UUID) -> m.Run:
        run = self.session.get(m.Run, run_id)
        if run is None:
            raise NotFound(f"Run {run_id} not found")
        return run

    def active_for_document(self, document_id: uuid.UUID) -> m.Run | None:
        return self.session.scalars(
            select(m.Run).where(m.Run.document_id == document_id, m.Run.state.in_(_ACTIVE))
        ).one_or_none()

    def list_for_document(self, document_id: uuid.UUID) -> Sequence[m.Run]:
        """Newest first."""
        return self.session.scalars(
            select(m.Run).where(m.Run.document_id == document_id).order_by(m.Run.queued_at.desc())
        ).all()

    # ---- execution state (used by the executor) --------------------------------------------------

    def start(self, run_id: uuid.UUID, worker_id: str) -> m.Run:
        """queued → running. Raises ``Conflict`` for a run in any other state."""
        run = self.session.get(m.Run, run_id, with_for_update=True)
        if run is None:
            raise NotFound(f"Run {run_id} not found")
        if run.state != RunState.QUEUED:
            raise Conflict(f"Run {run_id} is {run.state}, not queued")
        return self._mark_running(run, worker_id)

    def _mark_running(self, run: m.Run, worker_id: str) -> m.Run:
        run.state, run.worker_id, run.error = RunState.RUNNING, worker_id, None
        run.attempts += 1
        run.started_at = run.heartbeat_at = func.now()
        self.session.flush()
        return run

    def claim_next(self, worker_id: str) -> m.Run | None:
        """Take the oldest queued run (or None). SKIP LOCKED: concurrent workers never get the same run."""
        run = self.session.scalars(
            select(m.Run).where(m.Run.state == RunState.QUEUED).order_by(m.Run.queued_at, m.Run.id)
            .limit(1).with_for_update(skip_locked=True)
        ).first()
        return self._mark_running(run, worker_id) if run else None

    def heartbeat(self, run_id: uuid.UUID, worker_id: str) -> bool:
        """Record that the run is alive. False when it is no longer running under this worker
        (e.g. it was marked failed as stale), so the executor should stop."""
        result = self.session.execute(update(m.Run).where(
            m.Run.id == run_id, m.Run.worker_id == worker_id, m.Run.state == RunState.RUNNING,
        ).values(heartbeat_at=func.now()))
        return result.rowcount == 1

    def fail_stale(self, stale_after_seconds: float) -> list[uuid.UUID]:
        """Mark running runs without a recent heartbeat as failed. Atomic, safe to run from many workers."""
        message = f"Worker stopped responding (no heartbeat for {int(stale_after_seconds)} s)"
        ids = list(self.session.scalars(
            update(m.Run).where(
                m.Run.state == RunState.RUNNING,
                m.Run.heartbeat_at < func.now() - func.make_interval(0, 0, 0, 0, 0, 0, stale_after_seconds),
            ).values(state=RunState.FAILED, error=message, finished_at=func.now()).returning(m.Run.id)
        ))
        for run_id in ids:
            self.add_event(run_id, message, EventLevel.ERROR)
        return ids

    def cancel(self, run_id: uuid.UUID) -> m.Run:
        """Queued → cancelled now; running → stop requested (picked up between fields and during model calls);
        finished → Conflict."""
        run = self.session.get(m.Run, run_id, with_for_update=True)
        if run is None:
            raise NotFound(f"Run {run_id} not found")
        if run.state == RunState.QUEUED:
            run.state, run.finished_at = RunState.CANCELLED, func.now()
            self.session.flush()
            self.add_event(run_id, "Cancelled before it started", EventLevel.WARNING)
        elif run.state == RunState.RUNNING:
            run.cancel_requested = True
            self.session.flush()
            self.add_event(run_id, "Cancellation requested", EventLevel.WARNING)
        else:
            raise Conflict(f"Run {run_id} is already {run.state}")
        self.session.refresh(run)
        return run

    def recent(self, limit: int = 20) -> Sequence[m.Run]:
        return self.session.scalars(select(m.Run).order_by(m.Run.queued_at.desc(), m.Run.id).limit(limit)).all()

    def set_stage(self, run_id: uuid.UUID, stage: RunStage) -> None:
        self.session.execute(update(m.Run).where(m.Run.id == run_id).values(stage=stage, heartbeat_at=func.now()))

    def set_progress(self, run_id: uuid.UUID, done: int, total: int) -> None:
        # GREATEST keeps progress monotonic when judge threads report out of order.
        self.session.execute(update(m.Run).where(m.Run.id == run_id).values(
            progress_total=total, progress_done=func.least(func.greatest(m.Run.progress_done, done), total),
            heartbeat_at=func.now()))

    def attach(self, run_id: uuid.UUID, decomposition_id: uuid.UUID | None = None,
               vector_index_id: uuid.UUID | None = None) -> None:
        values = {k: v for k, v in (("decomposition_id", decomposition_id), ("vector_index_id", vector_index_id)) if v}
        if values:
            self.session.execute(update(m.Run).where(m.Run.id == run_id).values(**values))

    def cancel_requested(self, run_id: uuid.UUID) -> bool:
        return bool(self.session.scalar(select(m.Run.cancel_requested).where(m.Run.id == run_id)))

    def request_cancel(self, run_id: uuid.UUID) -> None:
        self.session.execute(update(m.Run).where(m.Run.id == run_id).values(cancel_requested=True))

    def finish(self, run_id: uuid.UUID, state: RunState, error: str | None = None) -> bool:
        """running → final state. False (nothing changed) when the run is no longer running,
        e.g. it was already marked failed as stale; that outcome is kept."""
        result = self.session.execute(update(m.Run).where(m.Run.id == run_id, m.Run.state == RunState.RUNNING).values(
            state=state, error=error, finished_at=func.now(), heartbeat_at=func.now()))
        return result.rowcount == 1

    def add_event(self, run_id: uuid.UUID, message: str, level: EventLevel = EventLevel.INFO,
                  stage: RunStage | None = None, data: dict[str, Any] | None = None) -> None:
        self.session.add(m.RunEvent(run_id=run_id, message=message, level=level, stage=stage, data=data or {}))
        self.session.flush()

    def events(self, run_id: uuid.UUID, after: int | None = None) -> Sequence[m.RunEvent]:
        """The run's timeline in order; ``after`` returns only events newer than that event id (for polling)."""
        q = select(m.RunEvent).where(m.RunEvent.run_id == run_id)
        if after is not None:
            q = q.where(m.RunEvent.id > after)
        return self.session.scalars(q.order_by(m.RunEvent.id)).all()

    def list(self, state: RunState | None = None, document_id: uuid.UUID | None = None,
             limit: int = 25, offset: int = 0) -> tuple[Sequence[m.Run], int]:
        """Newest first, with the total count for paging."""
        conditions = [c for c in (m.Run.state == state if state else None,
                                  m.Run.document_id == document_id if document_id else None) if c is not None]
        rows = self.session.scalars(select(m.Run).where(*conditions)
                                    .order_by(m.Run.queued_at.desc(), m.Run.id).limit(limit).offset(offset)).all()
        total = self.session.scalar(select(func.count()).select_from(m.Run).where(*conditions)) or 0
        return rows, total

    def latest_for_documents(self, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, m.Run]:
        if not document_ids:
            return {}
        rows = self.session.scalars(
            select(m.Run).where(m.Run.document_id.in_(document_ids)).ext(distinct_on(m.Run.document_id))
            .order_by(m.Run.document_id, m.Run.queued_at.desc())
        ).all()
        return {r.document_id: r for r in rows}
