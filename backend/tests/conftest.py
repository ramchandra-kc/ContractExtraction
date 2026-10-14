"""Test fixtures.

Database tests use a throwaway database (``contract_extraction_test`` by default, from
config/.env.test, or ``$TEST_DATABASE_URL``) on the Postgres started from docker/. It is
dropped and recreated once per test session from docker/schema.sql and docker/seed.sql;
every test runs inside a transaction that is rolled back. Without a reachable Postgres
the database tests are skipped.
"""

from __future__ import annotations

import os

os.environ["APP_ENV"] = "test"

from collections.abc import Iterator  # noqa: E402

import psycopg  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.engine import Engine, make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from contract_extraction.core.settings import BACKEND_ROOT, load_settings  # noqa: E402
from contract_extraction.persistence.db import Database  # noqa: E402
from contract_extraction.storage import FileStorage  # noqa: E402
from helpers import make_pdf  # noqa: E402

DOCKER_DIR = BACKEND_ROOT.parent / "docker"


def _test_url() -> str:
    return os.getenv("TEST_DATABASE_URL") or load_settings("test").database.url


def _libpq(url) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = make_url(_test_url())
    name = url.database
    if not name or not name.endswith("_test"):
        pytest.exit(f"Refusing to recreate {name!r}: the test database name must end in _test", returncode=2)
    try:
        admin = psycopg.connect(_libpq(url.set(database="postgres")), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not reachable at {url.render_as_string()} ({exc}). "
                    "Start it with: docker compose -f docker/docker-compose.yml up -d --build --wait")
    with admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{name}"')
    with psycopg.connect(_libpq(url), autocommit=True) as conn:
        for script in ("schema.sql", "seed.sql"):
            conn.execute((DOCKER_DIR / script).read_text(encoding="utf-8"))

    eng = create_engine(url)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back after the test (repository savepoints still work)."""
    with engine.connect() as conn:
        tx = conn.begin()
        s = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
        try:
            yield s
        finally:
            s.close()
            tx.rollback()


@pytest.fixture
def db(engine: Engine) -> Database:
    return Database(load_settings("test").database, engine=engine)


@pytest.fixture
def storage(tmp_path) -> FileStorage:
    return FileStorage(tmp_path / "storage")


@pytest.fixture
def sample_pdf(tmp_path):
    return make_pdf(tmp_path / "msa.pdf")
