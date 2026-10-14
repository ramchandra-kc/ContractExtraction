"""Engine and session handling."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from ..core.settings import DatabaseSettings


class Database:
    def __init__(self, settings: DatabaseSettings, engine: Engine | None = None):
        self.engine = engine or create_engine(
            settings.url, pool_size=settings.pool_size, max_overflow=settings.max_overflow,
            pool_pre_ping=True, echo=settings.echo,
        )
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """A session in one transaction: committed on success, rolled back on error."""
        with self._sessions() as session, session.begin():
            yield session

    def ping(self) -> None:
        with self.engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    def safe_url(self) -> str:
        return make_url(self.engine.url).render_as_string(hide_password=True)

    def dispose(self) -> None:
        self.engine.dispose()
