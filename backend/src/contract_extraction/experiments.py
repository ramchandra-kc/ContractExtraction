"""Experiments: a documents × pipelines × repeats matrix of runs under fixed conditions, and its results.

* ``create`` fixes the design: pipelines, repeats, run options, and the documents with the fields each one
  extracts. Every pipeline extracts the same fields of a document, so their results compare field by field:

  - ``labelled`` (default): the document's labelled fields
  - ``types``: the fields of its labelled contract types, down to ``min_priority``
  - ``list``: the given field keys
  - ``detect``: each pipeline detects the contract type itself (the fields may then differ between pipelines)

* ``ExperimentRunner`` queues the matrix for the workers. A document has at most one active run, so the runner
  queues a document's next run when its previous one has finished, keeps at most ``max_queued`` experiment runs
  queued, and rotates the pipelines per document and repeat, so no pipeline runs all at once (at one time of
  day, under one provider's rate limits). The pipelines are resolved once per invocation. Starting it again
  resumes: a cell (document, pipeline) is done when it has ``repeats`` succeeded runs; failed runs are retried
  up to ``retries`` times per invocation, then the cell is given up and reported.

* ``collect`` turns the experiment's runs into rows (``export`` writes them as CSV). Labels of "" (not in
  this contract) are scored apart from labels with a value: otherwise a pipeline that finds nothing would score
  well on contracts where most fields are absent.
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from .core.errors import Conflict, InvalidInput
from .domain.config import PipelineConfig
from .domain.enums import Priority, RunKind, RunState
from .evaluation import match_score
from .persistence import models as m
from .persistence.db import Database
from .persistence.repositories import ConfigRepo, DocumentRepo, RunRepo
from .persistence.repositories.experiments import ExperimentRepo
from .persistence.repositories.ground_truth import GroundTruthRepo
from .persistence.repositories.results import ResultRepo
from .pipeline.options import RunOptions, narrow

FieldMode = Literal["labelled", "types", "list", "detect"]
_ACTIVE = (RunState.QUEUED, RunState.RUNNING)
_FAILED = (RunState.FAILED, RunState.CANCELLED)


class DesignDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    code: str
    # The field keys every pipeline extracts for this document (None: detected by each pipeline).
    fields: list[str] | None = None


class Design(BaseModel):
    """Stored in ``experiments.design``."""

    model_config = ConfigDict(extra="forbid")

    pipelines: list[str]
    repeats: int = 1
    fields: FieldMode = "labelled"
    min_priority: Priority | None = None
    retrievals: list[str] | None = None
    # False turns the judge off; None keeps each pipeline's setting.
    judge: bool | None = None
    tag: str | None = None
    documents: list[DesignDocument]

    def options(self, doc: DesignDocument) -> RunOptions:
        return RunOptions(fields=doc.fields, retrievals=self.retrievals, judge=self.judge)


def create(session, name: str, *, pipelines: list[str], repeats: int = 1, tag: str | None = None,
           codes: Iterable[str] = (), fields: FieldMode = "labelled", field_keys: list[str] | None = None,
           min_priority: Priority | None = None, retrievals: list[str] | None = None, judge: bool | None = None,
           description: str | None = None, hypothesis: str | None = None) -> m.Experiment:
    """Validate and store an experiment's design; ``InvalidInput`` names what is missing."""
    if repeats < 1:
        raise InvalidInput("repeats must be at least 1")
    pipelines = list(dict.fromkeys(pipelines))
    if not pipelines:
        raise InvalidInput("Choose at least one pipeline")
    if (fields == "list") != bool(field_keys):
        raise InvalidInput("Give field keys exactly when the field mode is 'list'")
    if min_priority is not None and fields != "types":
        raise InvalidInput("min_priority applies to the 'types' field mode only")
    resolved = {p: ConfigRepo(session).resolve_pipeline(p) for p in pipelines}
    if len({p.field_set.id for p in resolved.values()}) > 1:
        raise InvalidInput("The pipelines use different field sets, so their fields don't compare")
    field_set = next(iter(resolved.values())).field_set

    docs_repo = DocumentRepo(session)
    docs = {d.id: d for d in (docs_repo.with_tag(tag) if tag else [])}
    docs |= {d.id: d for d in (docs_repo.get_by_code(c) for c in codes)}
    if not docs:
        raise InvalidInput(f"No documents {'tagged ' + repr(tag) if tag else 'given'}")

    gt = GroundTruthRepo(session)
    labelled_fs = gt.field_set()
    if fields in ("labelled", "types") and labelled_fs.id != field_set.id:
        raise InvalidInput(f"The pipelines' field set is not the one the labels belong to ({labelled_fs.name})")
    entries, missing = [], []
    for doc in sorted(docs.values(), key=lambda d: d.code):
        keys: list[str] | None = None
        if fields == "labelled":
            keys = [f.key for f, label in gt.labels(doc.id, labelled_fs) if label is not None]
        elif fields == "types":
            types = [t.key for t in gt.contract_types(doc.id, labelled_fs)]
            keys = [f.key for f in field_set.fields_for_types(types, min_priority or Priority.P3)] if types else []
        elif fields == "list":
            keys = list(dict.fromkeys(field_keys or []))
        if keys == []:
            missing.append(doc.code)
        entries.append(DesignDocument(id=doc.id, code=doc.code, fields=keys))
    if missing:
        what = "labels" if fields == "labelled" else "labelled contract types"
        raise InvalidInput(f"{len(missing)} document(s) have no {what}: {', '.join(missing[:10])}"
                           + (" …" if len(missing) > 10 else ""))

    design = Design(pipelines=pipelines, repeats=repeats, fields=fields, min_priority=min_priority,
                    retrievals=retrievals, judge=judge, tag=tag, documents=entries)
    for p in resolved.values():  # unknown fields or RAG configs, or a judge the pipeline lacks
        for doc in entries:
            narrow(p, design.options(doc))
    return ExperimentRepo(session).create(name, design.model_dump(mode="json"), description, hypothesis)


