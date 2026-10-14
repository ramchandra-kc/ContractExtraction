"""Request dependencies: settings, storage and one database session per request."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from ..core.settings import Settings
from ..persistence.db import Database
from ..storage import FileStorage


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_storage(request: Request) -> FileStorage:
    return request.app.state.storage


def get_session(request: Request) -> Iterator[Session]:
    """Committed when the endpoint returns normally, rolled back when it raises."""
    with request.app.state.db.session() as session:
        yield session
