"""Run executor: carries out one queued run from its stored configuration snapshot.

    queued → running → ensure decomposition → ensure index → extract → succeeded | failed | cancelled

Extraction goes through the run's RAG configs in priority order and, for each, through its
fields: retrieve evidence → extraction LLM → judge LLM. Every field result is committed on
its own, so progress and partial results are visible while the run is going.

* A provider error on one field records an ``error`` result (judged SKIPPED); the run goes on.
* A field that receives exactly the same evidence (same chunks, same order) again in this run
  reuses the earlier answer and verdict instead of calling the models again (``reuse_calls``).
  The profile is fixed per run, so (field, chunks) fully determines the prompt. Failed answers
  are not reused, so a transient provider error gets another chance.
* With ``judge_parallel`` the judge calls run on a small thread pool; the run waits for them.
* Cancellation (``runs.cancel_requested``, or the worker shutting down) is checked before each field.
* A heartbeat thread updates ``runs.heartbeat_at`` while the run executes. If the run stops being
  ours (a worker marked it failed as stale), the executor stops at the next field and leaves it as is.

The worker claims runs and calls ``run_claimed``; the CLI's inline path calls ``execute``.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field as dc_field
from typing import Any

from ..core.settings import Settings
from ..domain.config import Field, Model, ModelProfile, PipelineConfig, RetrievalConfig
from ..domain.enums import (
    ClassificationSource,
    EventLevel,
    FieldResultStatus,
    LlmCallPurpose,
    RunKind,
    RunStage,
    RunState,
    Verdict,
)
from ..extraction import classify
from ..extraction.judge import JudgeOutcome, parse_verdict
from ..extraction.parsing import field_value
from ..extraction.prompts import build_context, extraction_prompt, judge_prompt
from ..extraction.retrieval import Hit, Retriever
from ..extraction.validation import conform
from ..indexing.indexer import build_index
from ..ingestion import ensure_decomposition
from ..persistence.db import Database
from ..persistence.repositories import RunRepo
from ..persistence.repositories.artifacts import IndexRepo
from ..persistence.repositories.results import ResultRepo
from ..providers import factory
from ..providers.base import ChatClient, ChatResult, Embedder, ProviderError, VectorStore
from ..storage import FileStorage
from .options import RunOptions

log = logging.getLogger(__name__)

# A prompt using this share of the context window was most likely cut by the provider.
TRUNCATION_RATIO = 0.95


@dataclass
class Providers:
    """How the executor obtains model and store clients (tests pass fakes)."""

    chat: Callable[[ModelProfile], ChatClient]
    embedder: Callable[[Model], Embedder]
    store: Callable[[str], VectorStore]

    @classmethod
    def from_settings(cls, settings: Settings) -> Providers:
        return cls(chat=lambda p: factory.chat_client(p, settings),
                   embedder=lambda mo: factory.embedder(mo, settings),
                   store=lambda kind: factory.vector_store(kind, settings))


class RunCancelled(Exception):
    """Cancellation was requested (or the worker is shutting down); raised between fields."""


class RunLost(Exception):
    """The run is no longer running under this worker (e.g. marked failed as stale); stop without touching it."""


class _Heartbeat:
    """Background thread proving the run is alive while long model calls block the main thread."""

    def __init__(self, db: Database, run_id: uuid.UUID, worker_id: str, interval: float):
        self.db, self.run_id, self.worker_id, self.interval = db, run_id, worker_id, interval
        self.lost = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name=f"heartbeat-{run_id}", daemon=True)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                with self.db.session() as s:
                    if not RunRepo(s).heartbeat(self.run_id, self.worker_id):
                        self.lost = True
                        return
            except Exception:  # noqa: BLE001 - a missed beat is retried; a long outage ends in stale detection
                log.warning("Heartbeat for run %s failed", self.run_id, exc_info=True)

    def __enter__(self) -> _Heartbeat:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)


class RunExecutor:
    def __init__(self, db: Database, storage: FileStorage, settings: Settings,
                 providers: Providers | None = None, worker_id: str = "local"):
        self.db = db
        self.storage = storage
        self.settings = settings
        self.providers = providers or Providers.from_settings(settings)
        self.worker_id = worker_id
        # Set by the worker on shutdown: the current run is cancelled at the next field.
        self.stop_event = threading.Event()
        self._heartbeat: _Heartbeat | None = None

    def check_continue(self, run_id: uuid.UUID) -> None:
        """Called between fields and stages: raise if the run must stop."""
        if self._heartbeat is not None and self._heartbeat.lost:
            raise RunLost
        if self.stop_event.is_set():
            raise RunCancelled("Worker is shutting down")
        with self.db.session() as s:
            if RunRepo(s).cancel_requested(run_id):
                raise RunCancelled("Cancellation requested")

    def event(self, run_id: uuid.UUID, message: str, level: EventLevel = EventLevel.INFO,
              stage: RunStage | None = None, **data: Any) -> None:
        with self.db.session() as s:
            RunRepo(s).add_event(run_id, message, level, stage, data)

    def _stage(self, run_id: uuid.UUID, stage: RunStage) -> None:
        with self.db.session() as s:
            RunRepo(s).set_stage(run_id, stage)
        self.event(run_id, f"Stage {stage}", stage=stage)

    def _finish(self, run_id: uuid.UUID, state: RunState, error: str | None = None) -> RunState:
        with self.db.session() as s:
            repo = RunRepo(s)
            if repo.finish(run_id, state, error):
                return state
            return RunState(repo.get(run_id).state)  # already finished elsewhere (e.g. failed as stale)

    def execute(self, run_id: uuid.UUID) -> RunState:
        """Start ``run_id`` (which must be queued) and run it to completion; returns the final state."""
        with self.db.session() as s:
            RunRepo(s).start(run_id, self.worker_id)
        return self.run_claimed(run_id)

    def run_claimed(self, run_id: uuid.UUID) -> RunState:
        """Run a run that this executor's worker already marked running; returns the final state."""
        with self.db.session() as s:
            run = RunRepo(s).get(run_id)
            pipeline = PipelineConfig.model_validate(run.config_snapshot)
            options = RunOptions.model_validate(run.options)
            kind, document_id = RunKind(run.kind), run.document_id
        with _Heartbeat(self.db, run_id, self.worker_id, self.settings.worker.heartbeat_seconds) as hb:
            self._heartbeat = hb
            try:
                return self._run(run_id, pipeline, options, kind, document_id)
            finally:
                self._heartbeat = None

    def _run(self, run_id: uuid.UUID, pipeline: PipelineConfig, options: RunOptions, kind: RunKind,
             document_id: uuid.UUID) -> RunState:
        try:
            self.event(run_id, f"Run started: {kind}, pipeline {pipeline.name}, {len(pipeline.retrievals)} RAG configs")
            self._stage(run_id, RunStage.DECOMPOSING)
            dec = ensure_decomposition(self.db, self.storage, document_id, pipeline.decomposition, options.redecompose)
            self.event(run_id, f"Decomposition {'reused' if dec.reused else 'created'}: {dec.page_count} pages",
                       stage=RunStage.DECOMPOSING, decomposition_id=str(dec.decomposition_id))

            self.check_continue(run_id)
            self._stage(run_id, RunStage.INDEXING)
            store = self.providers.store(pipeline.index.vector_store)
            idx = build_index(self.db, dec.decomposition_id, dec.document_code, pipeline.index,
                              self.providers.embedder(pipeline.index.embedding_model), store)
            with self.db.session() as s:
                RunRepo(s).attach(run_id, dec.decomposition_id, idx.vector_index_id)
            self.event(run_id, f"Index {'reused' if idx.reused else 'built'}: {idx.chunk_count} chunks",
                       stage=RunStage.INDEXING, collection=idx.collection_name)

            if kind != RunKind.DECOMPOSE:
                self.check_continue(run_id)
                type_keys = self._contract_types(run_id, pipeline, options, idx.vector_index_id)
                fields = select_fields(pipeline, options, type_keys)
                self.check_continue(run_id)
                self._stage(run_id, RunStage.EXTRACTING)
                self.event(run_id, f"Extracting {len(fields)} fields x {len(pipeline.retrievals)} RAG configs",
                           stage=RunStage.EXTRACTING, fields=[f.key for f in fields])
                summary = _Extraction(self, run_id, pipeline, options, fields, store, idx.collection_name).run()
                self.event(run_id, "Extraction finished", stage=RunStage.EXTRACTING, **summary)
            return self._finish(run_id, RunState.SUCCEEDED)
        except RunLost:
            log.warning("Run %s is no longer ours (marked stale?); stopping without changing it", run_id)
            with self.db.session() as s:
                return RunState(RunRepo(s).get(run_id).state)
        except RunCancelled as exc:
            self.event(run_id, f"Run cancelled: {exc}" if str(exc) else "Run cancelled", EventLevel.WARNING)
            return self._finish(run_id, RunState.CANCELLED)
        except Exception as exc:  # noqa: BLE001 - any failure ends the run as failed, with the reason recorded
            log.exception("Run %s failed", run_id)
            message = f"{exc.__class__.__name__}: {exc}"
            self.event(run_id, f"Run failed: {message}", EventLevel.ERROR)
            return self._finish(run_id, RunState.FAILED, message)


    # ---- contract types ------------------------------------------------------------------------

    def _contract_types(self, run_id: uuid.UUID, pipeline: PipelineConfig, options: RunOptions,
                        index_id: uuid.UUID) -> tuple[str, ...]:
        """The contract types whose fields the run extracts, recorded in run_classifications.

        Empty when the run's fields were chosen explicitly or the field set defines no types.
        """
        fs = pipeline.field_set
        if options.fields is not None or not fs.contract_types:
            return ()
        types = {t.key: t for t in fs.contract_types}
        fallback = fs.fallback_type
        if options.contract_types:
            with self.db.session() as s:
                for key in options.contract_types:
                    ResultRepo(s).add_classification(run_id, types[key].id, ClassificationSource.OVERRIDE, True)
            self.event(run_id, "Contract type from the run options: " + ", ".join(types[k].label for k in options.contract_types),
                       contract_types=list(options.contract_types))
            return tuple(options.contract_types)
        if not pipeline.classification_enabled:
            with self.db.session() as s:
                ResultRepo(s).add_classification(run_id, fallback.id, ClassificationSource.FALLBACK, True)
            self.event(run_id, f"Contract type: {fallback.label} (classification is off for this pipeline)",
                       contract_types=[fallback.key])
            return (fallback.key,)

        self._stage(run_id, RunStage.CLASSIFYING)
        candidates, call_id = self._classify(run_id, pipeline, index_id)
        chosen = classify.select(candidates, pipeline.classification_min_confidence, fallback.key)
        said_fallback = next((c for c in candidates if c.key in (classify.OTHER, fallback.key)), None)
        with self.db.session() as s:
            repo = ResultRepo(s)
            for c in candidates:
                if c.key in types and c.key != fallback.key:
                    repo.add_classification(run_id, types[c.key].id, ClassificationSource.CLASSIFIER, c.key in chosen,
                                            c.confidence, c.evidence, call_id)
            if not chosen:
                repo.add_classification(run_id, fallback.id, ClassificationSource.FALLBACK, True,
                                        said_fallback.confidence if said_fallback else None,
                                        said_fallback.evidence if said_fallback else None, call_id)
        if chosen:
            labels = ", ".join(f"{types[c.key].label} ({c.confidence})" for c in candidates if c.key in chosen)
            self.event(run_id, f"Contract type: {labels}", stage=RunStage.CLASSIFYING, contract_types=chosen)
            return tuple(chosen)
        reason = (f"no type reached confidence {pipeline.classification_min_confidence}" if candidates
                  else "the classifier proposed no known type")
        self.event(run_id, f"Contract type: {fallback.label} (fallback: {reason})", stage=RunStage.CLASSIFYING,
                   contract_types=[fallback.key])
        return (fallback.key,)

    def _classify(self, run_id: uuid.UUID, pipeline: PipelineConfig,
                  index_id: uuid.UUID) -> tuple[list[classify.Candidate], uuid.UUID]:
        """Ask the classification model about the document's first pages; a failed call proposes nothing."""
        profile, system = pipeline.classification_profile, pipeline.classification_prompt.body
        with self.db.session() as s:
            chunks = [(c.page_start, c.text) for c in IndexRepo(s).chunks(index_id)]
        text = classify.opening_text(chunks, pipeline.classification_pages)
        user = classify.classification_prompt(pipeline.field_set.contract_types, text)
        result, error, timeout, candidates = None, None, False, []
        try:
            result = self.providers.chat(profile).complete(system, user, profile)
            candidates = classify.parse_classification(result.text, {t.key for t in pipeline.field_set.contract_types})
        except ProviderError as exc:
            error, timeout = str(exc), exc.timeout
        with self.db.session() as s:
            call_id = ResultRepo(s).add_llm_call(run_id=run_id, field_result_id=None, purpose=LlmCallPurpose.CLASSIFICATION,
                                                 profile=profile, system_prompt=system, user_prompt=user, result=result,
                                                 error=error, timeout=timeout)
        if error:
            self.event(run_id, f"Classification failed: {error}", EventLevel.WARNING, RunStage.CLASSIFYING,
                       llm_call_id=str(call_id))
        elif not candidates:
            self.event(run_id, f"Classifier answer names no known contract type: {(result.text or '')[:200]}",
                       EventLevel.WARNING, RunStage.CLASSIFYING, llm_call_id=str(call_id))
        return candidates, call_id


