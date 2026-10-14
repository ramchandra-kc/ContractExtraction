"""Command line entry point.

    contract-extraction check                 settings, database, schema, default pipeline, Qdrant and LLM providers
    contract-extraction ingest <pdf>          register, decompose and index a PDF with a pipeline config
    contract-extraction run <pdf> [options]   ingest + extract every field under every RAG config (inline)
    contract-extraction run <pdf> --queue     only queue it; `contract-extraction worker` executes queued runs
    contract-extraction status [RUN_ID]       recent runs, or one run's timeline and best values
    contract-extraction cancel RUN_ID         cancel a queued run / stop a running one before its next field
    contract-extraction api                   serve the HTTP API (127.0.0.1:8000, behind the gateway)
    contract-extraction openapi [-o PATH]     write the API's OpenAPI document (no database needed)
    contract-extraction providers [set KEY --base-url URL | --enable | --disable]
                                              list LLM providers / switch e.g. native ↔ Docker Ollama
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from .core.errors import AppError
from .core.logging import setup_logging
from .core.settings import load_settings
from .domain.enums import RunKind, RunState
from .persistence import models as m
from .persistence.db import Database
from .persistence.repositories import ConfigRepo, RunRepo
from .persistence.repositories.results import ResultRepo
from .pipeline.options import RunOptions
from .providers.base import ProviderError
from .storage import FileStorage


def check() -> int:
    from .health import readiness

    settings = load_settings()
    setup_logging(settings.log_level)
    db = Database(settings.database)
    print(f"environment : {settings.app_env}")
    print(f"database    : {db.safe_url()}")
    print(f"storage     : {settings.storage_root}")
    try:
        components, p = readiness(db, settings)
    finally:
        db.dispose()
    if p is not None:
        judge = f"{p.judge_profile.name} ({p.judge_profile.model.name})" if p.judge_enabled and p.judge_profile else "off"
        print(f"pipeline    : {p.name}")
        print(f"  decompose : {p.decomposition.name} ({p.decomposition.method}, {p.decomposition.text_format})")
        print(f"  extraction: {p.extraction_profile.name} ({p.extraction_profile.model.name} via {p.extraction_profile.model.provider.key})")
        print(f"  judge     : {judge}")
        print(f"  embedding : {p.index.embedding_model.name} (chunks {p.index.chunk_size}/{p.index.chunk_overlap}, {p.index.vector_store})")
        print(f"  fields    : {len(p.field_set.fields)} from {p.field_set.name} v{p.field_set.version}")
        print(f"  retrieval : {', '.join(r.name for r in p.retrievals)}")
    print("services    :")
    for c in components:
        print(f"  {'ok  ' if c.ok else 'FAIL'} {c.name}: {c.detail}")
    ok = all(c.ok for c in components)
    print("OK" if ok else "FAIL")
    return 0 if ok else 1


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


def run(pdf: Path, pipeline_name: str | None, kind: str, options: RunOptions, queue: bool = False) -> int:
    from .ingestion import register_file
    from .pipeline.executor import RunExecutor
    from .pipeline.options import narrow
    from .worker import default_worker_id

    settings = load_settings()
    setup_logging(settings.log_level)
    db = Database(settings.database)
    storage = FileStorage(settings.storage_root)
    run_id = None
    try:
        with db.session() as s:
            pipeline = narrow(ConfigRepo(s).resolve_pipeline(pipeline_name), options)
        document_id, code, _ = register_file(db, storage, settings, pdf)
        worker_id = f"cli:{default_worker_id()}"
        with db.session() as s:
            # Inline runs start in the same transaction, so a worker can never claim them.
            run_id = RunRepo(s).enqueue(document_id, pipeline, RunKind(kind), options.model_dump(exclude_defaults=True),
                                        start_as=None if queue else worker_id).id
        calls = len(pipeline.field_set.fields) * len(pipeline.retrievals) * (2 if pipeline.judge_enabled else 1)
        print(f"run {run_id}: {code}, {len(pipeline.field_set.fields)} fields x {len(pipeline.retrievals)} RAG configs "
              f"(up to {calls} LLM calls)", flush=True)
        if queue:
            print("queued; a worker will run it. Follow it with: contract-extraction status " + str(run_id))
            return 0
        state = RunExecutor(db, storage, settings, worker_id=worker_id).run_claimed(run_id)
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


def _age(start: datetime | None, end: datetime | None = None) -> str:
    if start is None:
        return "-"
    seconds = int(((end or datetime.now(timezone.utc)) - start).total_seconds())
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m" if seconds >= 3600 else f"{seconds // 60}m{seconds % 60:02d}s"


def status(run_id: str | None, limit: int) -> int:
    """Recent runs, or one run with its timeline and best values."""
    settings = load_settings()
    db = Database(settings.database)
    try:
        with db.session() as s:
            repo = RunRepo(s)
            if run_id is None:
                print(f"{'run':36} {'doc':7} {'state':9} {'stage':11} {'progress':8} {'took':8} error")
                for r in repo.recent(limit):
                    took = _age(r.started_at, r.finished_at) if r.started_at else "-"
                    print(f"{str(r.id):36} {r.document.code:7} {r.state:9} {r.stage or '-':11} "
                          f"{f'{r.progress_done}/{r.progress_total}':8} {took:8} {_short(r.error, 60)}")
                return 0
            r = repo.get(uuid.UUID(run_id))
            print(f"run      : {r.id} ({r.document.code}, {r.kind}, pipeline {r.config_snapshot.get('name')})")
            print(f"state    : {r.state}  stage: {r.stage or '-'}  progress: {r.progress_done}/{r.progress_total}")
            print(f"worker   : {r.worker_id or '-'}  started: {r.started_at or '-'}  finished: {r.finished_at or '-'}")
            if r.state == RunState.RUNNING and r.heartbeat_at:
                print(f"heartbeat: {_age(r.heartbeat_at)} ago")
            if r.error:
                print(f"error    : {r.error}")
            print("\nevents:")
            for e in repo.events(r.id):
                if e.level != "debug":
                    print(f"  {e.created_at:%H:%M:%S} {e.level:7} {e.message}")
            best = ResultRepo(s).best_values(r.id)
            if best:
                print(f"\n{'field':30} {'value':70} {'config':7} verdict")
                for b in best:
                    print(f"{b['field_label'][:30]:30} {_short(b['value']):70} {b['retrieval_config']:7} {b['verdict'] or '-'}")
            return 0
    except (AppError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        db.dispose()


def cancel(run_id: str) -> int:
    settings = load_settings()
    db = Database(settings.database)
    try:
        with db.session() as s:
            r = RunRepo(s).cancel(uuid.UUID(run_id))
            print("cancelled" if r.state == RunState.CANCELLED else "cancellation requested; it stops before its next field")
            return 0
    except (AppError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        db.dispose()


def worker(once: bool) -> int:
    from .worker import Worker

    settings = load_settings()
    setup_logging(settings.log_level)
    db = Database(settings.database)
    w = Worker(db, FileStorage(settings.storage_root), settings)
    try:
        if once:
            w.run_once()
        else:
            w.install_signal_handlers()
            w.run_forever()
    except KeyboardInterrupt:
        print("worker stopped immediately", file=sys.stderr)
        return 130
    finally:
        db.dispose()
    return 0


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


def openapi_json() -> str:
    """The API's OpenAPI document as stable, pretty JSON (the frontend's generated types are built from it)."""
    from .api.app import create_app

    return json.dumps(create_app().openapi(), indent=2, ensure_ascii=False) + "\n"


def openapi(out: Path | None) -> int:
    text = openapi_json()
    if out is None:
        sys.stdout.write(text)
    else:
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out}")
    return 0


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
    p_run.add_argument("--queue", action="store_true", help="only queue the run; a worker executes it")

    p_worker = sub.add_parser("worker", help="execute queued runs (Ctrl-C once: stop after cancelling the current run)")
    p_worker.add_argument("--once", action="store_true", help="process at most one run, then exit")

    p_status = sub.add_parser("status", help="recent runs, or one run's timeline and results")
    p_status.add_argument("run_id", nargs="?")
    p_status.add_argument("--limit", type=int, default=20)

    p_cancel = sub.add_parser("cancel", help="cancel a queued run, or stop a running one before its next field")
    p_cancel.add_argument("run_id")

    sub.add_parser("api", help="serve the HTTP API on API__HOST:API__PORT (default 127.0.0.1:8000)")
    p_openapi = sub.add_parser("openapi", help="write the API's OpenAPI document (stdout by default)")
    p_openapi.add_argument("-o", "--output", type=Path, help="file to write, e.g. ../frontend/openapi.json")

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
        return run(args.pdf, args.pipeline, args.kind, options, queue=args.queue)
    if args.command == "worker":
        return worker(args.once)
    if args.command == "status":
        return status(args.run_id, args.limit)
    if args.command == "cancel":
        return cancel(args.run_id)
    if args.command == "api":
        from .api.app import serve

        serve()
        return 0
    if args.command == "openapi":
        return openapi(args.output)
    return 2


if __name__ == "__main__":
    sys.exit(main())
