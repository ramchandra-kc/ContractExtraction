"""Request and response models of the HTTP API (separate from the ORM; no filesystem paths)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from ..domain.enums import RunKind
from ..pipeline.options import RunOptions

T = TypeVar("T")


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# ---- system ------------------------------------------------------------------------------------


class ComponentOut(_Out):
    name: str
    ok: bool
    detail: str


class HealthOut(BaseModel):
    status: str  # "ok" | "degraded"
    components: list[ComponentOut]


# ---- config ------------------------------------------------------------------------------------


class ModelOut(_Out):
    name: str
    kind: str
    context_window: int | None = None
    embedding_dimension: int | None = None


class ProviderOut(_Out):
    key: str
    kind: str
    base_url: str
    api_key_env: str | None
    is_enabled: bool
    models: list[ModelOut]


class RetrievalOut(BaseModel):
    name: str
    top_k: int
    score_threshold: Decimal
    query_expansion: bool
    per_query_top: int
    min_score: Decimal


class FieldOut(BaseModel):
    key: str
    label: str
    description: str | None
    value_type: str
    query_count: int


class ProfileOut(BaseModel):
    name: str
    model: str
    provider: str
    temperature: Decimal


class PipelineOut(BaseModel):
    name: str
    is_default: bool
    description: str | None = None
    # Set when the pipeline cannot be resolved (e.g. a disabled provider); the other fields are then empty.
    error: str | None = None
    decomposition: str | None = None
    index: str | None = None
    embedding_model: str | None = None
    extraction: ProfileOut | None = None
    judge: ProfileOut | None = None
    retrievals: list[RetrievalOut] = []
    fields: list[FieldOut] = []


# ---- documents ---------------------------------------------------------------------------------


class RunSummary(_Out):
    id: uuid.UUID
    document_id: uuid.UUID
    kind: str
    state: str
    stage: str | None
    progress_done: int
    progress_total: int
    error: str | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunOut(RunSummary):
    pipeline: str | None
    options: dict[str, Any]
    worker_id: str | None
    heartbeat_at: datetime | None
    cancel_requested: bool
    attempts: int
    decomposition_id: uuid.UUID | None
    vector_index_id: uuid.UUID | None


class DocumentOut(_Out):
    id: uuid.UUID
    code: str
    title: str | None
    original_filename: str
    mime_type: str
    sha256: str
    size_bytes: int
    page_count: int | None
    tags: list[str]
    created_at: datetime
    latest_run: RunSummary | None = None


class DecompositionOut(BaseModel):
    id: uuid.UUID
    config: str | None
    method: str | None
    text_format: str | None
    page_count: int
    duration_ms: int
    created_at: datetime


class DocumentDetail(DocumentOut):
    decompositions: list[DecompositionOut]
    runs: list[RunSummary]


class ImageOut(BaseModel):
    id: uuid.UUID
    file_name: str
    width: int | None
    height: int | None
    url: str


class PageOut(BaseModel):
    page_number: int
    text: str
    text_format: str
    header: str | None
    footer: str | None
    width: float | None
    height: float | None
    images: list[ImageOut]


class PagesOut(BaseModel):
    decomposition_id: uuid.UUID
    pages: list[PageOut]


# ---- runs --------------------------------------------------------------------------------------


class RunCreate(BaseModel):
    """Queue a run. Narrowing options are applied to the pipeline before its snapshot is stored."""

    model_config = ConfigDict(extra="forbid")

    pipeline: str | None = Field(None, description="Pipeline config name; default pipeline when omitted")
    kind: RunKind = RunKind.FULL
    fields: list[str] | None = Field(None, description="Field keys to extract (default: all)")
    retrievals: list[str] | None = Field(None, description="RAG config names (default: all of the pipeline)")
    judge: bool | None = Field(None, description="false skips the judge for this run")
    reuse_calls: bool = True
    redecompose: bool = False

    def options(self) -> RunOptions:
        return RunOptions(fields=self.fields, retrievals=self.retrievals, judge=self.judge,
                          reuse_calls=self.reuse_calls, redecompose=self.redecompose)


class EventOut(_Out):
    id: int
    created_at: datetime
    level: str
    stage: str | None
    message: str
    data: dict[str, Any]


class BestValue(BaseModel):
    field_id: uuid.UUID
    field_key: str
    field_label: str
    value_type: str
    value: Any
    status: str
    retrieval_config: str
    verdict: str | None
    issue: str | None
    explanation: str | None
    field_result_id: uuid.UUID
    expected_value: Any = Field(None, description="Ground truth for the document and field; null when unlabelled")
    exact_match: bool | None = Field(None, description="Best value equals the ground truth; null when unlabelled")


class EvaluationOut(BaseModel):
    """Best values compared with the ground truth (matching is defined in v_run_evaluation)."""

    fields: int
    labelled: int
    matched: int


class FieldResultOut(BaseModel):
    id: uuid.UUID
    field_key: str
    field_label: str
    retrieval_config: str
    status: str
    value: Any
    error: str | None
    extraction_ms: int | None
    verdict: str | None
    issue: str | None
    created_at: datetime


class RunResults(BaseModel):
    run: RunOut
    best: list[BestValue]
    evaluation: EvaluationOut
    results: list[FieldResultOut]


class HitOut(BaseModel):
    rank: int
    score: float
    page: int
    matched_query: str | None
    chunk_id: uuid.UUID
    text: str


class LlmCallOut(_Out):
    id: uuid.UUID
    purpose: str
    provider_key: str
    model_name: str
    params: dict[str, Any]
    system_prompt: str | None
    user_prompt: str | None
    response: str | None
    status: str
    error: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int | None
    cost_usd: Decimal | None
    created_at: datetime


class JudgementOut(_Out):
    verdict: str
    issue: str | None
    explanation: str | None
    llm_call_id: uuid.UUID | None
    created_at: datetime


class FieldResultDetail(FieldResultOut):
    raw_answer: str | None
    reused_from: uuid.UUID | None
    hits: list[HitOut]
    llm_calls: list[LlmCallOut]
    judgements: list[JudgementOut]


# ---- ground truth ------------------------------------------------------------------------------


class FieldSetRef(BaseModel):
    id: uuid.UUID
    name: str
    version: int


class GroundTruthItem(BaseModel):
    field_id: uuid.UUID
    field_key: str
    field_label: str
    value_type: str
    expected_value: Any = Field(None, description='The label; null when unlabelled, "" when not in this contract')
    notes: str | None = None
    updated_at: datetime | None = None


class GroundTruthOut(BaseModel):
    field_set: FieldSetRef
    items: list[GroundTruthItem]


class GroundTruthSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_value: Any = Field(description='Any JSON value except null; "" means not in this contract')
    notes: str | None = None