@dataclass
class _Answer:
    """An extraction outcome, kept so identical evidence later in the run can reuse it."""

    field_result_id: uuid.UUID
    status: FieldResultStatus
    value: Any
    raw_answer: str | None
    error: str | None
    judgement: JudgeOutcome | Future[JudgeOutcome] | None = dc_field(default=None)

    def verdict(self) -> JudgeOutcome | None:
        return self.judgement.result() if isinstance(self.judgement, Future) else self.judgement


def select_fields(pipeline: PipelineConfig, options: RunOptions, type_keys: tuple[str, ...]) -> tuple[Field, ...]:
    """Fields a run extracts: exactly the ones chosen in the run options, else those of the given contract
    types (the fallback type when none are given) down to the pipeline's minimum priority."""
    if options.fields is not None:
        return pipeline.field_set.fields  # already narrowed to the chosen fields
    return pipeline.field_set.fields_for_types(type_keys, pipeline.min_priority)


class _Extraction:
    def __init__(self, ex: RunExecutor, run_id: uuid.UUID, pipeline: PipelineConfig, options: RunOptions,
                 fields: tuple[Field, ...], store: VectorStore, collection: str):
        self.ex, self.db, self.run_id, self.p, self.options = ex, ex.db, run_id, pipeline, options
        self.fields = fields
        self.retriever = Retriever(store, collection, ex.providers.embedder(pipeline.index.embedding_model))
        self.chat = ex.providers.chat(pipeline.extraction_profile)
        self.judge_chat = ex.providers.chat(pipeline.judge_profile) if pipeline.judge_enabled and pipeline.judge_profile else None
        self.total = len(fields) * len(pipeline.retrievals)
        self._lock = threading.Lock()
        self.done = self.calls = self.reused = 0

    # ---- bookkeeping ---------------------------------------------------------------------------

    def _advance(self) -> None:
        with self._lock:
            self.done += 1
            done = self.done
        with self.db.session() as s:
            RunRepo(s).set_progress(self.run_id, done, self.total)

    def _count_call(self) -> None:
        with self._lock:
            self.calls += 1

    def _check_truncation(self, profile: ModelProfile, result: ChatResult | None, what: str, call_id: uuid.UUID) -> None:
        if result and result.prompt_tokens and profile.num_ctx and result.prompt_tokens >= TRUNCATION_RATIO * profile.num_ctx:
            self.ex.event(self.run_id, f"{what}: prompt used {result.prompt_tokens} of {profile.num_ctx} context tokens "
                                       "and was probably truncated", EventLevel.WARNING, RunStage.EXTRACTING,
                          llm_call_id=str(call_id))

    # ---- steps ---------------------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        with self.db.session() as s:
            RunRepo(s).set_progress(self.run_id, 0, self.total)
        pool = None
        if self.judge_chat and self.p.judge_parallel:
            pool = ThreadPoolExecutor(self.ex.settings.executor.judge_workers, thread_name_prefix="judge")
        pending: list[Future[JudgeOutcome]] = []
        answers: dict[tuple, _Answer] = {}
        try:
            for rc in self.p.retrievals:
                for f in self.fields:
                    self.ex.check_continue(self.run_id)
                    hits = self.retriever.retrieve(f, rc)
                    key = (f.id, tuple(h.chunk_id for h in hits))
                    if self.options.reuse_calls and key in answers:
                        self._reuse(answers[key], f, rc, hits)
                        continue
                    answer = self._extract(f, rc, hits)
                    if answer.status != FieldResultStatus.ERROR:  # failed calls are retried, not reused
                        answers[key] = answer
                    if self.judge_chat is None:
                        self._advance()
                    elif answer.status == FieldResultStatus.ERROR:
                        answer.judgement = self._skip_judge(answer)
                        self._advance()
                    elif pool is not None:
                        answer.judgement = pool.submit(self._judge, answer, f, build_context(hits))
                        pending.append(answer.judgement)
                    else:
                        answer.judgement = self._judge(answer, f, build_context(hits))
            for future in pending:
                future.result()
        finally:
            if pool is not None:
                pool.shutdown(wait=True, cancel_futures=True)
        return {"field_results": self.total, "llm_calls": self.calls, "reused": self.reused,
                "judge_parallel": pool is not None}

    def _extract(self, f: Field, rc: RetrievalConfig, hits: list[Hit]) -> _Answer:
        profile, system = self.p.extraction_profile, self.p.extraction_prompt.body
        user = extraction_prompt(f, build_context(hits))
        result, error, timeout = None, None, False
        try:
            result = self.chat.complete(system, user, profile)
            status, value = field_value(result.text, f.key)
            if status == FieldResultStatus.EXTRACTED:
                value, problems = conform(value, f.value_schema)
                if problems:
                    status, value, error = FieldResultStatus.ERROR, None, "Answer does not fit the field's type: " + "; ".join(problems[:3])
        except ProviderError as exc:
            status, value, error, timeout = FieldResultStatus.ERROR, None, str(exc), exc.timeout
        self._count_call()
        with self.db.session() as s:
            repo = ResultRepo(s)
            fr_id = repo.add_field_result(self.run_id, f.id, rc.id, status, value, result.text if result else None,
                                          error, result.latency_ms if result else None, hits)
            call_id = repo.add_llm_call(run_id=self.run_id, field_result_id=fr_id, purpose=LlmCallPurpose.EXTRACTION,
                                        profile=profile, system_prompt=system, user_prompt=user, result=result,
                                        error=error, timeout=timeout)
        self._check_truncation(profile, result, f"Extraction of {f.key} ({rc.name})", call_id)
        log.info("[%s] %-28s %s %r", rc.name, f.key, status, value if error is None else error[:120])
        return _Answer(fr_id, status, value, result.text if result else None, error)

    def _judge(self, answer: _Answer, f: Field, context: str) -> JudgeOutcome:
        profile, system = self.p.judge_profile, self.p.judge_prompt.body
        user = judge_prompt(f, context, answer.raw_answer or "")
        result, error, timeout = None, None, False
        try:
            result = self.judge_chat.complete(system, user, profile)
            outcome = parse_verdict(result.text)
        except ProviderError as exc:
            error, timeout = str(exc), exc.timeout
            outcome = JudgeOutcome(Verdict.ERROR, None, f"Judge call failed: {exc}")
        self._count_call()
        with self.db.session() as s:
            repo = ResultRepo(s)
            call_id = repo.add_llm_call(run_id=self.run_id, field_result_id=answer.field_result_id,
                                        purpose=LlmCallPurpose.JUDGE, profile=profile, system_prompt=system,
                                        user_prompt=user, result=result, error=error, timeout=timeout)
            repo.add_judgement(answer.field_result_id, outcome.verdict, outcome.issue, outcome.explanation, profile.id, call_id)
        self._check_truncation(profile, result, f"Judge of {f.key}", call_id)
        self._advance()
        return JudgeOutcome(outcome.verdict, outcome.issue, outcome.explanation, call_id)

    def _skip_judge(self, answer: _Answer) -> JudgeOutcome:
        outcome = JudgeOutcome(Verdict.SKIPPED, None, "Extraction failed; not judged")
        with self.db.session() as s:
            ResultRepo(s).add_judgement(answer.field_result_id, outcome.verdict, None, outcome.explanation,
                                        self.p.judge_profile.id, None)
        return outcome

    def _reuse(self, prior: _Answer, f: Field, rc: RetrievalConfig, hits: list[Hit]) -> None:
        verdict = prior.verdict()  # waits for a pooled judge call if needed
        with self.db.session() as s:
            repo = ResultRepo(s)
            fr_id = repo.add_field_result(self.run_id, f.id, rc.id, prior.status, prior.value, prior.raw_answer,
                                          prior.error, None, hits)
            if verdict is not None:
                repo.add_judgement(fr_id, verdict.verdict, verdict.issue, verdict.explanation,
                                   self.p.judge_profile.id if self.p.judge_profile else None, verdict.llm_call_id)
            RunRepo(s).add_event(self.run_id, f"{f.key} ({rc.name}): same evidence as an earlier config, answer reused",
                                 EventLevel.DEBUG, RunStage.EXTRACTING,
                                 {"field_result_id": str(fr_id), "reused_from": str(prior.field_result_id)})
        with self._lock:
            self.reused += 1
        self._advance()
