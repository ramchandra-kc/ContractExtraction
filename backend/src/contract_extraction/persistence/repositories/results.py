"""Extraction results: field results with their evidence, LLM calls and judgements."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from ...core.errors import NotFound
from ...domain.config import ModelProfile
from ...domain.enums import FieldResultStatus, JudgeIssue, LlmCallPurpose, LlmCallStatus, Verdict
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
            m.RetrievalHit(field_result_id=row.id, rank=rank, chunk_id=h.chunk_id, score=h.score, matched_query=h.matched_query)
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

    def llm_calls(self, field_result_id: uuid.UUID) -> list[m.LlmCall]:
        """Calls that produced this result. A reused result made no calls of its own: the calls of the
        result it was reused from are returned instead (found through the reuse event)."""
        source = self.reused_from(field_result_id) or field_result_id
        calls = list(self.session.scalars(select(m.LlmCall).where(m.LlmCall.field_result_id == source)
                                          .order_by(m.LlmCall.created_at)))
        return calls

    def reused_from(self, field_result_id: uuid.UUID) -> uuid.UUID | None:
        value = self.session.scalar(
            select(m.RunEvent.data["reused_from"].astext)
            .where(m.RunEvent.data["field_result_id"].astext == str(field_result_id)).limit(1))
        return uuid.UUID(value) if value else None

    def best_values(self, run_id: uuid.UUID) -> Sequence[RowMapping]:
        bv = m.best_values
        return self.session.execute(
            select(bv, m.Field.position).join(m.Field, m.Field.id == bv.c.field_id)
            .where(bv.c.run_id == run_id).order_by(m.Field.position)
        ).mappings().all()
