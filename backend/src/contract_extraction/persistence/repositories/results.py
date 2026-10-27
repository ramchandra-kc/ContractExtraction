"""Extraction results: field results with their evidence, LLM calls and judgements."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session, selectinload

from ...core.errors import NotFound
from ...domain.config import ModelProfile
from ...domain.enums import ClassificationSource, FieldResultStatus, JudgeIssue, LlmCallPurpose, LlmCallStatus, Verdict
from ...extraction.retrieval import Hit
from ...providers.base import ChatResult
from .. import models as m

_MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Outcome:
    result: m.FieldResult
    field: m.Field
    retrieval_config: str
    judgement: m.Judgement | None


def call_cost(profile: ModelProfile, result: ChatResult) -> Decimal | None:
    """USD cost from the model's prices; None when prices or token counts are unknown."""
    model = profile.model
    if model.input_cost_per_mtok is None and model.output_cost_per_mtok is None:
        return None
    if result.prompt_tokens is None and result.completion_tokens is None:
        return None
    cost = (Decimal(result.prompt_tokens or 0) * (model.input_cost_per_mtok or 0)
            + Decimal(result.completion_tokens or 0) * (model.output_cost_per_mtok or 0)) / _MILLION
    return cost.quantize(Decimal("0.000001"))


class ResultRepo:
    def __init__(self, session: Session):
        self.session = session

    def add_field_result(self, run_id: uuid.UUID, field_id: uuid.UUID, retrieval_config_id: uuid.UUID,
                         status: FieldResultStatus, value: Any, raw_answer: str | None, error: str | None,
                         extraction_ms: int | None, hits: list[Hit]) -> uuid.UUID:
        row = m.FieldResult(id=uuid.uuid4(), run_id=run_id, field_id=field_id, retrieval_config_id=retrieval_config_id,
                            status=status, value=value, raw_answer=raw_answer, error=error, extraction_ms=extraction_ms)
        self.session.add(row)
        self.session.flush()
        self.session.add_all(
            m.RetrievalHit(field_result_id=row.id, rank=rank, chunk_id=h.chunk_id, score=h.score, matched_query=h.matched_query,
                           keyword_score=h.keyword_score, source=h.source)
            for rank, h in enumerate(hits, start=1)
        )
        self.session.flush()
        return row.id

    def add_llm_call(self, *, run_id: uuid.UUID, field_result_id: uuid.UUID | None, purpose: LlmCallPurpose,
                     profile: ModelProfile, system_prompt: str, user_prompt: str, result: ChatResult | None,
                     error: str | None = None, timeout: bool = False) -> uuid.UUID:
        status = LlmCallStatus.OK if result is not None else (LlmCallStatus.TIMEOUT if timeout else LlmCallStatus.ERROR)
        row = m.LlmCall(
            id=uuid.uuid4(), run_id=run_id, field_result_id=field_result_id, purpose=purpose,
            model_profile_id=profile.id, provider_key=profile.model.provider.key, model_name=profile.model.name,
            params=result.params if result else {}, system_prompt=system_prompt, user_prompt=user_prompt,
            response=result.text if result else None, status=status, error=error,
            prompt_tokens=result.prompt_tokens if result else None,
            completion_tokens=result.completion_tokens if result else None,
            latency_ms=result.latency_ms if result else None,
            cost_usd=call_cost(profile, result) if result else None,
        )
        self.session.add(row)
        self.session.flush()
        return row.id

    def add_judgement(self, field_result_id: uuid.UUID, verdict: Verdict, issue: JudgeIssue | None,
                      explanation: str, profile_id: uuid.UUID | None, llm_call_id: uuid.UUID | None) -> uuid.UUID:
        row = m.Judgement(id=uuid.uuid4(), field_result_id=field_result_id, model_profile_id=profile_id, verdict=verdict,
                          issue=issue, explanation=explanation, llm_call_id=llm_call_id)
        self.session.add(row)
        self.session.flush()
        return row.id

    def add_classification(self, run_id: uuid.UUID, contract_type_id: uuid.UUID, source: ClassificationSource,
                           selected: bool, confidence: Decimal | None = None, evidence: str | None = None,
                           llm_call_id: uuid.UUID | None = None) -> None:
        self.session.add(m.RunClassification(run_id=run_id, contract_type_id=contract_type_id, source=source,
                                             selected=selected, confidence=confidence, evidence=evidence,
                                             llm_call_id=llm_call_id))
        self.session.flush()

    def classifications(self, run_id: uuid.UUID) -> Sequence[m.RunClassification]:
        """Contract types considered for the run: selected first, then by confidence."""
        return self.session.scalars(
            select(m.RunClassification).options(selectinload(m.RunClassification.contract_type))
            .where(m.RunClassification.run_id == run_id)
            .order_by(m.RunClassification.selected.desc(), m.RunClassification.confidence.desc().nulls_last(),
                      m.RunClassification.created_at)
        ).all()

    def field_results(self, run_id: uuid.UUID) -> Sequence[m.FieldResult]:
        return self.session.scalars(
            select(m.FieldResult).where(m.FieldResult.run_id == run_id).order_by(m.FieldResult.created_at)
        ).all()

    def outcomes(self, run_id: uuid.UUID) -> list[Outcome]:
        """Every field result of the run with its field, RAG config and latest verdict."""
        rows = self.session.execute(
            select(m.FieldResult, m.Field, m.RetrievalConfig.name)
            .join(m.Field, m.Field.id == m.FieldResult.field_id)
            .join(m.RetrievalConfig, m.RetrievalConfig.id == m.FieldResult.retrieval_config_id)
            .where(m.FieldResult.run_id == run_id).order_by(m.FieldResult.created_at)
        ).all()
        latest = self.latest_judgements([fr.id for fr, _, _ in rows])
        return [Outcome(fr, f, rc_name, latest.get(fr.id)) for fr, f, rc_name in rows]

    def latest_judgements(self, field_result_ids: list[uuid.UUID]) -> dict[uuid.UUID, m.Judgement]:
        if not field_result_ids:
            return {}
        rows = self.session.scalars(
            select(m.Judgement).where(m.Judgement.field_result_id.in_(field_result_ids))
            .ext(distinct_on(m.Judgement.field_result_id))
            .order_by(m.Judgement.field_result_id, m.Judgement.created_at.desc())
        ).all()
        return {j.field_result_id: j for j in rows}

    def outcome(self, run_id: uuid.UUID, field_result_id: uuid.UUID) -> Outcome:
        for o in self.outcomes(run_id):
            if o.result.id == field_result_id:
                return o
        raise NotFound(f"Field result {field_result_id} not found in run {run_id}")

    def evidence(self, field_result_id: uuid.UUID) -> list[tuple[m.RetrievalHit, m.Chunk]]:
        return list(self.session.execute(
            select(m.RetrievalHit, m.Chunk).join(m.Chunk, m.Chunk.id == m.RetrievalHit.chunk_id)
            .where(m.RetrievalHit.field_result_id == field_result_id).order_by(m.RetrievalHit.rank)
        ).all())

    def judgements(self, field_result_id: uuid.UUID) -> Sequence[m.Judgement]:
        return self.session.scalars(select(m.Judgement).where(m.Judgement.field_result_id == field_result_id)
                                    .order_by(m.Judgement.created_at)).all()

    def link_call(self, llm_call_id: uuid.UUID, field_result_ids: list[uuid.UUID]) -> None:
        """Record that one call (group extraction) produced several field results."""
        self.session.add_all(m.LlmCallFieldResult(llm_call_id=llm_call_id, field_result_id=fr) for fr in field_result_ids)
        self.session.flush()

    def llm_calls(self, field_result_id: uuid.UUID) -> list[m.LlmCall]:
        """Calls that produced this result: its own, and a group call it shares with other fields.
        A reused result made no calls of its own: the calls of the result it was reused from are
        returned instead (found through the reuse event)."""
        source = self.reused_from(field_result_id) or field_result_id
        shared = select(m.LlmCallFieldResult.llm_call_id).where(m.LlmCallFieldResult.field_result_id == source)
        return list(self.session.scalars(
            select(m.LlmCall).where(or_(m.LlmCall.field_result_id == source, m.LlmCall.id.in_(shared)))
            .order_by(m.LlmCall.created_at)))

    def reused_from(self, field_result_id: uuid.UUID) -> uuid.UUID | None:
        value = self.session.scalar(
            select(m.RunEvent.data["reused_from"].astext)
            .where(m.RunEvent.data["field_result_id"].astext == str(field_result_id)).limit(1))
        return uuid.UUID(value) if value else None

    def best_values(self, run_id: uuid.UUID) -> Sequence[RowMapping]:
        """Best value per field with its ground truth: ``expected_value`` (None when unlabelled) and
        ``exact_match`` (None when unlabelled), both from v_run_evaluation."""
        return self.best_values_for_runs([run_id])

    def best_values_for_runs(self, run_ids: list[uuid.UUID]) -> Sequence[RowMapping]:
        """``best_values`` of several runs, by run and field position."""
        bv, ev, gt = m.best_values, m.run_evaluation, m.GroundTruth
        return self.session.execute(
            select(bv, m.Field.position, m.Field.value_type, ev.c.expected_value, ev.c.exact_match,
                   gt.notes.label("label_notes"))
            .join(m.Field, m.Field.id == bv.c.field_id)
            .join(ev, and_(ev.c.run_id == bv.c.run_id, ev.c.field_id == bv.c.field_id))
            .outerjoin(gt, and_(gt.document_id == bv.c.document_id, gt.field_id == bv.c.field_id))
            .where(bv.c.run_id.in_(run_ids)).order_by(bv.c.run_id, m.Field.position)
        ).mappings().all()

    def outcomes_for_runs(self, run_ids: list[uuid.UUID]) -> Sequence[RowMapping]:
        """Every outcome of several runs (run × RAG config × field), with its latest verdict, label, label notes and
        exact match computed as in ``v_run_evaluation``; by run, field position and RAG config."""
        fr, gt, rc = m.FieldResult, m.GroundTruth, m.RetrievalConfig
        verdict = (select(m.Judgement.verdict).where(m.Judgement.field_result_id == fr.id)
                   .order_by(m.Judgement.created_at.desc()).limit(1).scalar_subquery())
        structured = func.jsonb_typeof(gt.expected_value).in_(["object", "array"])
        text = lambda j: func.lower(func.btrim(func.coalesce(j.op("#>>")(literal_column("'{}'::text[]")), "")))  # noqa: E731
        exact = case(
            (gt.id.is_(None), None),
            (fr.status == FieldResultStatus.ERROR, False),
            (structured, func.coalesce(func.jsonb_strip_empty(fr.value) == func.jsonb_strip_empty(gt.expected_value), False)),
            else_=text(fr.value) == text(gt.expected_value))
        return self.session.execute(
            select(fr.id.label("field_result_id"), fr.run_id, m.Run.document_id, m.Run.vector_index_id, fr.field_id,
                   m.Field.key.label("field_key"), m.Field.value_type, rc.name.label("retrieval_config"), fr.status,
                   fr.value, verdict.label("verdict"), gt.expected_value, gt.notes.label("label_notes"),
                   exact.label("exact_match"))
            .join(m.Run, m.Run.id == fr.run_id).join(m.Field, m.Field.id == fr.field_id).join(rc, rc.id == fr.retrieval_config_id)
            .outerjoin(gt, and_(gt.document_id == m.Run.document_id, gt.field_id == fr.field_id))
            .where(fr.run_id.in_(run_ids)).order_by(fr.run_id, m.Field.position, rc.name)
        ).mappings().all()

    def hits_for_results(self, field_result_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[tuple[int, uuid.UUID]]]:
        """Per field result: its evidence as (rank, chunk id), best rank first."""
        h = m.RetrievalHit
        out: dict[uuid.UUID, list[tuple[int, uuid.UUID]]] = {}
        for i in range(0, len(field_result_ids), 5000):
            rows = self.session.execute(select(h.field_result_id, h.rank, h.chunk_id)
                                        .where(h.field_result_id.in_(field_result_ids[i:i + 5000]))
                                        .order_by(h.field_result_id, h.rank)).all()
            for fid, rank, chunk_id in rows:
                out.setdefault(fid, []).append((rank, chunk_id))
        return out

    def chunk_texts(self, vector_index_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[uuid.UUID, str]]:
        """Per vector index: every chunk's text by chunk id."""
        c = m.Chunk
        out: dict[uuid.UUID, dict[uuid.UUID, str]] = {}
        for index_id, chunk_id, text in self.session.execute(
                select(c.vector_index_id, c.id, c.text).where(c.vector_index_id.in_(vector_index_ids))):
            out.setdefault(index_id, {})[chunk_id] = text
        return out

    def call_totals(self, run_ids: list[uuid.UUID]) -> dict[uuid.UUID, RowMapping]:
        """Per run: LLM calls, prompt and completion tokens, cost (USD) and mean latency (ms)."""
        c = m.LlmCall
        rows = self.session.execute(
            select(c.run_id, func.count().label("calls"),
                   func.coalesce(func.sum(c.prompt_tokens), 0).label("prompt_tokens"),
                   func.coalesce(func.sum(c.completion_tokens), 0).label("completion_tokens"),
                   func.sum(c.cost_usd).label("cost_usd"), func.avg(c.latency_ms).label("mean_latency_ms"))
            .where(c.run_id.in_(run_ids)).group_by(c.run_id)
        ).mappings().all()
        return {r["run_id"]: r for r in rows}
