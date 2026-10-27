"""Experiments: a named, fixed design and the runs queued for it (``runs.experiment_id``)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.errors import Conflict, NotFound
from .. import models as m


class ExperimentRepo:
    def __init__(self, session: Session):
        self.session = session

    def create(self, name: str, design: dict[str, Any], description: str | None = None,
               hypothesis: str | None = None) -> m.Experiment:
        exp = m.Experiment(name=name, design=design, description=description, hypothesis=hypothesis)
        try:
            with self.session.begin_nested():
                self.session.add(exp)
                self.session.flush()
        except IntegrityError:
            raise Conflict(f"Experiment {name!r} already exists") from None
        return exp

    def get_by_name(self, name: str) -> m.Experiment:
        exp = self.session.scalars(select(m.Experiment).where(m.Experiment.name == name)).one_or_none()
        if exp is None:
            raise NotFound(f"Experiment {name!r} not found")
        return exp

    def list(self) -> list[tuple[m.Experiment, dict[str, int]]]:
        """Newest first, each with its run counts by state."""
        exps = self.session.scalars(select(m.Experiment).order_by(m.Experiment.created_at.desc())).all()
        counts: dict[uuid.UUID, dict[str, int]] = {}
        for exp_id, state, n in self.session.execute(
                select(m.Run.experiment_id, m.Run.state, func.count()).where(m.Run.experiment_id.is_not(None))
                .group_by(m.Run.experiment_id, m.Run.state)):
            counts.setdefault(exp_id, {})[state] = n
        return [(e, counts.get(e.id, {})) for e in exps]

    def runs(self, experiment_id: uuid.UUID) -> Sequence[m.Run]:
        """The experiment's runs, oldest first."""
        return self.session.scalars(
            select(m.Run).where(m.Run.experiment_id == experiment_id).order_by(m.Run.queued_at, m.Run.id)).all()
