"""Run execution against the test database with scripted models (fake chat, HashEmbedder, memory store).

The pipeline is the seeded default, narrowed to two fields and three RAG configs whose
thresholds are lowered so the small test PDF always yields evidence. RAG01 (top 10) and
RAG02 (top 5) both retrieve all three chunks, and RAG07 is RAG01's twin, so every field gets
identical evidence three times: with reuse only the first config calls the models.
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest
from sqlalchemy import func, select, update

from contract_extraction.core.settings import load_settings
from contract_extraction.domain.enums import RunKind, RunState
from contract_extraction.ingestion import register_file
from contract_extraction.persistence import models as m
from contract_extraction.persistence.repositories import ConfigRepo, RunRepo
from contract_extraction.persistence.repositories.results import ResultRepo
from contract_extraction.pipeline.executor import Providers, RunExecutor
from contract_extraction.pipeline.options import RunOptions, narrow
from contract_extraction.providers.base import ChatResult, ProviderError
from contract_extraction.providers.memory import MemoryStore
from helpers import BODY, HashEmbedder, make_pdf

FIELDS = ["customer_name", "payment_terms"]
_KEY = re.compile(r"extract the following fields:\s*\n\s*([a-z_]+)")


class ScriptedChat:
    """Extraction: finds Acme for customer_name, nothing else. Judge: PASS when the answer names Acme."""

    def __init__(self, judge: bool, fail_on: str | None = None, on_call=None):
        self.judge, self.fail_on, self.on_call = judge, fail_on, on_call
        self.calls: list[str] = []

    def complete(self, system, user, profile):
        self.calls.append(user)
        if self.on_call:
            self.on_call(len(self.calls))
        if self.judge:
            ok = "Acme" in user.split("Answer:", 1)[1]
            text = ('{"status": "PASS", "issue": "NONE", "explanation": "Stated in the preamble."}' if ok
                    else '{"status": "FAIL", "issue": "NO_CONTEXT", "explanation": "Not in the context."}')
        else:
            key = _KEY.search(user).group(1)
            if key == self.fail_on:
                raise ProviderError("model crashed")
            text = '{"%s": "%s"}' % (key, "Acme Pty Ltd" if key == "customer_name" else "")
        return ChatResult(text=text, latency_ms=12, prompt_tokens=200, completion_tokens=10, params={"model": profile.model.name})


class Harness:
    def __init__(self, db, storage, tmp_path, name: str, **chat_kwargs):
        self.db, self.storage, self.settings = db, storage, load_settings("test")
        self.extractor = ScriptedChat(judge=False, **chat_kwargs)
        self.judge = ScriptedChat(judge=True)
        self.embedder, self.store = HashEmbedder(), MemoryStore()
        self.providers = Providers(chat=lambda p: self.judge if p.name.startswith("judge") else self.extractor,
                                   embedder=lambda model: self.embedder, store=lambda kind: self.store)
        self.pdf = make_pdf(tmp_path / f"{name}.pdf", pages=[f"{b} {name}." for b in BODY])

    def pipeline(self, options: RunOptions, **changes):
        with self.db.session() as s:
            p = narrow(ConfigRepo(s).resolve_pipeline(), options)
        loose = tuple(r.model_copy(update={"score_threshold": Decimal("0"), "min_score": Decimal("0")}) for r in p.retrievals)
        return p.model_copy(update={"retrievals": loose, **changes})

    def enqueue(self, options: RunOptions | None = None, kind=RunKind.FULL, **changes):
        options = options or RunOptions(fields=FIELDS, retrievals=["RAG01", "RAG02", "RAG07"])
        doc_id, _, _ = register_file(self.db, self.storage, self.settings, self.pdf)
        with self.db.session() as s:
            return RunRepo(s).enqueue(doc_id, self.pipeline(options, **changes), kind,
                                      options.model_dump(exclude_defaults=True)).id

    def execute(self, run_id):
        return RunExecutor(self.db, self.storage, self.settings, self.providers).execute(run_id)


def _summary(db, run_id):
    with db.session() as s:
        run = RunRepo(s).get(run_id)
        best = {b["field_key"]: (b["value"], b["retrieval_config"], b["verdict"]) for b in ResultRepo(s).best_values(run_id)}
        count = lambda model, col: s.scalar(select(func.count()).select_from(model).where(col == run_id))  # noqa: E731
        results = count(m.FieldResult, m.FieldResult.run_id)
        calls = count(m.LlmCall, m.LlmCall.run_id)
        judgements = s.scalar(select(func.count()).select_from(m.Judgement).join(m.FieldResult)
                              .where(m.FieldResult.run_id == run_id))
        hits = s.scalar(select(func.count()).select_from(m.RetrievalHit).join(m.FieldResult)
                        .where(m.FieldResult.run_id == run_id))
        events = [e.message for e in RunRepo(s).events(run_id)]
        return run, best, results, calls, judgements, hits, events


def test_full_run_records_everything(db, storage, tmp_path):
    h = Harness(db, storage, tmp_path, "full")
    run_id = h.enqueue()
    assert h.execute(run_id) == RunState.SUCCEEDED

    run, best, results, calls, judgements, hits, events = _summary(db, run_id)
    assert (run.progress_done, run.progress_total) == (6, 6)
    assert run.started_at and run.finished_at and run.decomposition_id and run.vector_index_id
    assert results == 6 and judgements == 6 and hits == 18
    assert calls == 4, "2 fields x (extraction + judge); RAG02 and RAG07 reuse RAG01's answers"
    assert best["customer_name"] == ("Acme Pty Ltd", "RAG01", "PASS")
    assert best["payment_terms"] == (None, "RAG01", "FAIL")
    assert any("Stage extracting" in e for e in events) and any("Extraction finished" in e for e in events)

    with db.session() as s:
        call = s.scalars(select(m.LlmCall).where(m.LlmCall.run_id == run_id, m.LlmCall.purpose == "extraction")).first()
        assert call.user_prompt.endswith(">>>") and call.system_prompt and call.prompt_tokens == 200
        assert call.status == "ok" and call.provider_key == "ollama-local"


def test_reuse_can_be_turned_off(db, storage, tmp_path):
    h = Harness(db, storage, tmp_path, "noreuse")
    run_id = h.enqueue(RunOptions(fields=FIELDS, retrievals=["RAG01", "RAG02", "RAG07"], reuse_calls=False))
    assert h.execute(run_id) == RunState.SUCCEEDED
    _, best, results, calls, judgements, _, _ = _summary(db, run_id)
    assert calls == 12 and results == 6 and judgements == 6
    assert best["customer_name"][2] == "PASS"


def test_parallel_judge_matches_sequential(db, storage, tmp_path):
    h = Harness(db, storage, tmp_path, "parallel")
    run_id = h.enqueue(judge_parallel=True)
    assert h.execute(run_id) == RunState.SUCCEEDED
    run, best, results, calls, judgements, _, events = _summary(db, run_id)
    assert (run.progress_done, run.progress_total) == (6, 6)
    assert (results, calls, judgements) == (6, 4, 6)
    assert best["customer_name"] == ("Acme Pty Ltd", "RAG01", "PASS")


def test_extraction_error_does_not_stop_the_run(db, storage, tmp_path):
    h = Harness(db, storage, tmp_path, "error", fail_on="payment_terms")
    run_id = h.enqueue()
    assert h.execute(run_id) == RunState.SUCCEEDED
    with db.session() as s:
        rows = s.execute(select(m.FieldResult.status, m.Judgement.verdict).join(m.Judgement)
                         .join(m.Field).where(m.FieldResult.run_id == run_id, m.Field.key == "payment_terms")).all()
    assert rows == [("error", "SKIPPED")] * 3, "errors are retried per config, never reused"
    assert len(h.extractor.calls) == 4


def test_judge_off(db, storage, tmp_path):
    h = Harness(db, storage, tmp_path, "nojudge")
    run_id = h.enqueue(RunOptions(fields=FIELDS, retrievals=["RAG01"], judge=False))
    assert h.execute(run_id) == RunState.SUCCEEDED
    run, best, results, calls, judgements, _, _ = _summary(db, run_id)
    assert (results, calls, judgements) == (2, 2, 0) and not h.judge.calls
    assert best["customer_name"] == ("Acme Pty Ltd", "RAG01", None)


def test_cancellation_between_fields(db, storage, tmp_path):
    holder = {}

    def cancel_after_first(n):
        if n == 1:
            with db.session() as s:
                RunRepo(s).request_cancel(holder["run_id"])

    h = Harness(db, storage, tmp_path, "cancel", on_call=cancel_after_first)
    holder["run_id"] = run_id = h.enqueue()
    assert h.execute(run_id) == RunState.CANCELLED
    run, _, results, _, _, _, events = _summary(db, run_id)
    assert run.state == "cancelled" and run.finished_at
    assert results == 1 and run.progress_done == 1
    assert "Run cancelled" in events


def test_decompose_only_run(db, storage, tmp_path):
    h = Harness(db, storage, tmp_path, "decompose")
    run_id = h.enqueue(kind=RunKind.DECOMPOSE)
    assert h.execute(run_id) == RunState.SUCCEEDED
    run, _, results, calls, _, _, _ = _summary(db, run_id)
    assert results == 0 and calls == 0 and run.vector_index_id


def test_run_uses_its_snapshot_not_live_config(db, storage, tmp_path):
    h = Harness(db, storage, tmp_path, "snapshot")
    run_id = h.enqueue()
    with db.session() as s:
        original = s.scalar(select(m.Field.user_prompt).where(m.Field.key == "customer_name"))
        s.execute(update(m.Field).where(m.Field.key == "customer_name").values(user_prompt="CHANGED AFTER ENQUEUE"))
    try:
        assert h.execute(run_id) == RunState.SUCCEEDED
        assert not any(c.startswith("CHANGED") for c in h.extractor.calls)
    finally:
        with db.session() as s:
            s.execute(update(m.Field).where(m.Field.key == "customer_name").values(user_prompt=original))


def test_only_queued_runs_execute(db, storage, tmp_path):
    from contract_extraction.core.errors import Conflict

    h = Harness(db, storage, tmp_path, "twice")
    run_id = h.enqueue(RunOptions(fields=["customer_name"], retrievals=["RAG01"]))
    h.execute(run_id)
    with pytest.raises(Conflict):
        h.execute(run_id)
