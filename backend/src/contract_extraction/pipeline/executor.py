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
* Cancellation (``runs.cancel_requested``) is checked before each field.

The Phase 4 worker calls this same executor; the CLI runs it inline.
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
from ..domain.enums import EventLevel, FieldResultStatus, LlmCallPurpose, RunKind, RunStage, RunState, Verdict
from ..extraction.judge import JudgeOutcome, parse_verdict
from ..extraction.parsing import field_value
from ..extraction.prompts import build_context, extraction_prompt, judge_prompt
from ..extraction.retrieval import Hit, Retriever
from ..indexing.indexer import build_index
from ..ingestion import ensure_decomposition
from ..persistence.db import Database
from ..persistence.repositories import RunRepo
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
    """Cancellation was requested; raised between fields."""


class RunExecutor:
    def __init__(self, db: Database, storage: FileStorage, settings: Settings,
                 providers: Providers | None = None, worker_id: str = "local"):
        self.db = db
        self.storage = storage
        self.settings = settings
        self.providers = providers or Providers.from_settings(settings)
        self.worker_id = worker_id

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
            RunRepo(s).finish(run_id, state, error)
        return state

    def execute(self, run_id: uuid.UUID) -> RunState:
        """Run ``run_id`` (which must be queued) to completion; returns the final state."""
        with self.db.session() as s:
            run = RunRepo(s).start(run_id, self.worker_id)
            pipeline = PipelineConfig.model_validate(run.config_snapshot)
            options = RunOptions.model_validate(run.options)
            kind, document_id = RunKind(run.kind), run.document_id

        try:
            self.event(run_id, f"Run started: {kind}, pipeline {pipeline.name}, "
                               f"{len(pipeline.field_set.fields)} fields x {len(pipeline.retrievals)} RAG configs")
            self._stage(run_id, RunStage.DECOMPOSING)
            dec = ensure_decomposition(self.db, self.storage, document_id, pipeline.decomposition, options.redecompose)
            self.event(run_id, f"Decomposition {'reused' if dec.reused else 'created'}: {dec.page_count} pages",
                       stage=RunStage.DECOMPOSING, decomposition_id=str(dec.decomposition_id))

            self._stage(run_id, RunStage.INDEXING)
            store = self.providers.store(pipeline.index.vector_store)
            idx = build_index(self.db, dec.decomposition_id, dec.document_code, pipeline.index,
                              self.providers.embedder(pipeline.index.embedding_model), store)
            with self.db.session() as s:
                RunRepo(s).attach(run_id, dec.decomposition_id, idx.vector_index_id)
            self.event(run_id, f"Index {'reused' if idx.reused else 'built'}: {idx.chunk_count} chunks",
                       stage=RunStage.INDEXING, collection=idx.collection_name)

            if kind != RunKind.DECOMPOSE:
                self._stage(run_id, RunStage.EXTRACTING)
                summary = _Extraction(self, run_id, pipeline, options, store, idx.collection_name).run()
                self.event(run_id, "Extraction finished", stage=RunStage.EXTRACTING, **summary)
            return self._finish(run_id, RunState.SUCCEEDED)
        except RunCancelled:
            self.event(run_id, "Run cancelled", EventLevel.WARNING)
            return self._finish(run_id, RunState.CANCELLED)
        except Exception as exc:  # noqa: BLE001 - any failure ends the run as failed, with the reason recorded
            log.exception("Run %s failed", run_id)
            message = f"{exc.__class__.__name__}: {exc}"
            self.event(run_id, f"Run failed: {message}", EventLevel.ERROR)
            return self._finish(run_id, RunState.FAILED, message)


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


class _Extraction:
    def __init__(self, ex: RunExecutor, run_id: uuid.UUID, pipeline: PipelineConfig, options: RunOptions,
                 store: VectorStore, collection: str):
        self.ex, self.db, self.run_id, self.p, self.options = ex, ex.db, run_id, pipeline, options
        self.retriever = Retriever(store, collection, ex.providers.embedder(pipeline.index.embedding_model))
        self.chat = ex.providers.chat(pipeline.extraction_profile)
        self.judge_chat = ex.providers.chat(pipeline.judge_profile) if pipeline.judge_enabled and pipeline.judge_profile else None
        self.total = len(pipeline.field_set.fields) * len(pipeline.retrievals)
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
                for f in self.p.field_set.fields:
                    with self.db.session() as s:
                        if RunRepo(s).cancel_requested(self.run_id):
                            raise RunCancelled
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
