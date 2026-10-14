"""Command line entry point.

    contract-extraction check                 settings, database, schema, default pipeline, Qdrant and LLM providers
    contract-extraction ingest <pdf>          register, decompose and index a PDF with a pipeline config
    contract-extraction run <pdf> [options]   ingest + extract every field under every RAG config (inline)
    contract-extraction providers [set KEY --base-url URL | --enable | --disable]
                                              list LLM providers / switch e.g. native ↔ Docker Ollama
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx
from sqlalchemy import func, inspect, select

from .core.errors import AppError
from .core.logging import setup_logging
from .core.settings import Settings, load_settings
from .domain.config import PipelineConfig
from .domain.enums import ProviderKind, RunKind, RunState
from .persistence import models as m
from .persistence.db import Database
from .persistence.repositories import ConfigRepo, RunRepo
from .persistence.repositories.results import ResultRepo
from .pipeline.options import RunOptions
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


def _short(value: object, width: int = 70) -> str:
    text = "" if value is None else value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= width else text[:width - 1] + "…"


def run(pdf: Path, pipeline_name: str | None, kind: str, options: RunOptions) -> int:
    from .ingestion import register_file
    from .pipeline.executor import RunExecutor
    from .pipeline.options import narrow

    settings = load_settings()
    setup_logging(settings.log_level)
    db = Database(settings.database)
    storage = FileStorage(settings.storage_root)
    run_id = None
    try:
        with db.session() as s:
            pipeline = narrow(ConfigRepo(s).resolve_pipeline(pipeline_name), options)
        document_id, code, _ = register_file(db, storage, settings, pdf)
        with db.session() as s:
            run_id = RunRepo(s).enqueue(document_id, pipeline, RunKind(kind), options.model_dump(exclude_defaults=True)).id
        calls = len(pipeline.field_set.fields) * len(pipeline.retrievals) * (2 if pipeline.judge_enabled else 1)
        print(f"run {run_id}: {code}, {len(pipeline.field_set.fields)} fields x {len(pipeline.retrievals)} RAG configs "
              f"(up to {calls} LLM calls)", flush=True)
        state = RunExecutor(db, storage, settings, worker_id="cli").execute(run_id)
    except KeyboardInterrupt:
        if run_id is not None:
            with db.session() as s:
                RunRepo(s).finish(run_id, RunState.CANCELLED, "Interrupted from the command line")
        print("cancelled", file=sys.stderr)
        return 130
    except (AppError, ProviderError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    try:
        with db.session() as s:
            r = RunRepo(s).get(run_id)
            best = ResultRepo(s).best_values(run_id)
            n_calls = s.scalar(select(func.count()).select_from(m.LlmCall).where(m.LlmCall.run_id == run_id))
            print(f"state: {r.state}  progress: {r.progress_done}/{r.progress_total}  LLM calls: {n_calls}"
                  + (f"  error: {r.error}" if r.error else ""))
            if best:
                print(f"\n{'field':30} {'value':70} {'config':7} verdict")
                for b in best:
                    print(f"{b['field_label'][:30]:30} {_short(b['value']):70} {b['retrieval_config']:7} {b['verdict'] or '-'}")
    finally:
        db.dispose()
    return 0 if state == RunState.SUCCEEDED else 1


def providers(key: str | None, base_url: str | None, enabled: bool | None) -> int:
    """List LLM providers, or change one (``key`` given)."""
    settings = load_settings()
    db = Database(settings.database)
    try:
        with db.session() as s:
            repo = ConfigRepo(s)
            if key is not None:
                if base_url is None and enabled is None:
                    print("Nothing to change: pass --base-url, --enable or --disable", file=sys.stderr)
                    return 2
                row = repo.update_provider(key, base_url, enabled)
                print(f"updated {row.key}: {row.base_url} ({'enabled' if row.is_enabled else 'disabled'})")
                return 0
            for p in repo.providers():
                models = ", ".join(f"{mo.name} ({mo.kind})" for mo in p.models) or "-"
                print(f"{p.key:14} {p.kind:18} {p.base_url:32} {'enabled ' if p.is_enabled else 'disabled'}  {models}")
            return 0
    except AppError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        db.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="contract-extraction")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="verify settings, database, default pipeline and services")
    p_ingest = sub.add_parser("ingest", help="register, decompose and index a PDF")
    p_ingest.add_argument("pdf", type=Path)
    p_ingest.add_argument("--pipeline", help="pipeline config name (default: the default pipeline)")
    p_ingest.add_argument("--redecompose", action="store_true", help="decompose again even if a decomposition exists")

    p_run = sub.add_parser("run", help="ingest a PDF and extract its fields (runs inline)")
    p_run.add_argument("pdf", type=Path)
    p_run.add_argument("--pipeline", help="pipeline config name (default: the default pipeline)")
    p_run.add_argument("--kind", choices=[k.value for k in RunKind], default=RunKind.FULL.value)
    p_run.add_argument("--fields", help="comma-separated field keys (default: all)")
    p_run.add_argument("--retrievals", help="comma-separated RAG config names (default: all of the pipeline)")
    p_run.add_argument("--no-judge", action="store_true", help="skip the judge for this run")
    p_run.add_argument("--no-reuse", action="store_true", help="call the models even when evidence repeats")
    p_run.add_argument("--redecompose", action="store_true", help="decompose again even if a decomposition exists")

    p_prov = sub.add_parser("providers", help="list LLM providers, or change one with 'providers set'")
    prov_sub = p_prov.add_subparsers(dest="action")
    p_set = prov_sub.add_parser("set", help="change a provider's URL or enable/disable it")
    p_set.add_argument("key", help="provider key, e.g. ollama-local")
    p_set.add_argument("--base-url", help="e.g. http://localhost:11434 (native Ollama) or http://localhost:11435 (Docker)")
    toggle = p_set.add_mutually_exclusive_group()
    toggle.add_argument("--enable", dest="enabled", action="store_true", default=None)
    toggle.add_argument("--disable", dest="enabled", action="store_false")

    args = parser.parse_args(argv)
    if args.command == "providers":
        if args.action == "set":
            return providers(args.key, args.base_url, args.enabled)
        return providers(None, None, None)
    if args.command == "check":
        return check()
    if args.command == "ingest":
        return ingest(args.pdf, args.pipeline, args.redecompose)
    if args.command == "run":
        split = lambda v: [x.strip() for x in v.split(",") if x.strip()] if v else None  # noqa: E731
        options = RunOptions(fields=split(args.fields), retrievals=split(args.retrievals),
                             judge=False if args.no_judge else None, reuse_calls=not args.no_reuse,
                             redecompose=args.redecompose)
        return run(args.pdf, args.pipeline, args.kind, options)
    return 2


if __name__ == "__main__":
    sys.exit(main())
