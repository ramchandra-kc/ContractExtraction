"""Extraction results: field results with their evidence, LLM calls and judgements."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from ...domain.config import ModelProfile
from ...domain.enums import FieldResultStatus, JudgeIssue, LlmCallPurpose, LlmCallStatus, Verdict
from ...extraction.retrieval import Hit
from ...providers.base import ChatResult
from .. import models as m

_MILLION = Decimal(1_000_000)


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

    def best_values(self, run_id: uuid.UUID) -> Sequence[RowMapping]:
        bv = m.best_values
        return self.session.execute(
            select(bv, m.Field.position).join(m.Field, m.Field.id == bv.c.field_id)
            .where(bv.c.run_id == run_id).order_by(m.Field.position)
        ).mappings().all()
