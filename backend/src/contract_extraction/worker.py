"""Worker process: takes queued runs from Postgres and executes them, one at a time.

    contract-extraction worker

Each loop: mark runs whose process died as failed → claim the oldest queued run
(``FOR UPDATE SKIP LOCKED``, so concurrent workers never share a run) → execute it.
Start more worker processes to process runs in parallel.

Stopping: the first Ctrl-C / SIGTERM cancels the current run at its next field and exits;
a second one exits immediately (the run is then marked failed once its heartbeat is stale).
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import uuid
from types import FrameType

from .core.settings import Settings
from .persistence.db import Database
from .persistence.repositories import RunRepo
from .pipeline.executor import Providers, RunExecutor
from .storage import FileStorage

log = logging.getLogger(__name__)


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


class Worker:
    def __init__(self, db: Database, storage: FileStorage, settings: Settings,
                 providers: Providers | None = None, worker_id: str | None = None):
        self.db = db
        self.settings = settings
        self.worker_id = worker_id or default_worker_id()
        self.executor = RunExecutor(db, storage, settings, providers, self.worker_id)
        self.stopping = threading.Event()

    def fail_stale(self) -> list[uuid.UUID]:
        with self.db.session() as s:
            ids = RunRepo(s).fail_stale(self.settings.worker.stale_after_seconds)
        for run_id in ids:
            log.warning("Run %s had no heartbeat; marked failed", run_id)
        return ids

    def run_once(self) -> uuid.UUID | None:
        """Clean up dead runs, then claim and execute at most one run. Returns its id."""
        self.fail_stale()
        with self.db.session() as s:
            run = RunRepo(s).claim_next(self.worker_id)
            run_id = run.id if run else None
        if run_id is not None:
            log.info("Worker %s took run %s", self.worker_id, run_id)
            state = self.executor.run_claimed(run_id)
            log.info("Run %s finished: %s", run_id, state)
        return run_id

    def run_forever(self) -> None:
        log.info("Worker %s polling every %ss (%s)", self.worker_id, self.settings.worker.poll_seconds, self.db.safe_url())
        while not self.stopping.is_set():
            try:
                claimed = self.run_once()
            except Exception:  # noqa: BLE001 - keep serving after transient database errors
                log.exception("Worker loop error")
                claimed = None
            if claimed is None:
                self.stopping.wait(self.settings.worker.poll_seconds)
        log.info("Worker %s stopped", self.worker_id)

    def stop(self) -> None:
        """Stop after cancelling the current run at its next field."""
        self.stopping.set()
        self.executor.stop_event.set()

    def install_signal_handlers(self) -> None:
        def handle(signum: int, frame: FrameType | None) -> None:
            if self.stopping.is_set():
                raise KeyboardInterrupt
            log.warning("Stopping: the current run is cancelled at its next field (repeat to exit now)")
            self.stop()

        signal.signal(signal.SIGINT, handle)
        signal.signal(signal.SIGTERM, handle)
