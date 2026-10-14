"""Command line entry point.

    contract-extraction check                 settings, database, schema, default pipeline, Qdrant and LLM providers
    contract-extraction ingest <pdf>          register, decompose and index a PDF with a pipeline config
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx
from sqlalchemy import inspect

from .core.errors import AppError
from .core.logging import setup_logging
from .core.settings import Settings, load_settings
from .domain.config import PipelineConfig
from .domain.enums import ProviderKind
from .persistence import models as m
from .persistence.db import Database
from .persistence.repositories import ConfigRepo
from .providers.base import ProviderError
from .providers.qdrant import QdrantStore
from .storage import FileStorage


def _ping_providers(pipeline: PipelineConfig, settings: Settings) -> list[str]:
    """One line per distinct endpoint used by the pipeline; failures are prefixed with FAIL."""
    lines = []
    if pipeline.index.vector_store == "qdrant":
        try:
            QdrantStore(settings.qdrant.url, settings.qdrant.api_key or None).ping()
            lines.append(f"  qdrant    : ok ({settings.qdrant.url})")
        except ProviderError as exc:
            lines.append(f"FAIL qdrant : {exc}")
    models = [pipeline.extraction_profile.model, pipeline.index.embedding_model]
    if pipeline.judge_profile:
        models.append(pipeline.judge_profile.model)
    seen = set()
    for model in models:
        p = model.provider
        if (p.key, model.name) in seen:
            continue
        seen.add((p.key, model.name))
        if p.kind != ProviderKind.OLLAMA:
            lines.append(f"  {p.key:<10}: {model.name} (hosted; key from {p.api_key_env or 'none'})")
            continue
        try:
            tags = httpx.get(f"{p.base_url.rstrip('/')}/api/tags", timeout=5).json()
            names = {t.get("name") for t in tags.get("models", [])}
            if model.name in names:
                lines.append(f"  {p.key}: {model.name} ok ({p.base_url})")
            else:
                lines.append(f"FAIL {p.key}: {model.name} is not available at {p.base_url} (pull it, or point the provider elsewhere)")
        except (httpx.HTTPError, ValueError) as exc:
            lines.append(f"FAIL {p.key}: {p.base_url} unreachable ({exc.__class__.__name__})")
    return lines


def check() -> int:
    settings = load_settings()
    setup_logging(settings.log_level)
    db = Database(settings.database)
    print(f"environment : {settings.app_env}")
    print(f"database    : {db.safe_url()}")
    print(f"storage     : {settings.storage_root}")
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
    print(f"  decompose : {p.decomposition.name} ({p.decomposition.method}, {p.decomposition.text_format})")
    print(f"  extraction: {p.extraction_profile.name} ({p.extraction_profile.model.name} via {p.extraction_profile.model.provider.key})")
    print(f"  judge     : {judge}")
    print(f"  embedding : {p.index.embedding_model.name} (chunks {p.index.chunk_size}/{p.index.chunk_overlap}, {p.index.vector_store})")
    print(f"  fields    : {len(p.field_set.fields)} from {p.field_set.name} v{p.field_set.version}")
    print(f"  retrieval : {', '.join(r.name for r in p.retrievals)}")
    print("services    :")
    lines = _ping_providers(p, settings)
    print("\n".join(lines))
    failed = any("FAIL" in line for line in lines)
    print("FAIL" if failed else "OK")
    return 1 if failed else 0


def ingest(pdf: Path, pipeline_name: str | None, redecompose: bool) -> int:
    from .ingestion import ingest as run_ingest

    settings = load_settings()
    setup_logging(settings.log_level)
    db = Database(settings.database)
    try:
        with db.session() as s:
            pipeline = ConfigRepo(s).resolve_pipeline(pipeline_name)
        r = run_ingest(db, FileStorage(settings.storage_root), settings, pipeline, pdf_path=pdf, redecompose=redecompose)
    except (AppError, ProviderError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        db.dispose()
    print(f"document     : {r.document_code} ({'new' if r.document_created else 'already stored'})")
    print(f"decomposition: {r.decomposition_id} ({'reused' if r.decomposition_reused else 'new'}, {r.page_count} pages)")
    print(f"index        : {r.index.collection_name} ({'reused' if r.index.reused else 'built'}, {r.index.chunk_count} chunks)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="contract-extraction")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="verify settings, database, default pipeline and services")
    p_ingest = sub.add_parser("ingest", help="register, decompose and index a PDF")
    p_ingest.add_argument("pdf", type=Path)
    p_ingest.add_argument("--pipeline", help="pipeline config name (default: the default pipeline)")
    p_ingest.add_argument("--redecompose", action="store_true", help="decompose again even if a decomposition exists")
    args = parser.parse_args(argv)
    if args.command == "check":
        return check()
    if args.command == "ingest":
        return ingest(args.pdf, args.pipeline, args.redecompose)
    return 2


if __name__ == "__main__":
    sys.exit(main())
