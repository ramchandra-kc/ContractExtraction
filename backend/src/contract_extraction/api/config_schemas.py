"""Request and response models for reading and editing configuration (``/config/catalog`` and the writes).

Input bounds mirror the CHECK constraints in docker/schema.sql, so bad input gets per-field 422 errors;
the database stays the backstop. Patch models apply only the keys that are sent: ``null`` clears a
nullable column, and is rejected (422) for a required one, whose type is not optional.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domain.enums import DecompositionMethod, Distance, ModelKind, PromptRole, TextFormat, ValueType, VectorStore

Name = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
                            description="Letters, digits, '.', '_' and '-'; cannot be changed later")]
Score = Annotated[Decimal, Field(ge=0, le=1, max_digits=4, decimal_places=3)]
Positive = Annotated[int, Field(gt=0)]
Cost = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=6)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VersionRef(BaseModel):
    name: str
    version: int


# ---- catalog (read) -------------------------------------------------------------------------------


class CatalogModel(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    context_window: int | None
    embedding_dimension: int | None
    input_cost_per_mtok: Decimal | None
    output_cost_per_mtok: Decimal | None
    is_enabled: bool


class CatalogProvider(BaseModel):
    key: str
    kind: str
    base_url: str
    api_key_env: str | None
    is_enabled: bool
    models: list[CatalogModel]


class CatalogProfile(BaseModel):
    name: str
    description: str | None
    model_id: uuid.UUID
    model: str
    provider: str
    temperature: Decimal
    top_p: Decimal | None
    top_k: int | None
    max_tokens: int | None
    num_ctx: int | None
    json_mode: bool
    timeout_seconds: int


class CatalogPrompt(BaseModel):
    name: str
    version: int
    role: str
    body: str
    notes: str | None
    is_active: bool
    created_at: datetime


class CatalogDecomposition(BaseModel):
    name: str
    description: str | None
    method: str
    text_format: str
    keep_invisible_text: bool
    remove_headers_footers: bool
    ocr_language: str
    dpi: int


class CatalogIndex(BaseModel):
    name: str
    description: str | None
    embedding_model_id: uuid.UUID
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    vector_store: str
    distance: str
    batch_size: int


class CatalogRetrieval(BaseModel):
    name: str
    description: str | None
    top_k: int
    score_threshold: Decimal
    query_expansion: bool
    per_query_top: int
    min_score: Decimal


class CatalogField(BaseModel):
    id: uuid.UUID
    key: str
    label: str
    description: str | None
    value_type: str
    user_prompt: str
    position: int
    is_enabled: bool
    queries: list[str]


class CatalogFieldSet(BaseModel):
    name: str
    version: int
    description: str | None
    fields: list[CatalogField]


class CatalogPipeline(BaseModel):
    name: str
    description: str | None
    is_default: bool
    decomposition: str
    index: str
    field_set: VersionRef
    extraction_profile: str
    extraction_prompt: VersionRef
    judge_enabled: bool
    judge_profile: str | None
    judge_prompt: VersionRef | None
    judge_parallel: bool
    retrievals: list[str] = Field(description="RAG config names in priority order")
    error: str | None = Field(None, description="Why the pipeline cannot run right now, if it cannot")


class Catalog(BaseModel):
    providers: list[CatalogProvider]
    profiles: list[CatalogProfile]
    prompts: list[CatalogPrompt]
    decompositions: list[CatalogDecomposition]
    indexes: list[CatalogIndex]
    retrievals: list[CatalogRetrieval]
    field_sets: list[CatalogFieldSet]
    pipelines: list[CatalogPipeline]


# ---- pipelines ------------------------------------------------------------------------------------


class PipelineCreate(_In):
    name: Name
    description: str | None = None
    decomposition: str
    index: str
    field_set: VersionRef
    extraction_profile: str
    extraction_prompt: VersionRef
    judge_enabled: bool = True
    judge_profile: str | None = None
    judge_prompt: VersionRef | None = None
    judge_parallel: bool = False
    retrievals: list[str] = Field(min_length=1, description="RAG config names in priority order")

    @model_validator(mode="after")
    def _judge(self) -> PipelineCreate:
        if self.judge_enabled and (self.judge_profile is None or self.judge_prompt is None):
            raise ValueError("judge_profile and judge_prompt are required when judge_enabled is true")
        return self


class PipelineUpdate(_In):
    description: str | None = None
    decomposition: str = None  # type: ignore[assignment]
    index: str = None  # type: ignore[assignment]
    field_set: VersionRef = None  # type: ignore[assignment]
    extraction_profile: str = None  # type: ignore[assignment]
    extraction_prompt: VersionRef = None  # type: ignore[assignment]
    judge_enabled: bool = None  # type: ignore[assignment]
    judge_profile: str | None = None
    judge_prompt: VersionRef | None = None
    judge_parallel: bool = None  # type: ignore[assignment]
    retrievals: list[str] = Field(None, min_length=1)  # type: ignore[assignment]


# ---- RAG configs ----------------------------------------------------------------------------------


class RetrievalCreate(_In):
    name: Name
    description: str | None = None
    top_k: Positive
    score_threshold: Score
    query_expansion: bool = True
    per_query_top: Positive = 3
    min_score: Score = Decimal("0.30")


class RetrievalUpdate(_In):
    description: str | None = None
    top_k: Positive = None  # type: ignore[assignment]
    score_threshold: Score = None  # type: ignore[assignment]
    query_expansion: bool = None  # type: ignore[assignment]
    per_query_top: Positive = None  # type: ignore[assignment]
    min_score: Score = None  # type: ignore[assignment]


# ---- model profiles -------------------------------------------------------------------------------


class ProfileCreate(_In):
    name: Name
    description: str | None = None
    model_id: uuid.UUID
    temperature: Annotated[Decimal, Field(ge=0, le=2, max_digits=4, decimal_places=3)] = Decimal("0.2")
    top_p: Score | None = None
    top_k: Positive | None = None
    max_tokens: Positive | None = None
    num_ctx: Positive | None = None
    json_mode: bool = True
    timeout_seconds: Positive = 600


class ProfileUpdate(_In):
    description: str | None = None
    model_id: uuid.UUID = None  # type: ignore[assignment]
    temperature: Annotated[Decimal, Field(ge=0, le=2, max_digits=4, decimal_places=3)] = None  # type: ignore[assignment]
    top_p: Score | None = None
    top_k: Positive | None = None
    max_tokens: Positive | None = None
    num_ctx: Positive | None = None
    json_mode: bool = None  # type: ignore[assignment]
    timeout_seconds: Positive = None  # type: ignore[assignment]


# ---- decomposition and index configs (create-only) ------------------------------------------------


class DecompositionCreate(_In):
    name: Name
    description: str | None = None
    method: DecompositionMethod = DecompositionMethod.PYMUPDF
    text_format: TextFormat = TextFormat.MD
    keep_invisible_text: bool = True
    remove_headers_footers: bool = True
    ocr_language: str = Field("eng", min_length=1)
    dpi: Annotated[int, Field(ge=72, le=1200)] = 200


class IndexCreate(_In):
    name: Name
    description: str | None = None
    embedding_model_id: uuid.UUID
    chunk_size: Positive = 2000
    chunk_overlap: Annotated[int, Field(ge=0)] = 300
    vector_store: VectorStore = VectorStore.QDRANT
    distance: Distance = Distance.COSINE
    batch_size: Positive = 32

    @model_validator(mode="after")
    def _overlap(self) -> IndexCreate:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


# ---- prompts --------------------------------------------------------------------------------------


class PromptCreate(_In):
    name: Name
    role: PromptRole
    body: str = Field(min_length=1)
    notes: str | None = None


class PromptVersionCreate(_In):
    body: str = Field(min_length=1)
    notes: str | None = None


# ---- fields ---------------------------------------------------------------------------------------


class FieldCreate(_In):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100, description="Cannot be changed later")
    label: str = Field(min_length=1)
    description: str | None = None
    value_type: ValueType = ValueType.TEXT
    user_prompt: str = Field(min_length=1)
    is_enabled: bool = True
    queries: list[str] = Field([], description="Expansion queries in order; blank ones are dropped")


class FieldUpdate(_In):
    label: str = Field(None, min_length=1)  # type: ignore[assignment]
    description: str | None = None
    value_type: ValueType = None  # type: ignore[assignment]
    user_prompt: str = Field(None, min_length=1)  # type: ignore[assignment]
    is_enabled: bool = None  # type: ignore[assignment]
    queries: list[str] = None  # type: ignore[assignment]


# ---- providers and models -------------------------------------------------------------------------


class ProviderUpdate(_In):
    base_url: str = Field(None, min_length=1)  # type: ignore[assignment]
    is_enabled: bool = None  # type: ignore[assignment]


class ModelCreate(_In):
    name: str = Field(min_length=1, max_length=200)
    kind: ModelKind
    context_window: Positive | None = None
    embedding_dimension: Positive | None = None
    input_cost_per_mtok: Cost | None = None
    output_cost_per_mtok: Cost | None = None

    @model_validator(mode="after")
    def _dimension(self) -> ModelCreate:
        if (self.kind == ModelKind.EMBEDDING) != (self.embedding_dimension is not None):
            raise ValueError("embedding_dimension is required for embedding models and only for them")
        return self


class ModelUpdate(_In):
    is_enabled: bool = None  # type: ignore[assignment]
    context_window: Positive | None = None
    input_cost_per_mtok: Cost | None = None
    output_cost_per_mtok: Cost | None = None
