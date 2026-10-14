"""Runs: enqueueing, lookup and execution state. Claiming and stale-run recovery come with the worker (Phase 4)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select, update
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
    ) -> m.Run:
        """Queue a run with the resolved pipeline stored as its config snapshot.

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
        run.state, run.worker_id, run.error = RunState.RUNNING, worker_id, None
        run.attempts += 1
        run.started_at = run.heartbeat_at = func.now()
        self.session.flush()
        return run

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

    def finish(self, run_id: uuid.UUID, state: RunState, error: str | None = None) -> None:
        self.session.execute(update(m.Run).where(m.Run.id == run_id).values(
            state=state, error=error, finished_at=func.now(), heartbeat_at=func.now()))

    def add_event(self, run_id: uuid.UUID, message: str, level: EventLevel = EventLevel.INFO,
                  stage: RunStage | None = None, data: dict[str, Any] | None = None) -> None:
        self.session.add(m.RunEvent(run_id=run_id, message=message, level=level, stage=stage, data=data or {}))
        self.session.flush()

    def events(self, run_id: uuid.UUID) -> Sequence[m.RunEvent]:
        return self.session.scalars(select(m.RunEvent).where(m.RunEvent.run_id == run_id).order_by(m.RunEvent.id)).all()