# ---- running ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Progress:
    total: int
    succeeded: int
    running: int
    queued: int
    failed: int
    given_up: tuple[str, ...] = ()
    pending: int = 0

    @property
    def finished(self) -> bool:
        return self.running == 0 and self.queued == 0 and self.pending == 0

    def __str__(self) -> str:
        text = (f"{self.succeeded}/{self.total} succeeded · {self.running} running · {self.queued} queued · "
                f"{self.pending} waiting · {self.failed} failed")
        return text + (f" · gave up on {len(self.given_up)}: {', '.join(self.given_up)}" if self.given_up else "")


class ExperimentRunner:
    def __init__(self, db: Database, name: str, max_queued: int = 8, retries: int = 1):
        self.db, self.max_queued, self.retries = db, max(1, max_queued), retries
        with db.session() as s:
            exp = ExperimentRepo(s).get_by_name(name)
            self.experiment_id = exp.id
            self.design = Design.model_validate(exp.design)
            self.pipelines: dict[str, PipelineConfig] = {
                p: ConfigRepo(s).resolve_pipeline(p) for p in self.design.pipelines}
        self.mine: set[uuid.UUID] = set()  # runs queued by this invocation

    def cells(self) -> list[tuple[int, DesignDocument, str]]:
        """(repeat, document, pipeline) in queueing order: by repeat, then document, pipelines rotated."""
        names, n = self.design.pipelines, len(self.design.pipelines)
        return [(r, doc, names[(i + r + j) % n])
                for r in range(self.design.repeats)
                for i, doc in enumerate(self.design.documents)
                for j in range(n)]

    def step(self) -> Progress:
        """Queue what can be queued now, and report where the experiment stands."""
        with self.db.session() as s:
            runs = ExperimentRepo(s).runs(self.experiment_id)
            ids = {p.id: name for name, p in self.pipelines.items()}
            succeeded, active, failed_here = Counter(), Counter(), Counter()
            for run in runs:
                cell = (run.document_id, ids.get(run.pipeline_config_id, run.config_snapshot.get("name")))
                if run.state == RunState.SUCCEEDED:
                    succeeded[cell] += 1
                elif run.state in _ACTIVE:
                    active[cell] += 1
                elif run.id in self.mine:
                    failed_here[cell] += 1
            doc_ids = [d.id for d in self.design.documents]
            busy = set(s.scalars(select(m.Run.document_id).where(m.Run.document_id.in_(doc_ids),
                                                                 m.Run.state.in_(_ACTIVE))))
            queued = sum(r.state == RunState.QUEUED for r in runs)
            given_up = sorted({f"{d.code}/{p}" for _, d, p in self.cells() if failed_here[(d.id, p)] > self.retries
                               and succeeded[(d.id, p)] < self.design.repeats})
            pending = 0
            for r, doc, name in self.cells():
                cell = (doc.id, name)
                if r < succeeded[cell] + active[cell] or failed_here[cell] > self.retries:
                    continue
                if queued >= self.max_queued or doc.id in busy:
                    pending += 1
                    continue
                try:
                    run = RunRepo(s).enqueue(doc.id, narrow(self.pipelines[name], self.design.options(doc)), RunKind.FULL,
                                             self.design.options(doc).model_dump(exclude_defaults=True),
                                             experiment_id=self.experiment_id)
                except Conflict:  # a run started elsewhere (UI, CLI) in the meantime
                    pending += 1
                    busy.add(doc.id)
                    continue
                self.mine.add(run.id)
                active[cell] += 1
                busy.add(doc.id)
                queued += 1
            runs = ExperimentRepo(s).runs(self.experiment_id)
            return Progress(total=len(self.cells()),
                            succeeded=sum(min(n, self.design.repeats) for n in succeeded.values()),
                            running=sum(r.state == RunState.RUNNING for r in runs),
                            queued=sum(r.state == RunState.QUEUED for r in runs),
                            failed=sum(r.state in _FAILED for r in runs),
                            given_up=tuple(given_up), pending=pending)

    def run(self, poll: float = 5.0, report: Callable[[Progress], None] = print,
            sleep: Callable[[float], None] = time.sleep) -> Progress:
        """Step until the experiment is finished (or given up where it fails); reports each change."""
        last = None
        while True:
            progress = self.step()
            if progress != last:
                report(progress)
                last = progress
            if progress.finished:
                return progress
            sleep(poll)

    def cancel_queued(self) -> int:
        """Cancel the experiment's queued runs (running ones finish); returns how many."""
        with self.db.session() as s:
            queued = [r.id for r in ExperimentRepo(s).runs(self.experiment_id) if r.state == RunState.QUEUED]
            for run_id in queued:
                RunRepo(s).cancel(run_id)
        return len(queued)


