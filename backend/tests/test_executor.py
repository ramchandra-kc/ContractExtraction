"""Run execution against the test database with scripted models (fake chat, HashEmbedder, memory store).

The pipeline is the seeded default, narrowed to two fields and three RAG configs whose
thresholds are lowered so the small test PDF always yields evidence. RAG01 (top 10), RAG02
(top 5) and RAG03 (top 3) all retrieve its three chunks, so every field gets identical
evidence three times: with reuse only the first config calls the models.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal

import pytest
from sqlalchemy import func, select, update

from contract_extraction.core.settings import load_settings
from contract_extraction.domain.enums import Granularity, Priority, RunKind, RunState
from contract_extraction.ingestion import register_file
from contract_extraction.persistence import models as m
from contract_extraction.persistence.repositories import ConfigRepo, RunRepo
from contract_extraction.persistence.repositories.results import ResultRepo
from contract_extraction.pipeline import executor
from contract_extraction.pipeline.executor import Providers, RunExecutor
from contract_extraction.pipeline.options import RunOptions, narrow
from contract_extraction.providers.base import ChatResult, ProviderError
from contract_extraction.providers.memory import MemoryStore
from helpers import BODY, HashEmbedder, make_pdf

FIELDS = ["title", "payment_terms"]
_KEY = re.compile(r"extract the following fields?:\s*\n\s*([a-z_]+)")


MSA = '{"types": [{"key": "msa", "confidence": 0.92, "evidence": "This Master Services Agreement"}]}'


class ScriptedChat:
    """Extraction: finds Acme for title, nothing else (or the scripted ``answers``). Judge: PASS when the
    answer names Acme. Classifier: answers ``classification`` (an MSA by default)."""

    def __init__(self, judge: bool, fail_on: str | None = None, on_call=None, answers: dict | None = None,
                 classification: str | Exception = MSA, group_text: str | None = None, streams: bool = False):
        self.judge, self.fail_on, self.on_call = judge, fail_on, on_call
        self.answers = {"title": "Acme Pty Ltd", **(answers or {})}
        self.classification, self.group_text = classification, group_text
        self.streams = streams  # call the checkpoint after on_call, as a streaming provider would between chunks
        self.calls: list[str] = []

    def complete(self, system, user, profile, checkpoint=None):
        self.calls.append(user)
        if self.on_call:
            self.on_call(len(self.calls))
        if self.streams and checkpoint is not None:
            checkpoint()
        if user.startswith("Contract types:"):
            if isinstance(self.classification, Exception):
                raise self.classification
            text = self.classification
        elif self.judge:
            ok = "Acme" in user.split("Answer:", 1)[1]
            text = ('{"status": "PASS", "issue": "NONE", "explanation": "Stated in the preamble."}' if ok
                    else '{"status": "FAIL", "issue": "NO_CONTEXT", "explanation": "Not in the context."}')
        elif "\nDefinitions:\n" in user:  # group extraction: every listed key in one object
            keys = user.split("fields:\n", 1)[1].split("\n\n", 1)[0].splitlines()
            if self.fail_on in keys:
                raise ProviderError("model crashed")
            text = self.group_text or json.dumps({k: self.answers.get(k) for k in keys})
        else:
            key = _KEY.search(user).group(1)
            if key == self.fail_on:
                raise ProviderError("model crashed")
            text = json.dumps({key: self.answers.get(key, "")})
        return ChatResult(text=text, latency_ms=12, prompt_tokens=200, completion_tokens=10, params={"model": profile.model.name})


class Harness:
    def __init__(self, db, storage, tmp_path, name: str, classification: str | Exception = MSA, **chat_kwargs):
        self.db, self.storage, self.settings = db, storage, load_settings("test")
        self.extractor = ScriptedChat(judge=False, **chat_kwargs)
        self.judge = ScriptedChat(judge=True)
        self.classifier = ScriptedChat(judge=False, classification=classification)
        self.embedder, self.store = HashEmbedder(), MemoryStore()
        chats = {"judge-default": self.judge, "classification-default": self.classifier}
        self.providers = Providers(chat=lambda p: chats.get(p.name, self.extractor),
                                   embedder=lambda model: self.embedder, store=lambda kind: self.store)
        self.pdf = make_pdf(tmp_path / f"{name}.pdf", pages=[f"{b} {name}." for b in BODY])

    def pipeline(self, options: RunOptions, **changes):
        with self.db.session() as s:
            p = narrow(ConfigRepo(s).resolve_pipeline(), options)
        loose = tuple(r.model_copy(update={"score_threshold": Decimal("0"), "min_score": Decimal("0")}) for r in p.retrievals)
        return p.model_copy(update={"retrievals": loose, **changes})

    def enqueue(self, options: RunOptions | None = None, kind=RunKind.FULL, **changes):
        options = options or RunOptions(fields=FIELDS, retrievals=["RAG01", "RAG02", "RAG03"])
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
    assert calls == 4, "2 fields x (extraction + judge); RAG02 and RAG03 reuse RAG01's answers"
    assert best["title"] == ("Acme Pty Ltd", "RAG01", "PASS")
    assert best["payment_terms"] == (None, "RAG01", "FAIL")
    assert any("Stage extracting" in e for e in events) and any("Extraction finished" in e for e in events)
    assert "Extracting 2 fields x 3 RAG configs" in events

    with db.session() as s:
        call = s.scalars(select(m.LlmCall).where(m.LlmCall.run_id == run_id, m.LlmCall.purpose == "extraction")).first()
        assert call.user_prompt.endswith(">>>") and call.system_prompt and call.prompt_tokens == 200
        assert call.status == "ok" and call.provider_key == "ollama-local"


def _classifications(db, run_id) -> list[tuple]:
    with db.session() as s:
        return [(c.contract_type.key, c.source, c.selected, c.confidence and float(c.confidence))
                for c in ResultRepo(s).classifications(run_id)]


TYPED = RunOptions(retrievals=["RAG01"], judge=False)


def test_detected_contract_type_decides_the_fields(db, storage, tmp_path):
    h = Harness(db, storage, tmp_path, "classify")
    run_id = h.enqueue(TYPED)
    assert h.execute(run_id) == RunState.SUCCEEDED
    run, best, results, calls, _, _, events = _summary(db, run_id)
    assert results == 66 and run.progress_total == 66 and calls == 1 + 66, "MSA fields; one classification call"
    assert {"rate_card", "liability_cap", "title"} <= set(best) and "nda_direction" not in best
    assert _classifications(db, run_id) == [("msa", "classifier", True, 0.92)]
    assert "Contract type: MSA (0.920)" in events and any("Stage classifying" in e for e in events)
    assert "Master Services Agreement" in h.classifier.calls[0], "the classifier reads the document's first pages"
    keys = [_KEY.search(c).group(1) for c in h.extractor.calls]
    assert keys[0] == "document_status", "P1 fields first, then field-set order"
    with db.session() as s:
        purposes = s.scalars(select(m.LlmCall.purpose).where(m.LlmCall.run_id == run_id)).all()
    assert purposes.count("classification") == 1


def test_several_types_extract_the_union(db, storage, tmp_path):
    answer = '{"types": [{"key": "msa", "confidence": 0.9}, {"key": "sow", "confidence": "80%"}, {"key": "nda", "confidence": 0.2}]}'
    h = Harness(db, storage, tmp_path, "union", classification=answer)
    run_id = h.enqueue(TYPED)
    assert h.execute(run_id) == RunState.SUCCEEDED
    run, best, *_ = _summary(db, run_id)
    assert run.progress_total == 76 and {"rate_card", "sow_number"} <= set(best)
    assert _classifications(db, run_id) == [("msa", "classifier", True, 0.9), ("sow", "classifier", True, 0.8),
                                            ("nda", "classifier", False, 0.2)]


@pytest.mark.parametrize("answer", [
    '{"types": [{"key": "msa", "confidence": 0.3}]}',
    '{"types": [{"key": "other", "confidence": 0.9, "evidence": "a letter"}]}',
    "I am not sure.",
    ProviderError("model crashed"),
])
def test_unsure_or_failed_classification_uses_the_fallback(db, storage, tmp_path, answer):
    h = Harness(db, storage, tmp_path, "unsure", classification=answer)
    run_id = h.enqueue(TYPED)
    assert h.execute(run_id) == RunState.SUCCEEDED
    run, best, _, _, _, _, events = _summary(db, run_id)
    assert run.progress_total == 44, "Other = Core + Commercial + Risk & Liability"
    assert ("other", "fallback", True) in [c[:3] for c in _classifications(db, run_id)]
    assert any(e.startswith("Contract type: Other (fallback") for e in events)


def test_contract_type_override_skips_the_classifier(db, storage, tmp_path):
    h = Harness(db, storage, tmp_path, "override")
    run_id = h.enqueue(RunOptions(contract_types=["nda"], retrievals=["RAG01"], judge=False))
    assert h.execute(run_id) == RunState.SUCCEEDED
    run, best, *_ = _summary(db, run_id)
    assert run.progress_total == 42 and "nda_direction" in best and not h.classifier.calls
    assert _classifications(db, run_id) == [("nda", "override", True, None)]


def test_classification_off_uses_the_fallback(db, storage, tmp_path):
    h = Harness(db, storage, tmp_path, "classify-off")
    run_id = h.enqueue(TYPED, classification_enabled=False, classification_profile=None, classification_prompt=None)
    assert h.execute(run_id) == RunState.SUCCEEDED
    run, *_ = _summary(db, run_id)
    assert run.progress_total == 44 and not h.classifier.calls
    assert _classifications(db, run_id) == [("other", "fallback", True, None)]


def test_min_priority_drops_less_important_fields(db, storage, tmp_path):
    h = Harness(db, storage, tmp_path, "priority")
    run_id = h.enqueue(TYPED, min_priority=Priority.P1)
    assert h.execute(run_id) == RunState.SUCCEEDED
    with db.session() as s:
        snapshot_fields = {f["key"]: f for f in RunRepo(s).get(run_id).config_snapshot["field_set"]["fields"]}
        msa = next(t for t in RunRepo(s).get(run_id).config_snapshot["field_set"]["contract_types"] if t["key"] == "msa")
    expected = {mb["key"] for mb in msa["fields"] if mb["priority"] == "P1"}
    _, best, *_ = _summary(db, run_id)
    assert set(best) == expected and "title" not in best and len(expected) < 66 and set(best) <= set(snapshot_fields)


GROUPED = {"extraction_granularity": Granularity.GROUP, "group_max_fields": 8}


def test_group_extraction_answers_a_batch_per_call(db, storage, tmp_path):
    h = Harness(db, storage, tmp_path, "grouped", answers={"payment_terms": {"due_period": "P30D"}})
    run_id = h.enqueue(RunOptions(retrievals=["RAG01", "RAG03"], judge=False), **GROUPED)
    assert h.execute(run_id) == RunState.SUCCEEDED
    run, best, results, calls, _, _, events = _summary(db, run_id)
    with db.session() as s:
        snap = RunRepo(s).get(run_id).config_snapshot
    batches = next(e for e in events if e.startswith("Extracting 66 fields in "))
    n = int(batches.split(" in ")[1].split()[0])
    assert 66 / 8 <= n < 66, "MSA: core, commercial, risk, covenants, IP & data and its own fields, split at 8"
    assert results == 2 * 66 and run.progress_total == 132
    assert calls == 1 + n, "one classification call, one call per batch; RAG03 reuses RAG01's answers"
    assert best["title"][0] == "Acme Pty Ltd" and best["payment_terms"][0] == {"due_period": "P30D"}
    assert best["liability_cap"][0] is None, "a key the answer leaves out is not found"
    with db.session() as s:
        repo = ResultRepo(s)
        title = next(fr for fr in repo.field_results(run_id) if fr.raw_answer == '{"title": "Acme Pty Ltd"}')
        call = repo.llm_calls(title.id)
        assert len(call) == 1 and call[0].field_result_id is None and "\nDefinitions:\n" in call[0].user_prompt
        assert s.scalar(select(func.count()).select_from(m.LlmCallFieldResult).where(m.LlmCallFieldResult.llm_call_id == call[0].id)) <= 8
    assert snap["extraction_granularity"] == "group"


def test_group_answer_that_is_not_json_fails_the_batch(db, storage, tmp_path):
    h = Harness(db, storage, tmp_path, "grouped-bad", group_text="Sorry, I cannot help with that.")
    run_id = h.enqueue(RunOptions(fields=["title", "payment_terms"], retrievals=["RAG01"]), **GROUPED)
    assert h.execute(run_id) == RunState.SUCCEEDED
    with db.session() as s:
        rows = s.execute(select(m.FieldResult.status, m.FieldResult.error, m.Judgement.verdict).join(m.Judgement)
                         .where(m.FieldResult.run_id == run_id)).all()
    assert [(st, v) for st, _, v in rows] == [("error", "SKIPPED")] * 2
    assert all(e.startswith("Answer is not a JSON object") for _, e, _ in rows)


def test_answers_must_fit_the_field_type(db, storage, tmp_path):
    h = Harness(db, storage, tmp_path, "schema", answers={"document_status": "Executed", "nda_direction": "maybe",
                                                          "trade_secrets_indefinite": "yes"})
    run_id = h.enqueue(RunOptions(fields=["document_status", "nda_direction", "trade_secrets_indefinite"],
                                  retrievals=["RAG01"], judge=False))
    assert h.execute(run_id) == RunState.SUCCEEDED
    with db.session() as s:
        rows = {k: (st, v, e) for k, st, v, e in s.execute(
            select(m.Field.key, m.FieldResult.status, m.FieldResult.value, m.FieldResult.error)
            .join(m.Field).where(m.FieldResult.run_id == run_id))}
    assert rows["document_status"][:2] == ("extracted", "executed"), "enum values are normalised"
    assert rows["nda_direction"][0] == "error" and "'maybe' is not one of" in rows["nda_direction"][2]
    assert rows["trade_secrets_indefinite"][0] == "error" and "expected boolean" in rows["trade_secrets_indefinite"][2]


def test_reuse_can_be_turned_off(db, storage, tmp_path):
    h = Harness(db, storage, tmp_path, "noreuse")
    run_id = h.enqueue(RunOptions(fields=FIELDS, retrievals=["RAG01", "RAG02", "RAG03"], reuse_calls=False))
    assert h.execute(run_id) == RunState.SUCCEEDED
    _, best, results, calls, judgements, _, _ = _summary(db, run_id)
    assert calls == 12 and results == 6 and judgements == 6
    assert best["title"][2] == "PASS"


def test_parallel_judge_matches_sequential(db, storage, tmp_path):
    h = Harness(db, storage, tmp_path, "parallel")
    run_id = h.enqueue(judge_parallel=True)
    assert h.execute(run_id) == RunState.SUCCEEDED
    run, best, results, calls, judgements, _, events = _summary(db, run_id)
    assert (run.progress_done, run.progress_total) == (6, 6)
    assert (results, calls, judgements) == (6, 4, 6)
    assert best["title"] == ("Acme Pty Ltd", "RAG01", "PASS")


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
    assert best["title"] == ("Acme Pty Ltd", "RAG01", None)


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
    assert any(e.startswith("Run cancelled") for e in events)


def test_cancellation_aborts_a_model_call(db, storage, tmp_path, monkeypatch):
    monkeypatch.setattr(executor, "STOP_CHECK_SECONDS", 0)
    holder = {}

    def cancel_during_first(n):
        if n == 1:
            with db.session() as s:
                RunRepo(s).request_cancel(holder["run_id"])

    h = Harness(db, storage, tmp_path, "abort", on_call=cancel_during_first, streams=True)
    holder["run_id"] = run_id = h.enqueue()
    assert h.execute(run_id) == RunState.CANCELLED
    run, _, results, calls, _, _, events = _summary(db, run_id)
    assert len(h.extractor.calls) == 1, "the first call was aborted; no other was made"
    assert (results, calls, run.progress_done) == (0, 0, 0), "an aborted call leaves no result behind"
    assert "Run cancelled: Cancellation requested" in events


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
        original = s.scalar(select(m.Field.user_prompt).where(m.Field.key == "title"))
        s.execute(update(m.Field).where(m.Field.key == "title").values(user_prompt="CHANGED AFTER ENQUEUE"))
    try:
        assert h.execute(run_id) == RunState.SUCCEEDED
        assert not any(c.startswith("CHANGED") for c in h.extractor.calls)
    finally:
        with db.session() as s:
            s.execute(update(m.Field).where(m.Field.key == "title").values(user_prompt=original))


def test_only_queued_runs_execute(db, storage, tmp_path):
    from contract_extraction.core.errors import Conflict

    h = Harness(db, storage, tmp_path, "twice")
    run_id = h.enqueue(RunOptions(fields=["title"], retrievals=["RAG01"]))
    h.execute(run_id)
    with pytest.raises(Conflict):
        h.execute(run_id)
