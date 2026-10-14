"""Runs: enqueueing and lookup. Claiming, heartbeats and completion come with the worker (Phase 4)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.errors import Conflict, NotFound
from ...domain.config import PipelineConfig
from ...domain.enums import RunKind, RunState
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