# ---- results --------------------------------------------------------------------------------------------------


@dataclass
class ResultRow:
    run_id: uuid.UUID
    document: str
    pipeline: str
    repeat: int | None
    run_state: str
    field: str
    retrieval_config: str
    label: str  # value | absent | unlabelled
    status: str
    value: Any
    expected: Any
    exact_match: bool | None
    score: float | None
    verdict: str | None


@dataclass
class RunRow:
    run_id: uuid.UUID
    document: str
    pipeline: str
    repeat: int | None
    state: str
    seconds: float | None
    fields: int
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None
    mean_latency_ms: float | None
    contract_types: str
    snapshot: str  # short fingerprint of the config snapshot: differs when a pipeline was edited mid-experiment
    error: str | None


@dataclass
class Collected:
    experiment: m.Experiment
    design: Design
    results: list[ResultRow] = field(default_factory=list)
    runs: list[RunRow] = field(default_factory=list)


def collect(session, name: str) -> Collected:
    exp = ExperimentRepo(session).get_by_name(name)
    design = Design.model_validate(exp.design)
    out = Collected(exp, design)
    runs = list(ExperimentRepo(session).runs(exp.id))
    if not runs:
        return out
    codes = {d.id: d.code for d in design.documents}
    repeat: dict[uuid.UUID, int] = {}
    seen: Counter = Counter()
    for run in runs:  # oldest first
        if run.state == RunState.SUCCEEDED:
            key = (run.document_id, run.config_snapshot.get("name"))
            seen[key] += 1
            repeat[run.id] = seen[key]
    results = ResultRepo(session)
    best: dict[uuid.UUID, list] = defaultdict(list)
    for b in results.best_values_for_runs([r.id for r in runs]):
        best[b["run_id"]].append(b)
    calls = results.call_totals([r.id for r in runs])
    for run in runs:
        pipeline, doc = run.config_snapshot.get("name", "?"), codes.get(run.document_id, str(run.document_id))
        for b in best[run.id]:
            expected = b["expected_value"]
            label = "unlabelled" if expected is None else "absent" if expected == "" else "value"
            out.results.append(ResultRow(
                run.id, doc, pipeline, repeat.get(run.id), run.state, b["field_key"], b["retrieval_config"], label,
                b["status"], b["value"], expected, b["exact_match"],
                match_score(b["status"], b["value"], expected, b["exact_match"]), b["verdict"]))
        c = calls.get(run.id)
        seconds = (run.finished_at - run.started_at).total_seconds() if run.finished_at and run.started_at else None
        out.runs.append(RunRow(
            run.id, doc, pipeline, repeat.get(run.id), run.state, seconds, len(best[run.id]),
            c["calls"] if c else 0, c["prompt_tokens"] if c else 0, c["completion_tokens"] if c else 0,
            float(c["cost_usd"]) if c and c["cost_usd"] is not None else None,
            round(float(c["mean_latency_ms"]), 1) if c and c["mean_latency_ms"] is not None else None,
            ",".join(cl.contract_type.key for cl in run.classifications if cl.selected),
            _fingerprint(run.config_snapshot), run.error))
    return out


def _fingerprint(snapshot: dict) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()[:10]


