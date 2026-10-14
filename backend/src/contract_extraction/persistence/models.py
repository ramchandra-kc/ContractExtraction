"""SQLAlchemy models mirroring docker/schema.sql.

The SQL file is the source of truth; this module never creates tables. Keep the two in
sync: ``tests/test_schema_matches_orm.py`` fails when tables, columns, types,
nullability, foreign keys or unique constraints differ.

Columns that the database fills (defaults, generated values, ``updated_at`` triggers) are
marked with ``FetchedValue`` so the ORM omits them on INSERT and reads them back.
CHECK constraints live only in SQL; ``domain.enums`` mirrors their allowed values.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    REAL,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Double,
    FetchedValue,
    ForeignKey,
    Identity,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    type_annotation_map = {
        uuid.UUID: Uuid,
        str: Text,
        int: Integer,
        bool: Boolean,
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
    }


def _db() -> FetchedValue:
    """Value supplied by the database (DEFAULT, generated column)."""
    return FetchedValue()


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4, server_default=_db())


def _created() -> Mapped[datetime]:
    return mapped_column(server_default=_db())


def _updated() -> Mapped[datetime]:
    return mapped_column(server_default=_db(), server_onupdate=_db())


def _json() -> Mapped[dict[str, Any]]:
    return mapped_column(server_default=_db())


# =====================================================================================================
# 1. Model & RAG configuration
# =====================================================================================================


class LlmProvider(Base):
    __tablename__ = "llm_providers"

    id: Mapped[uuid.UUID] = _pk()
    key: Mapped[str] = mapped_column(unique=True)
    kind: Mapped[str]
    base_url: Mapped[str]
    api_key_env: Mapped[str | None]
    is_enabled: Mapped[bool] = mapped_column(server_default=_db())
    settings: Mapped[dict[str, Any]] = _json()
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    models: Mapped[list[LlmModel]] = relationship(back_populates="provider")


class LlmModel(Base):
    __tablename__ = "llm_models"
    __table_args__ = (UniqueConstraint("provider_id", "name", "kind"),)

    id: Mapped[uuid.UUID] = _pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("llm_providers.id"))
    name: Mapped[str]
    kind: Mapped[str]
    context_window: Mapped[int | None]
    embedding_dimension: Mapped[int | None]
    input_cost_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    output_cost_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    is_enabled: Mapped[bool] = mapped_column(server_default=_db())
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    provider: Mapped[LlmProvider] = relationship(back_populates="models")


class ModelProfile(Base):
    __tablename__ = "model_profiles"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None]
    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("llm_models.id"))
    temperature: Mapped[Decimal] = mapped_column(Numeric(4, 3), server_default=_db())
    top_p: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    top_k: Mapped[int | None]
    max_tokens: Mapped[int | None]
    num_ctx: Mapped[int | None]
    json_mode: Mapped[bool] = mapped_column(server_default=_db())
    timeout_seconds: Mapped[int] = mapped_column(server_default=_db())
    extra: Mapped[dict[str, Any]] = _json()
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    model: Mapped[LlmModel] = relationship()


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (UniqueConstraint("name", "version"),)

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str]
    version: Mapped[int]
    role: Mapped[str]
    body: Mapped[str]
    notes: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(server_default=_db())
    created_at: Mapped[datetime] = _created()


class DecompositionConfig(Base):
    __tablename__ = "decomposition_configs"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None]
    method: Mapped[str] = mapped_column(server_default=_db())
    text_format: Mapped[str] = mapped_column(server_default=_db())
    keep_invisible_text: Mapped[bool] = mapped_column(server_default=_db())
    remove_headers_footers: Mapped[bool] = mapped_column(server_default=_db())
    ocr_language: Mapped[str] = mapped_column(server_default=_db())
    dpi: Mapped[int] = mapped_column(server_default=_db())
    caption_profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_profiles.id"))
    options: Mapped[dict[str, Any]] = _json()
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    caption_profile: Mapped[ModelProfile | None] = relationship()


class IndexConfig(Base):
    __tablename__ = "index_configs"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None]
    embedding_model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("llm_models.id"))
    chunk_size: Mapped[int] = mapped_column(server_default=_db())
    chunk_overlap: Mapped[int] = mapped_column(server_default=_db())
    vector_store: Mapped[str] = mapped_column(server_default=_db())
    distance: Mapped[str] = mapped_column(server_default=_db())
    batch_size: Mapped[int] = mapped_column(server_default=_db())
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    embedding_model: Mapped[LlmModel] = relationship()


class RetrievalConfig(Base):
    __tablename__ = "retrieval_configs"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None]
    top_k: Mapped[int]
    score_threshold: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    query_expansion: Mapped[bool] = mapped_column(server_default=_db())
    per_query_top: Mapped[int] = mapped_column(server_default=_db())
    min_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), server_default=_db())
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class FieldSet(Base):
    __tablename__ = "field_sets"
    __table_args__ = (UniqueConstraint("name", "version"),)

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str]
    version: Mapped[int]
    description: Mapped[str | None]
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    fields: Mapped[list[Field]] = relationship(back_populates="field_set", order_by="Field.position")


class Field(Base):
    __tablename__ = "fields"
    __table_args__ = (UniqueConstraint("field_set_id", "key"), UniqueConstraint("field_set_id", "position"))

    id: Mapped[uuid.UUID] = _pk()
    field_set_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("field_sets.id", ondelete="CASCADE"))
    key: Mapped[str]
    label: Mapped[str]
    description: Mapped[str | None]
    value_type: Mapped[str] = mapped_column(server_default=_db())
    user_prompt: Mapped[str]
    position: Mapped[int]
    is_enabled: Mapped[bool] = mapped_column(server_default=_db())
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    field_set: Mapped[FieldSet] = relationship(back_populates="fields")
    queries: Mapped[list[FieldQuery]] = relationship(order_by="FieldQuery.position")


class FieldQuery(Base):
    __tablename__ = "field_queries"
    __table_args__ = (UniqueConstraint("field_id", "position"),)

    id: Mapped[uuid.UUID] = _pk()
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"))
    position: Mapped[int]
    query: Mapped[str]


class PipelineConfig(Base):
    __tablename__ = "pipeline_configs"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None]
    decomposition_config_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decomposition_configs.id"))
    index_config_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("index_configs.id"))
    field_set_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("field_sets.id"))
    extraction_profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_profiles.id"))
    extraction_prompt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("prompt_templates.id"))
    judge_enabled: Mapped[bool] = mapped_column(server_default=_db())
    judge_profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_profiles.id"))
    judge_prompt_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("prompt_templates.id"))
    judge_parallel: Mapped[bool] = mapped_column(server_default=_db())
    is_default: Mapped[bool] = mapped_column(server_default=_db())
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    decomposition_config: Mapped[DecompositionConfig] = relationship()
    index_config: Mapped[IndexConfig] = relationship()
    field_set: Mapped[FieldSet] = relationship()
    extraction_profile: Mapped[ModelProfile] = relationship(foreign_keys=[extraction_profile_id])
    extraction_prompt: Mapped[PromptTemplate] = relationship(foreign_keys=[extraction_prompt_id])
    judge_profile: Mapped[ModelProfile | None] = relationship(foreign_keys=[judge_profile_id])
    judge_prompt: Mapped[PromptTemplate | None] = relationship(foreign_keys=[judge_prompt_id])
    retrievals: Mapped[list[PipelineConfigRetrieval]] = relationship(
        order_by="PipelineConfigRetrieval.position", cascade="all, delete-orphan")


class PipelineConfigRetrieval(Base):
    __tablename__ = "pipeline_config_retrievals"
    __table_args__ = (UniqueConstraint("pipeline_config_id", "position"),)

    pipeline_config_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_configs.id", ondelete="CASCADE"), primary_key=True)
    retrieval_config_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retrieval_configs.id"), primary_key=True)
    position: Mapped[int]

    retrieval_config: Mapped[RetrievalConfig] = relationship()


# =====================================================================================================
# 2. Documents & artifacts
# =====================================================================================================


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _pk()
    code: Mapped[str] = mapped_column(unique=True, server_default=_db())
    title: Mapped[str | None]
    original_filename: Mapped[str]
    mime_type: Mapped[str] = mapped_column(server_default=_db())
    sha256: Mapped[str] = mapped_column(CHAR(64), unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    page_count: Mapped[int | None]
    storage_path: Mapped[str]
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=_db())
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default=_db())
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Decomposition(Base):
    __tablename__ = "decompositions"

    id: Mapped[uuid.UUID] = _pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    decomposition_config_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decomposition_configs.id"))
    config_snapshot: Mapped[dict[str, Any]] = _json()
    storage_dir: Mapped[str]
    page_count: Mapped[int]
    duration_ms: Mapped[int]
    created_at: Mapped[datetime] = _created()


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("decomposition_id", "page_number"),)

    id: Mapped[uuid.UUID] = _pk()
    decomposition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decompositions.id", ondelete="CASCADE"))
    page_number: Mapped[int]
    text: Mapped[str]
    text_format: Mapped[str]
    header: Mapped[str | None]
    footer: Mapped[str | None]
    width: Mapped[float | None] = mapped_column(REAL)
    height: Mapped[float | None] = mapped_column(REAL)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default=_db())
    # Generated by the database; never written.
    search: Mapped[Any | None] = mapped_column(TSVECTOR, server_default=_db(), server_onupdate=_db(), deferred=True)


class PageImage(Base):
    __tablename__ = "page_images"
    __table_args__ = (UniqueConstraint("page_id", "file_name"),)

    id: Mapped[uuid.UUID] = _pk()
    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"))
    file_name: Mapped[str]
    storage_path: Mapped[str]
    width: Mapped[int | None]
    height: Mapped[int | None]
    caption: Mapped[str | None]
    caption_model_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("llm_models.id"))
    created_at: Mapped[datetime] = _created()


class VectorIndex(Base):
    __tablename__ = "vector_indexes"
    __table_args__ = (UniqueConstraint("decomposition_id", "index_config_id"),)

    id: Mapped[uuid.UUID] = _pk()
    decomposition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decompositions.id", ondelete="CASCADE"))
    index_config_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("index_configs.id"))
    vector_store: Mapped[str]
    collection_name: Mapped[str] = mapped_column(unique=True)
    embedding_model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("llm_models.id"))
    dimension: Mapped[int]
    chunk_count: Mapped[int] = mapped_column(server_default=_db())
    status: Mapped[str] = mapped_column(server_default=_db())
    error: Mapped[str | None]
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("vector_index_id", "chunk_index"),)

    id: Mapped[uuid.UUID] = _pk()
    vector_index_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vector_indexes.id", ondelete="CASCADE"))
    chunk_index: Mapped[int]
    page_start: Mapped[int]
    page_end: Mapped[int]
    char_start: Mapped[int | None]
    char_end: Mapped[int | None]
    text: Mapped[str]


# =====================================================================================================
# 3. Runs & results
# =====================================================================================================


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None]
    hypothesis: Mapped[str | None]
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = _pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    pipeline_config_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_configs.id"))
    experiment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("experiments.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(server_default=_db())
    state: Mapped[str] = mapped_column(server_default=_db())
    stage: Mapped[str | None]
    decomposition_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("decompositions.id", ondelete="SET NULL"))
    vector_index_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vector_indexes.id", ondelete="SET NULL"))
    progress_done: Mapped[int] = mapped_column(server_default=_db())
    progress_total: Mapped[int] = mapped_column(server_default=_db())
    options: Mapped[dict[str, Any]] = _json()
    config_snapshot: Mapped[dict[str, Any]] = _json()
    error: Mapped[str | None]
    cancel_requested: Mapped[bool] = mapped_column(server_default=_db())
    attempts: Mapped[int] = mapped_column(server_default=_db())
    max_attempts: Mapped[int] = mapped_column(server_default=_db())
    worker_id: Mapped[str | None]
    heartbeat_at: Mapped[datetime | None]
    queued_at: Mapped[datetime] = _created()
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    document: Mapped[Document] = relationship()
    pipeline_config: Mapped[PipelineConfig] = relationship()
    vector_index: Mapped[VectorIndex | None] = relationship()


class RunEvent(Base):
    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = _created()
    level: Mapped[str] = mapped_column(server_default=_db())
    stage: Mapped[str | None]
    message: Mapped[str]
    data: Mapped[dict[str, Any]] = _json()


class FieldResult(Base):
    __tablename__ = "field_results"
    __table_args__ = (UniqueConstraint("run_id", "retrieval_config_id", "field_id"),)

    id: Mapped[uuid.UUID] = _pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id"))
    retrieval_config_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retrieval_configs.id"))
    status: Mapped[str]
    value: Mapped[Any | None] = mapped_column(JSONB)
    raw_answer: Mapped[str | None]
    error: Mapped[str | None]
    extraction_ms: Mapped[int | None]
    created_at: Mapped[datetime] = _created()


class RetrievalHit(Base):
    __tablename__ = "retrieval_hits"

    field_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("field_results.id", ondelete="CASCADE"), primary_key=True)
    rank: Mapped[int] = mapped_column(primary_key=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chunks.id"))
    score: Mapped[float] = mapped_column(Double)
    matched_query: Mapped[str | None]


class LlmCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = _pk()
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    field_result_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("field_results.id", ondelete="CASCADE"))
    purpose: Mapped[str]
    model_profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_profiles.id", ondelete="SET NULL"))
    provider_key: Mapped[str]
    model_name: Mapped[str]
    params: Mapped[dict[str, Any]] = _json()
    system_prompt: Mapped[str | None]
    user_prompt: Mapped[str | None]
    response: Mapped[str | None]
    status: Mapped[str]
    error: Mapped[str | None]
    prompt_tokens: Mapped[int | None]
    completion_tokens: Mapped[int | None]
    latency_ms: Mapped[int | None]
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    created_at: Mapped[datetime] = _created()


class Judgement(Base):
    __tablename__ = "judgements"

    id: Mapped[uuid.UUID] = _pk()
    field_result_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("field_results.id", ondelete="CASCADE"))
    model_profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_profiles.id", ondelete="SET NULL"))
    verdict: Mapped[str]
    issue: Mapped[str | None]
    explanation: Mapped[str | None]
    llm_call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("llm_calls.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()


# =====================================================================================================
# 4. Evaluation
# =====================================================================================================


class GroundTruth(Base):
    __tablename__ = "ground_truth"
    __table_args__ = (UniqueConstraint("document_id", "field_id"),)

    id: Mapped[uuid.UUID] = _pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"))
    expected_value: Mapped[Any] = mapped_column(JSONB)
    notes: Mapped[str | None]
    created_by: Mapped[str | None]
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


# Read-only views, kept out of Base.metadata so they are never mistaken for tables.
views = MetaData()

best_values = Table(
    "v_best_values", views,
    Column("run_id", Uuid), Column("document_id", Uuid), Column("field_id", Uuid),
    Column("field_key", Text), Column("field_label", Text), Column("field_result_id", Uuid),
    Column("retrieval_config", Text), Column("status", Text), Column("value", JSONB),
    Column("verdict", Text), Column("issue", Text), Column("explanation", Text),
)

run_evaluation = Table(
    "v_run_evaluation", views,
    Column("run_id", Uuid), Column("document_id", Uuid), Column("field_id", Uuid),
    Column("field_key", Text), Column("retrieval_config", Text), Column("extracted_value", JSONB),
    Column("expected_value", JSONB), Column("verdict", Text), Column("exact_match", Boolean),
)
