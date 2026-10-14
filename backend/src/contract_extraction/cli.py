"""Command line entry point.

    contract-extraction check     settings, database connection, schema and default pipeline
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import inspect

from .core.errors import AppError
from .core.logging import setup_logging
from .core.settings import load_settings
from .persistence import models as m
from .persistence.db import Database
from .persistence.repositories import ConfigRepo


def check() -> int:
    settings = load_settings()
    setup_logging(settings.log_level)
    db = Database(settings.database)
    print(f"environment : {settings.app_env}")
    print(f"database    : {db.safe_url()}")
    print(f"storage     : {settings.storage_root}")
    print(f"qdrant      : {settings.qdrant.url}")
    try:
        db.ping()
        missing = set(m.Base.metadata.tables) - set(inspect(db.engine).get_table_names())
        if missing:
            print(f"FAIL schema : missing tables {sorted(missing)} (recreate the database from docker/schema.sql)")
            return 1
        with db.session() as s:
            p = ConfigRepo(s).resolve_pipeline()
    except AppError as exc:
        print(f"FAIL config : {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - report any connection problem plainly
        print(f"FAIL database: {exc.__class__.__name__}: {exc}")
        return 1
    finally:
        db.dispose()

    judge = f"{p.judge_profile.name} ({p.judge_profile.model.name})" if p.judge_enabled and p.judge_profile else "off"
    print(f"pipeline    : {p.name}")
    print(f"  extraction: {p.extraction_profile.name} ({p.extraction_profile.model.name} via {p.extraction_profile.model.provider.key})")
    print(f"  judge     : {judge}")
    print(f"  embedding : {p.index.embedding_model.name} (chunks {p.index.chunk_size}/{p.index.chunk_overlap}, {p.index.vector_store})")
    print(f"  fields    : {len(p.field_set.fields)} from {p.field_set.name} v{p.field_set.version}")
    print(f"  retrieval : {', '.join(r.name for r in p.retrievals)}")
    print("OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="contract-extraction")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="verify settings, database, schema and the default pipeline")
    args = parser.parse_args(argv)
    if args.command == "check":
        return check()
    return 2


if __name__ == "__main__":
    sys.exit(main())