def _mean(xs: list) -> float | None:
    xs = [float(x) for x in xs if x is not None]
    return round(statistics.fmean(xs), 4) if xs else None


def _rate(xs: list[bool]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def _quality(rows: list[ResultRow]) -> dict[str, Any]:
    """Accuracy on labels with a value, and handling of labels of "" (not in this contract)."""
    value = [r for r in rows if r.label == "value"]
    absent = [r for r in rows if r.label == "absent"]
    return {
        "value_labels": len(value),
        "value_exact": _rate([r.exact_match is True for r in value]),
        "value_score": _mean([r.score for r in value]),
        "value_missed": _rate([r.status == "not_found" for r in value]),
        "absent_labels": len(absent),
        "absent_correct": _rate([r.exact_match is True for r in absent]),
        "invented": _rate([r.status == "extracted" for r in absent]),
    }


def summary(c: Collected) -> list[dict[str, Any]]:
    """One row per pipeline, over its succeeded runs."""
    out = []
    for name in c.design.pipelines:
        runs = [r for r in c.runs if r.pipeline == name]
        ok = [r for r in runs if r.state == RunState.SUCCEEDED]
        ok_ids = {r.run_id for r in ok}
        rows = [r for r in c.results if r.run_id in ok_ids and r.label != "unlabelled"]
        by_repeat = defaultdict(list)
        for r in rows:
            if r.label == "value":
                by_repeat[r.repeat].append(r.score)
        repeat_means = [statistics.fmean(v) for v in by_repeat.values() if v]
        passed = [r for r in rows if r.verdict == "PASS"]
        failed = [r for r in rows if r.verdict == "FAIL"]
        out.append({
            "pipeline": name,
            "runs_succeeded": len(ok),
            "runs_failed": sum(r.state in _FAILED for r in runs),
            "documents": len({r.document for r in ok}),
            **_quality(rows),
            "value_score_sd": round(statistics.stdev(repeat_means), 4) if len(repeat_means) > 1 else None,
            "errors": _rate([r.status == "error" for r in rows]),
            "judge_pass": len(passed),
            "judge_pass_correct": _rate([r.exact_match is True for r in passed]),
            "judge_fail": len(failed),
            "judge_fail_correct": _rate([r.exact_match is False for r in failed]),
            "llm_calls_per_run": _mean([r.llm_calls for r in ok]),
            "tokens_per_run": _mean([r.prompt_tokens + r.completion_tokens for r in ok]),
            "cost_usd_per_run": _mean([r.cost_usd for r in ok]),
            "seconds_per_run": _mean([r.seconds for r in ok]),
            "snapshots": len({r.snapshot for r in ok}),
        })
    return out


def per_field(c: Collected) -> list[dict[str, Any]]:
    """One row per pipeline and field, over succeeded runs."""
    groups: dict[tuple[str, str], list[ResultRow]] = defaultdict(list)
    for r in c.results:
        if r.run_state == RunState.SUCCEEDED and r.label != "unlabelled":
            groups[(r.pipeline, r.field)].append(r)
    order = {p: i for i, p in enumerate(c.design.pipelines)}
    return [{"pipeline": p, "field": f, **_quality(rows)}
            for (p, f), rows in sorted(groups.items(), key=lambda kv: (order.get(kv[0][0], 99), kv[0][1]))]


def export(c: Collected, out_dir: Path) -> list[Path]:
    """results.csv, runs.csv, fields.csv, summary.csv and experiment.json in ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = [
        _csv(out_dir / "results.csv", [asdict(r) for r in c.results], json_cols=("value", "expected")),
        _csv(out_dir / "runs.csv", [asdict(r) for r in c.runs]),
        _csv(out_dir / "fields.csv", per_field(c)),
        _csv(out_dir / "summary.csv", summary(c)),
    ]
    meta = out_dir / "experiment.json"
    meta.write_text(json.dumps({
        "name": c.experiment.name, "description": c.experiment.description, "hypothesis": c.experiment.hypothesis,
        "created_at": c.experiment.created_at.isoformat(), "exported_at": datetime.now(timezone.utc).isoformat(),
        "design": c.design.model_dump(mode="json"),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return [*written, meta]


def _csv(path: Path, rows: list[dict[str, Any]], json_cols: tuple[str, ...] = ()) -> Path:
    with path.open("w", newline="", encoding="utf-8") as fh:
        if rows:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            for row in rows:
                writer.writerow({k: _cell(v, k in json_cols) for k, v in row.items()})
    return path


def _cell(value: Any, as_json: bool) -> Any:
    if value is None:
        return ""
    if as_json:
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value) if isinstance(value, uuid.UUID) else value
