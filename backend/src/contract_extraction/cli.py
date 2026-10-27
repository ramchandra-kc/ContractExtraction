"""Command line entry point.

    contract-extraction check                 settings, database, schema, default pipeline, Qdrant and LLM providers
    contract-extraction ingest <file>         register, decompose and index a contract file with a pipeline config
    contract-extraction run <file> [options]  ingest + extract every field under every RAG config (inline)
    contract-extraction run <file> --queue    only queue it; `contract-extraction worker` executes queued runs
    contract-extraction status [RUN_ID]       recent runs, or one run's timeline and best values
    contract-extraction cancel RUN_ID         cancel a queued run / stop a running one
    contract-extraction api                   serve the HTTP API (127.0.0.1:8000, behind the gateway)
    contract-extraction openapi [-o PATH]     write the API's OpenAPI document (no database needed)
    contract-extraction gen-catalogue [--with-queries]
                                              regenerate docker/seed_catalogue.sql from docs/contract_types_and_fields.md
    contract-extraction providers [set KEY --base-url URL | --enable | --disable]
                                              list LLM providers / switch e.g. native ↔ Docker Ollama
    contract-extraction labels import DIR [--dry-run] [--overwrite] [--tag TAG]
                                              import draft ground truth from label files (one JSON per contract)
    contract-extraction documents tag TAG CODE_OR_FILE... [--remove] | list [--tag TAG]
                                              tag documents for experiments / list them with their labels
    contract-extraction experiment create NAME --pipelines A,B --tag TAG [--repeats N] | list | run NAME |
                                   show NAME | export NAME [-o DIR]
                                              documents × pipelines × repeats under fixed conditions (experiments.py)
    contract-extraction experiment retrieval-eval NAME --tag TAG [--retrievals A,B] [--top-k 3,5,10] [--threshold 0,0.5] [--per-query-top 3,10]
                                              evidence recall of RAG configs, no LLM calls (retrieval_eval.py)
    contract-extraction experiment compare NAME --baseline ARM [--by pipeline] [--metric score] [--file results.csv]
                                              paired arm comparison with cluster bootstrap CIs (compare.py)
    contract-extraction experiment semantic NAME [--dry-run] [--sample 100] | --check FILE
                                              LLM-graded semantic score added to the export's CSVs (semantic.py)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from .core.errors import AppError
from .core.logging import setup_logging
from .core.settings import BACKEND_ROOT, load_settings
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


def ingest(file: Path, pipeline_name: str | None, redecompose: bool) -> int:
    from .ingestion import ingest as run_ingest

    settings = load_settings()
    setup_logging(settings.log_level)
    db = Database(settings.database)
    try:
        with db.session() as s:
            pipeline = ConfigRepo(s).resolve_pipeline(pipeline_name)
        r = run_ingest(db, FileStorage(settings.storage_root), settings, pipeline, source_path=file, redecompose=redecompose)
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


def run(file: Path, pipeline_name: str | None, kind: str, options: RunOptions, queue: bool = False) -> int:
    from .ingestion import register_file
    from .pipeline.executor import RunExecutor, select_fields
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
        document_id, code, _ = register_file(db, storage, settings, file)
        worker_id = f"cli:{default_worker_id()}"
        with db.session() as s:
            # Inline runs start in the same transaction, so a worker can never claim them.
            run_id = RunRepo(s).enqueue(document_id, pipeline, RunKind(kind), options.model_dump(exclude_defaults=True),
                                        start_as=None if queue else worker_id).id
        if options.fields is not None or options.contract_types:
            n_fields = len(select_fields(pipeline, options, tuple(options.contract_types or ())))
            calls = n_fields * len(pipeline.retrievals) * (2 if pipeline.judge_enabled else 1)
            print(f"run {run_id}: {code}, {n_fields} fields x {len(pipeline.retrievals)} RAG configs "
                  f"(up to {calls} LLM calls)", flush=True)
        else:
            detect = "detecting the contract type" if pipeline.classification_enabled else "fallback contract type"
            print(f"run {run_id}: {code}, {detect}, then its fields x {len(pipeline.retrievals)} RAG configs", flush=True)
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
            print("cancelled" if r.state == RunState.CANCELLED else "cancellation requested; it stops within seconds")
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


def labels_import(directory: Path, root: Path, overwrite: bool, dry_run: bool, tags: list[str]) -> int:
    from .labels import import_file, label_files

    settings = load_settings()
    setup_logging(settings.log_level)
    db = Database(settings.database)
    storage = FileStorage(settings.storage_root)
    files = label_files(directory)
    if not files:
        print(f"no label files under {directory}", file=sys.stderr)
        return 1
    totals = {"imported": 0, "kept": 0, "rejected": 0, "failed": 0, "registered": 0}
    try:
        for path in files:
            r = import_file(db, storage, settings, path, root, overwrite=overwrite, dry_run=dry_run, tags=tags)
            name = path.relative_to(directory)
            if r.error:
                totals["failed"] += 1
                print(f"FAIL {name}: {r.error}")
                continue
            totals["imported"] += r.imported
            totals["kept"] += r.kept
            totals["rejected"] += len(r.rejected)
            totals["registered"] += r.registered
            code = r.code or "(new)"
            print(f"{code:7} {str(name):70} {r.imported:3} set  {r.kept:3} kept  {len(r.rejected):3} rejected"
                  f"  types: {','.join(r.contract_types) or '-'}")
            for key, reason in r.rejected:
                print(f"          ✗ {key}: {reason}")
    finally:
        db.dispose()
    verb = "would set" if dry_run else "set"
    print(f"\n{len(files)} files: {verb} {totals['imported']} labels, kept {totals['kept']} edited by hand, "
          f"rejected {totals['rejected']}, {totals['registered']} documents {'to register' if dry_run else 'registered'}, "
          f"{totals['failed']} files failed")
    return 1 if totals["failed"] else 0


def documents_tag(tag: str, refs: list[str], remove: bool) -> int:
    """Tag documents given by code (DOC001) or by file (registered first when new)."""
    from .ingestion import register_file
    from .persistence.repositories import DocumentRepo

    settings = load_settings()
    db = Database(settings.database)
    storage = FileStorage(settings.storage_root)
    try:
        ids, registered = [], 0
        for ref in refs:
            path = Path(ref)
            if path.is_file():
                if remove:
                    with db.session() as s:
                        doc = DocumentRepo(s).get_by_sha256(hashlib.sha256(path.read_bytes()).hexdigest())
                    if doc is not None:
                        ids.append(doc.id)
                    continue
                document_id, _, created = register_file(db, storage, settings, path)
                ids.append(document_id)
                registered += created
            else:
                with db.session() as s:
                    ids.append(DocumentRepo(s).get_by_code(ref).id)
        with db.session() as s:
            repo = DocumentRepo(s)
            for document_id in dict.fromkeys(ids):
                (repo.remove_tags if remove else repo.add_tags)(document_id, [tag])
        verb = "untagged" if remove else "tagged"
        print(f"{verb} {len(set(ids))} documents with {tag}" + (f" ({registered} newly registered)" if registered else ""))
        return 0
    except AppError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        db.dispose()


def documents_list(tag: str | None, limit: int) -> int:
    """Documents (newest first, or those with a tag) with their label counts and labelled contract types."""
    from .persistence.repositories import DocumentRepo

    settings = load_settings()
    db = Database(settings.database)
    try:
        with db.session() as s:
            repo = DocumentRepo(s)
            docs = list(repo.with_tag(tag)) if tag else list(repo.list(limit)[0])
            ids = [d.id for d in docs]
            labels = dict(s.execute(select(m.GroundTruth.document_id, func.count()).where(
                m.GroundTruth.document_id.in_(ids)).group_by(m.GroundTruth.document_id)).all())
            types: dict[uuid.UUID, list[str]] = {}
            for doc_id, key in s.execute(
                    select(m.DocumentContractType.document_id, m.ContractType.key)
                    .join(m.ContractType, m.ContractType.id == m.DocumentContractType.contract_type_id)
                    .where(m.DocumentContractType.document_id.in_(ids)).order_by(m.ContractType.position)):
                types.setdefault(doc_id, []).append(key)
            print(f"{'code':7} {'format':6} {'labels':6} {'contract types':24} {'tags':20} file")
            for d in docs:
                print(f"{d.code:7} {d.format:6} {labels.get(d.id, 0):6} {','.join(types.get(d.id, [])) or '-':24} "
                      f"{','.join(d.tags) or '-':20} {d.original_filename}")
            print(f"\n{len(docs)} documents" + (f" tagged {tag}" if tag else ""))
        return 0
    finally:
        db.dispose()


def experiment_create(args: argparse.Namespace) -> int:
    from . import experiments
    from .domain.enums import Priority

    split = lambda v: [x.strip() for x in v.split(",") if x.strip()] if v else None  # noqa: E731
    modes = ("labelled", "types", "detect")
    fields_mode, keys = (args.fields, None) if args.fields in modes else ("list", split(args.fields))
    settings = load_settings()
    db = Database(settings.database)
    try:
        with db.session() as s:
            exp = experiments.create(
                s, args.name, pipelines=split(args.pipelines) or [], repeats=args.repeats, tag=args.tag,
                codes=split(args.documents) or [], fields=fields_mode, field_keys=keys,
                min_priority=Priority(args.min_priority) if args.min_priority else None,
                retrievals=split(args.retrievals), judge=False if args.no_judge else None,
                description=args.description, hypothesis=args.hypothesis)
            design = experiments.Design.model_validate(exp.design)
            n_docs, n_pipes = len(design.documents), len(design.pipelines)
            sizes = sorted(len(d.fields) for d in design.documents if d.fields)
            per_doc = "" if not sizes else str(sizes[0]) if sizes[0] == sizes[-1] else f"{sizes[0]}–{sizes[-1]}"
            print(f"experiment {exp.name}: {n_docs} documents × {n_pipes} pipelines × {design.repeats} repeats "
                  f"= {n_docs * n_pipes * design.repeats} runs"
                  + (f", {per_doc} fields per document" if per_doc else ", fields detected by each pipeline"))
            print(f"run it with: contract-extraction experiment run {exp.name}   (workers execute the runs)")
        return 0
    except AppError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        db.dispose()


def experiment_list() -> int:
    from .persistence.repositories.experiments import ExperimentRepo

    settings = load_settings()
    db = Database(settings.database)
    try:
        with db.session() as s:
            print(f"{'experiment':30} {'created':16} {'runs':28} pipelines")
            for exp, counts in ExperimentRepo(s).list():
                runs = " ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "-"
                print(f"{exp.name:30} {exp.created_at.astimezone():%Y-%m-%d %H:%M} {runs:28} "
                      f"{','.join(exp.design.get('pipelines', []))}")
        return 0
    finally:
        db.dispose()


def experiment_run(name: str, max_queued: int, retries: int, poll: float) -> int:
    from .experiments import ExperimentRunner

    settings = load_settings()
    setup_logging(settings.log_level)
    db = Database(settings.database)
    runner = None
    try:
        runner = ExperimentRunner(db, name, max_queued=max_queued, retries=retries)
        print(f"experiment {name}: queueing for the workers (start them with scripts/dev.sh up --workers N, or "
              "contract-extraction worker); Ctrl-C stops queueing", flush=True)
        progress = runner.run(poll=poll, report=lambda p: print(f"{datetime.now():%H:%M:%S} {p}", flush=True))
        print("finished" if not progress.given_up else "finished, except the given-up cells (run again to retry them)")
        return 0 if not progress.given_up else 1
    except KeyboardInterrupt:
        n = runner.cancel_queued() if runner else 0
        print(f"stopped: cancelled {n} queued runs; running ones finish. Run again to resume.", file=sys.stderr)
        return 130
    except AppError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        db.dispose()


def experiment_show(name: str) -> int:
    from .experiments import collect, summary

    settings = load_settings()
    db = Database(settings.database)
    try:
        with db.session() as s:
            c = collect(s, name)
            exp, d = c.experiment, c.design
            print(f"experiment : {exp.name}  (created {exp.created_at.astimezone():%Y-%m-%d %H:%M})")
            if exp.hypothesis:
                print(f"hypothesis : {exp.hypothesis}")
            print(f"design     : {len(d.documents)} documents{' tagged ' + d.tag if d.tag else ''} × "
                  f"{', '.join(d.pipelines)} × {d.repeats} repeats; fields: {d.fields}"
                  + (f" (≤ {d.min_priority})" if d.min_priority else "")
                  + (f"; RAG configs {','.join(d.retrievals)}" if d.retrievals else "") + ("; no judge" if d.judge is False else ""))
            states = Counter(r.state for r in c.runs)
            print(f"runs       : {' '.join(f'{k} {v}' for k, v in sorted(states.items())) or 'none yet'}")
            pct = lambda v: "-" if v is None else f"{v * 100:.1f}%"  # noqa: E731
            num = lambda v, f="{:.3f}": "-" if v is None else f.format(v)  # noqa: E731
            print(f"\n{'pipeline':22} {'runs':>5} {'value acc':>9} {'score':>6} {'±sd':>6} {'missed':>7} "
                  f"{'absent ok':>9} {'invented':>8} {'PASS ok':>7} {'$/run':>8} {'s/run':>7}")
            for r in summary(c):
                print(f"{r['pipeline']:22} {r['runs_succeeded']:5} {pct(r['value_exact']):>9} {num(r['value_score']):>6} "
                      f"{num(r['value_score_sd']):>6} {pct(r['value_missed']):>7} {pct(r['absent_correct']):>9} "
                      f"{pct(r['invented']):>8} {pct(r['judge_pass_correct']):>7} {num(r['cost_usd_per_run'], '{:.4f}'):>8} "
                      f"{num(r['seconds_per_run'], '{:.0f}'):>7}"
                      + ("  ⚠ pipeline changed during the experiment" if r["snapshots"] > 1 else "")
                      + ("  ⚠ runs from more than one code version" if r["code_versions"] > 1 else ""))
        return 0
    except AppError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        db.dispose()


def experiment_export(name: str, out: Path | None) -> int:
    from .experiments import collect, export

    settings = load_settings()
    db = Database(settings.database)
    try:
        with db.session() as s:
            files = export(collect(s, name, outcomes=True), out or BACKEND_ROOT.parent / "experiments" / name)
        for f in files:
            print(f"wrote {f}")
        return 0
    except AppError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        db.dispose()


def experiment_retrieval_eval(args: argparse.Namespace) -> int:
    from dataclasses import asdict

    from .experiments import write_csv
    from .persistence.repositories import DocumentRepo
    from .pipeline.executor import Providers
    from .retrieval_eval import evaluate, summary, variants

    split = lambda v: [x.strip() for x in v.split(",") if x.strip()] if v else []  # noqa: E731
    settings = load_settings()
    setup_logging(settings.log_level)
    db = Database(settings.database)
    try:
        with db.session() as s:
            repo = DocumentRepo(s)
            docs = {d.id: d for d in (repo.with_tag(args.tag) if args.tag else [])}
            docs |= {d.id: d for d in (repo.get_by_code(c) for c in split(args.documents))}
            pipeline = ConfigRepo(s).resolve_pipeline(args.pipeline)
            names = split(args.retrievals) or [rc.name for rc in pipeline.retrievals]
            configs = variants(ConfigRepo(s).resolve_retrievals(names),
                               [int(k) for k in split(args.top_k)] or None,
                               [float(t) for t in split(args.threshold)] if args.threshold else None,
                               [int(q) for q in split(args.per_query_top)] or None)
            s.expunge_all()
        if not docs:
            print("FAIL: no documents (give --tag and/or --documents)", file=sys.stderr)
            return 1
        print(f"{len(docs)} documents × {len(configs)} RAG config variants, pipeline {pipeline.name}")
        rows = evaluate(db, FileStorage(settings.storage_root), settings, Providers.from_settings(settings),
                        pipeline.name, sorted(docs.values(), key=lambda d: d.code), configs)
        out = args.output or BACKEND_ROOT.parent / "experiments" / args.name
        out.mkdir(parents=True, exist_ok=True)
        overall = summary(rows)
        for f in (write_csv(out / "retrieval_hits.csv", [asdict(r) for r in rows]),
                  write_csv(out / "retrieval_summary.csv", overall),
                  write_csv(out / "retrieval_by_type.csv", summary(rows, ("retrieval_config", "value_type")))):
            print(f"wrote {f}")
        pct = lambda v: "-" if v is None else f"{v * 100:.1f}%"  # noqa: E731
        print(f"\n{'RAG config':24} {'labels':>6} {'recall':>7} {'all':>7} {'@1':>6} {'@3':>6} {'@5':>6} {'MRR':>6} "
              f"{'not idx':>7} {'hits':>5}")
        for r in overall:
            print(f"{r['retrieval_config']:24} {r['labels']:6} {pct(r['recall']):>7} {pct(r['recall_all']):>7} "
                  f"{pct(r['recall_at_1']):>6} {pct(r['recall_at_3']):>6} {pct(r['recall_at_5']):>6} "
                  f"{r['mrr'] or 0:6.3f} {pct(r['not_indexed']):>7} {r['mean_hits'] or 0:5.1f}")
        return 0
    except (AppError, ProviderError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        db.dispose()


def experiment_semantic(args: argparse.Namespace) -> int:
    from .compare import read_rows
    from .experiments import write_csv
    from .persistence.repositories.ground_truth import GroundTruthRepo
    from .providers.factory import chat_client
    from .semantic import Cache, FieldInfo, add_scores, agreement, grade, requests_for, sample

    folder = args.name if args.name.exists() else BACKEND_ROOT.parent / "experiments" / str(args.name)
    if args.check:
        a = agreement(read_rows(args.check))
        if not a["n"]:
            print(f"FAIL: no rows with human_grade (correct / partial / wrong) in {args.check}", file=sys.stderr)
            return 1
        print(f"{a['n']} hand-graded parts: agreement {a['agreement']:.1%}, Cohen's kappa {a['kappa']:.3f}, "
              f"correct-vs-not agreement {a['correct_agreement']:.1%}")
        print("grader->human: " + ", ".join(f"{k} {v}" for k, v in a["confusion"].items()))
        return 0
    files = [folder / f for f in ("results.csv", "outcomes.csv") if (folder / f).exists()]
    if not files:
        print(f"FAIL: no results.csv in {folder} (run experiment export first)", file=sys.stderr)
        return 1
    settings = load_settings()
    db = Database(settings.database)
    try:
        with db.session() as s:
            profile = ConfigRepo(s).resolve_profile(args.profile, "semantic grading")
            fields = {f.key: FieldInfo(f.label, f.description) for f in GroundTruthRepo(s).field_set().fields}
    except AppError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        db.dispose()
    cache = Cache(args.cache or BACKEND_ROOT.parent / "experiments" / ".semantic-cache.jsonl", profile.model.name)
    rows = [r for f in files for r in read_rows(f)]
    requests = requests_for(rows)
    todo = {r.key for r in requests if cache.grades(r.key) is None}
    print(f"{len(rows)} rows, {len({r.key for r in requests})} distinct cells need the grader, {len(todo)} not cached "
          f"(grader {profile.name}: {profile.model.name})")
    if args.dry_run:
        price = lambda tokens, per_m: tokens * float(per_m or 0) / 1e6  # noqa: E731
        print(f"estimate at ~900 prompt + ~400 completion tokens a cell: "
              f"${price(900 * len(todo), profile.model.input_cost_per_mtok) + price(400 * len(todo), profile.model.output_cost_per_mtok):.2f}")
        return 0
    if todo:
        client = chat_client(profile, settings)
        usage = grade(requests, fields, lambda system, user: client.complete(system, user, profile), cache,
                      args.workers, report=lambda i, n: print(f"\r{i}/{n} graded", end="", flush=True) if i % 25 == 0 or i == n else None)
        cost = (usage.prompt_tokens * float(profile.model.input_cost_per_mtok or 0)
                + usage.completion_tokens * float(profile.model.output_cost_per_mtok or 0)) / 1e6
        print(f"\n{usage.calls} calls, {usage.prompt_tokens} + {usage.completion_tokens} tokens, ≈ ${cost:.2f}; "
              f"{usage.failed} cells left ungraded (run again to retry)")
    for f in files:
        scored, missing = add_scores(f, cache)
        print(f"wrote {f}: semantic score on {scored} rows" + (f", {missing} still missing a grade" if missing else ""))
    if args.sample:
        out = write_csv(folder / "semantic_sample.csv", sample(read_rows(files[0]), cache, args.sample))
        print(f"wrote {out}: fill human_grade, then `experiment semantic {args.name} --check {out}`")
    return 0


def experiment_compare(args: argparse.Namespace) -> int:
    from .compare import compare_arms, read_rows

    folder = args.name if args.name.exists() else BACKEND_ROOT.parent / "experiments" / str(args.name)
    files = [args.file] if args.file else ["outcomes.csv", "results.csv", "retrieval_hits.csv"]
    path = next((folder / f for f in files if (folder / f).exists()), None)
    if path is None:
        print(f"FAIL: none of {', '.join(files)} in {folder} (run experiment export / retrieval-eval first)", file=sys.stderr)
        return 1
    where = dict(w.split("=", 1) for w in args.where or [])
    try:
        rows = read_rows(path)
        metric = args.metric or ("evidence" if path.name == "retrieval_hits.csv" else "score")
        by = [c.strip() for c in args.by.split(",")]
        out = compare_arms(rows, by, args.baseline, metric, args.labels, where, args.resamples)
    except KeyError as exc:
        print(f"FAIL: {exc.args[0]}", file=sys.stderr)
        return 1
    print(f"{path.name}: {metric} on {args.labels} labels{' where ' + str(where) if where else ''}, "
          f"baseline {args.baseline}, paired by document × field ({args.resamples} resamples)\n")
    print(f"{'arm':28} {'cells':>5} {'docs':>4} {'base':>6} {'arm':>6} {'diff':>7} {'95% CI':>17} {'p':>7} "
          f"{'p_holm':>7} {'b/c':>9} {'mcnemar':>7}")
    for c in sorted(out, key=lambda c: -c.diff):
        bc = f"{c.b}/{c.c}" if c.b is not None else "-"
        mp = f"{c.mcnemar_p:.4f}" if c.mcnemar_p is not None else "-"
        print(f"{c.arm[:28]:28} {c.cells:5} {c.documents:4} {c.baseline_mean:6.3f} {c.arm_mean:6.3f} {c.diff:+7.3f} "
              f"[{c.ci_low:+.3f}, {c.ci_high:+.3f}] {c.p:7.4f} {c.p_holm:7.4f} {bc:>9} {mp:>7}")
    return 0


def gen_catalogue(doc: Path, out: Path, queries_path: Path, with_queries: bool, per_field: int) -> int:
    """Parse the catalogue document and write the seed SQL; optionally generate missing search queries."""
    from . import catalogue

    try:
        cat = catalogue.load(doc)
        queries = catalogue.load_queries(queries_path)
    except (OSError, ValueError, AppError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    stale = sorted(set(queries) - set(cat.fields))
    if stale:
        print(f"warning: {queries_path.name} has queries for unknown fields (ignored): {', '.join(stale)}", file=sys.stderr)

    if with_queries:
        from .providers import factory

        settings = load_settings()
        setup_logging(settings.log_level)
        db = Database(settings.database)
        try:
            with db.session() as s:
                profile = ConfigRepo(s).resolve_pipeline().extraction_profile
        except AppError as exc:
            print(f"FAIL: cannot resolve the default pipeline's extraction model: {exc}", file=sys.stderr)
            return 1
        finally:
            db.dispose()
        chat = factory.chat_client(profile, settings)
        missing = [f for key, f in cat.fields.items() if not queries.get(key)]
        print(f"generating queries for {len(missing)} fields with {profile.model.name}", flush=True)
        for i, f in enumerate(missing, start=1):
            try:
                result = chat.complete(catalogue.QUERY_SYSTEM, catalogue.query_prompt(f, per_field), profile)
            except ProviderError as exc:
                print(f"FAIL at {f.key}: {exc} (queries so far are saved)", file=sys.stderr)
                catalogue.save_queries(queries_path, queries)
                return 1
            got = catalogue.parse_queries(result.text, per_field)
            if got:
                queries[f.key] = got
            print(f"  [{i}/{len(missing)}] {f.key}: {len(got)} queries", flush=True)
            catalogue.save_queries(queries_path, queries)  # after each field, so an interruption loses nothing

    out.write_text(catalogue.to_sql(cat, queries), encoding="utf-8")
    with_generated = sum(1 for k in cat.fields if queries.get(k))
    print(f"wrote {out}: {len(cat.types)} contract types ({cat.fallback.label} is the fallback), {len(cat.fields)} fields "
          f"({with_generated} with generated queries, {len(cat.fields) - with_generated} with label + description)")
    return 0


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
    p_ingest = sub.add_parser("ingest", help="register, decompose and index a contract file")
    p_ingest.add_argument("file", type=Path)
    p_ingest.add_argument("--pipeline", help="pipeline config name (default: the default pipeline)")
    p_ingest.add_argument("--redecompose", action="store_true", help="decompose again even if a decomposition exists")

    p_run = sub.add_parser("run", help="ingest a contract file and extract its fields (runs inline)")
    p_run.add_argument("file", type=Path)
    p_run.add_argument("--pipeline", help="pipeline config name (default: the default pipeline)")
    p_run.add_argument("--kind", choices=[k.value for k in RunKind], default=RunKind.FULL.value)
    p_run.add_argument("--fields", help="comma-separated field keys (default: those of the detected contract types)")
    p_run.add_argument("--contract-types", help="comma-separated contract type keys, e.g. msa,sow (default: detect them)")
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

    p_cancel = sub.add_parser("cancel", help="cancel a queued run, or stop a running one")
    p_cancel.add_argument("run_id")

    sub.add_parser("api", help="serve the HTTP API on API__HOST:API__PORT (default 127.0.0.1:8000)")
    p_openapi = sub.add_parser("openapi", help="write the API's OpenAPI document (stdout by default)")
    p_openapi.add_argument("-o", "--output", type=Path, help="file to write, e.g. ../frontend/openapi.json")

    repo_root = BACKEND_ROOT.parent
    p_cat = sub.add_parser("gen-catalogue", help="regenerate docker/seed_catalogue.sql from the contract types document")
    p_cat.add_argument("--doc", type=Path, default=repo_root / "docs" / "contract_types_and_fields.md")
    p_cat.add_argument("-o", "--output", type=Path, default=repo_root / "docker" / "seed_catalogue.sql")
    p_cat.add_argument("--queries", type=Path, default=repo_root / "docs" / "contract_field_queries.json",
                       help="search queries per field (JSON); fields without any use their label and description")
    p_cat.add_argument("--with-queries", action="store_true",
                       help="generate missing queries with the default pipeline's extraction model (needs the database and LLM)")
    p_cat.add_argument("--per-field", type=int, default=8, help="queries to generate per field")

    p_prov = sub.add_parser("providers", help="list LLM providers, or change one with 'providers set'")
    prov_sub = p_prov.add_subparsers(dest="action")
    p_set = prov_sub.add_parser("set", help="change a provider's URL or enable/disable it")
    p_set.add_argument("key", help="provider key, e.g. ollama-local")
    p_set.add_argument("--base-url", help="e.g. http://localhost:11434 (native Ollama) or http://localhost:11435 (Docker)")
    toggle = p_set.add_mutually_exclusive_group()
    toggle.add_argument("--enable", dest="enabled", action="store_true", default=None)
    toggle.add_argument("--disable", dest="enabled", action="store_false")

    p_labels = sub.add_parser("labels", help="import draft ground truth with 'labels import'")
    labels_sub = p_labels.add_subparsers(dest="action", required=True)
    p_limport = labels_sub.add_parser("import", help="import label files (one JSON per contract) as draft ground truth")
    p_limport.add_argument("directory", type=Path, help="e.g. ../test_data/labels")
    p_limport.add_argument("--root", type=Path, default=repo_root,
                           help="folder the label files' paths are relative to (default: the repository root)")
    p_limport.add_argument("--overwrite", action="store_true",
                           help="also replace labels edited by hand and contract types already labelled")
    p_limport.add_argument("--dry-run", action="store_true", help="validate and report; change nothing")
    p_limport.add_argument("--tag", action="append", default=[], help="tag every imported document (repeatable)")

    p_docs = sub.add_parser("documents", help="list documents, or tag them for experiments")
    docs_sub = p_docs.add_subparsers(dest="action", required=True)
    p_dtag = docs_sub.add_parser("tag", help="tag documents given by code (DOC001) or file (registered when new)")
    p_dtag.add_argument("tag")
    p_dtag.add_argument("refs", nargs="+", metavar="CODE_OR_FILE")
    p_dtag.add_argument("--remove", action="store_true", help="remove the tag instead")
    p_dlist = docs_sub.add_parser("list", help="documents with their labels and labelled contract types")
    p_dlist.add_argument("--tag", help="only documents with this tag")
    p_dlist.add_argument("--limit", type=int, default=50, help="newest N documents when no tag is given")

    p_exp = sub.add_parser("experiment", help="create, run, show and export experiments")
    exp_sub = p_exp.add_subparsers(dest="action", required=True)
    p_ecreate = exp_sub.add_parser("create", help="fix an experiment's design: documents × pipelines × repeats")
    p_ecreate.add_argument("name")
    p_ecreate.add_argument("--pipelines", required=True, help="comma-separated pipeline config names")
    p_ecreate.add_argument("--tag", help="the documents with this tag")
    p_ecreate.add_argument("--documents", help="comma-separated document codes (also, or instead of --tag)")
    p_ecreate.add_argument("--repeats", type=int, default=1)
    p_ecreate.add_argument("--fields", default="labelled",
                           help="labelled (default: each document's labelled fields), types (its labelled contract "
                                "types' fields), detect (each pipeline detects the type), or comma-separated keys")
    p_ecreate.add_argument("--min-priority", choices=["P1", "P2", "P3"], help="with --fields types: down to this priority")
    p_ecreate.add_argument("--retrievals", help="comma-separated RAG config names (default: each pipeline's)")
    p_ecreate.add_argument("--no-judge", action="store_true", help="skip the judge in every run")
    p_ecreate.add_argument("--hypothesis")
    p_ecreate.add_argument("--description")
    exp_sub.add_parser("list", help="experiments with their run counts")
    p_erun = exp_sub.add_parser("run", help="queue the experiment's runs and wait for them (resumes where it stopped)")
    p_erun.add_argument("name")
    p_erun.add_argument("--max-queued", type=int, default=8, help="experiment runs kept in the queue at a time")
    p_erun.add_argument("--retries", type=int, default=1, help="retries of a failed run, per document and pipeline")
    p_erun.add_argument("--poll", type=float, default=5.0, help="seconds between checks")
    p_eshow = exp_sub.add_parser("show", help="design, run counts and a summary per pipeline")
    p_eshow.add_argument("name")
    p_eexport = exp_sub.add_parser("export", help="write results, runs, fields and summary CSVs")
    p_eexport.add_argument("name")
    p_eexport.add_argument("-o", "--output", type=Path, help="folder (default: experiments/NAME in the repository)")
    p_eret = exp_sub.add_parser("retrieval-eval",
                                help="evidence recall of RAG configs against labelled evidence quotes, no LLM calls")
    p_eret.add_argument("name", help="output folder name under experiments/")
    p_eret.add_argument("--tag", help="the documents with this tag")
    p_eret.add_argument("--documents", help="comma-separated document codes (also, or instead of --tag)")
    p_eret.add_argument("--pipeline", help="decomposition, index and fields from this pipeline (default: the default)")
    p_eret.add_argument("--retrievals", help="comma-separated RAG config names (default: the pipeline's)")
    p_eret.add_argument("--top-k", help="comma-separated top_k values: one variant of each RAG config per value")
    p_eret.add_argument("--threshold", help="comma-separated score thresholds (score_threshold = min_score) to sweep")
    p_eret.add_argument("--per-query-top", help="comma-separated hits per query before merging, to sweep (caps top_k)")
    p_eret.add_argument("-o", "--output", type=Path, help="folder (default: experiments/NAME in the repository)")
    p_ecmp = exp_sub.add_parser("compare", help="paired comparison of arms with cluster bootstrap CIs and p-values")
    p_ecmp.add_argument("name", type=Path, help="export folder, or its name under experiments/")
    p_ecmp.add_argument("--by", default="pipeline", help="arm column(s), comma-separated: pipeline, retrieval_config")
    p_ecmp.add_argument("--baseline", required=True, help="the arm the others are compared to")
    p_ecmp.add_argument("--file", help="CSV in the folder (default: outcomes.csv, results.csv or retrieval_hits.csv)")
    p_ecmp.add_argument("--metric", choices=["exact", "score", "lenient", "semantic", "evidence", "invented"],
                        help="default: score, or evidence for retrieval_hits.csv")
    p_ecmp.add_argument("--labels", default="value", choices=["value", "absent", "all"],
                        help="labels with a value (default), labels of \"\" (use with --metric invented), or all")
    p_ecmp.add_argument("--where", action="append", metavar="COLUMN=VALUE",
                        help="only rows with this value, e.g. label_confidence=high (repeatable)")
    p_ecmp.add_argument("--resamples", type=int, default=10_000)
    p_esem = exp_sub.add_parser("semantic", help="add an LLM-graded semantic score to an export's CSVs (cached)")
    p_esem.add_argument("name", type=Path, help="export folder, or its name under experiments/")
    p_esem.add_argument("--profile", default="judge-or-gpt6-luna", help="chat model profile that grades")
    p_esem.add_argument("--workers", type=int, default=8, help="grading calls at a time")
    p_esem.add_argument("--dry-run", action="store_true", help="only count the cells to grade and estimate the cost")
    p_esem.add_argument("--sample", type=int, default=0, help="also write N graded parts to semantic_sample.csv")
    p_esem.add_argument("--check", type=Path, help="a filled-in semantic_sample.csv: grader vs hand agreement")
    p_esem.add_argument("--cache", type=Path, help="grade cache (default: experiments/.semantic-cache.jsonl)")

    args = parser.parse_args(argv)
    if args.command == "documents":
        if args.action == "tag":
            return documents_tag(args.tag, args.refs, args.remove)
        return documents_list(args.tag, args.limit)
    if args.command == "experiment":
        if args.action == "create":
            return experiment_create(args)
        if args.action == "list":
            return experiment_list()
        if args.action == "run":
            return experiment_run(args.name, args.max_queued, args.retries, args.poll)
        if args.action == "show":
            return experiment_show(args.name)
        if args.action == "retrieval-eval":
            return experiment_retrieval_eval(args)
        if args.action == "compare":
            return experiment_compare(args)
        if args.action == "semantic":
            return experiment_semantic(args)
        return experiment_export(args.name, args.output)
    if args.command == "labels":
        return labels_import(args.directory, args.root, args.overwrite, args.dry_run, args.tag)
    if args.command == "providers":
        if args.action == "set":
            return providers(args.key, args.base_url, args.enabled)
        return providers(None, None, None)
    if args.command == "check":
        return check()
    if args.command == "ingest":
        return ingest(args.file, args.pipeline, args.redecompose)
    if args.command == "run":
        split = lambda v: [x.strip() for x in v.split(",") if x.strip()] if v else None  # noqa: E731
        options = RunOptions(fields=split(args.fields), contract_types=split(args.contract_types),
                             retrievals=split(args.retrievals),
                             judge=False if args.no_judge else None, reuse_calls=not args.no_reuse,
                             redecompose=args.redecompose)
        return run(args.file, args.pipeline, args.kind, options, queue=args.queue)
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
    if args.command == "gen-catalogue":
        return gen_catalogue(args.doc, args.output, args.queries, args.with_queries, args.per_field)
    return 2


if __name__ == "__main__":
    sys.exit(main())
