"""Model and RAG configuration stored in the database."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...core.errors import InvalidConfig, NotFound
from ...domain import config as d
from ...domain.enums import ModelKind, PromptRole
from .. import models as m


class ConfigRepo:
    def __init__(self, session: Session):
        self.session = session

    # ---- listings -------------------------------------------------------------------------------

    def providers(self) -> Sequence[m.LlmProvider]:
        return self.session.scalars(select(m.LlmProvider).order_by(m.LlmProvider.key)).all()

    def models(self, kind: ModelKind | None = None) -> Sequence[m.LlmModel]:
        q = select(m.LlmModel).options(selectinload(m.LlmModel.provider)).order_by(m.LlmModel.name)
        if kind:
            q = q.where(m.LlmModel.kind == kind)
        return self.session.scalars(q).all()

    def model_profiles(self) -> Sequence[m.ModelProfile]:
        return self.session.scalars(select(m.ModelProfile).order_by(m.ModelProfile.name)).all()

    def retrieval_configs(self) -> Sequence[m.RetrievalConfig]:
        return self.session.scalars(select(m.RetrievalConfig).order_by(m.RetrievalConfig.name)).all()

    def field_sets(self) -> Sequence[m.FieldSet]:
        return self.session.scalars(select(m.FieldSet).order_by(m.FieldSet.name, m.FieldSet.version)).all()

    def pipelines(self) -> Sequence[m.PipelineConfig]:
        return self.session.scalars(select(m.PipelineConfig).order_by(m.PipelineConfig.name)).all()

    # ---- resolution -----------------------------------------------------------------------------

    def resolve_pipeline(self, name: str | None = None) -> d.PipelineConfig:
        """The named pipeline config (or the default one) with everything it references, validated."""
        q = select(m.PipelineConfig)
        q = q.where(m.PipelineConfig.name == name) if name else q.where(m.PipelineConfig.is_default)
        row = self.session.scalars(q).one_or_none()
        if row is None:
            raise NotFound(f"Pipeline config {name!r} not found" if name else "No default pipeline config")

        judge_profile = judge_prompt = None
        if row.judge_enabled:
            judge_profile = _profile(row.judge_profile, ModelKind.CHAT, "judge")
            judge_prompt = _prompt(row.judge_prompt, PromptRole.JUDGE_SYSTEM)

        fields = tuple(_field(f) for f in row.field_set.fields if f.is_enabled)
        if not fields:
            raise InvalidConfig(f"Field set {row.field_set.name!r} v{row.field_set.version} has no enabled fields")
        if not row.retrievals:
            raise InvalidConfig(f"Pipeline config {row.name!r} has no retrieval configs")

        return d.PipelineConfig(
            id=row.id,
            name=row.name,
            decomposition=_decomposition(row.decomposition_config),
            index=_index(row.index_config),
            field_set=d.FieldSet(id=row.field_set.id, name=row.field_set.name, version=row.field_set.version, fields=fields),
            extraction_profile=_profile(row.extraction_profile, ModelKind.CHAT, "extraction"),
            extraction_prompt=_prompt(row.extraction_prompt, PromptRole.EXTRACTION_SYSTEM),
            judge_enabled=row.judge_enabled,
            judge_profile=judge_profile,
            judge_prompt=judge_prompt,
            judge_parallel=row.judge_parallel,
            retrievals=tuple(_retrieval(r.retrieval_config) for r in row.retrievals),
        )


# ---- row → domain ---------------------------------------------------------------------------------


def _provider(row: m.LlmProvider) -> d.Provider:
    if not row.is_enabled:
        raise InvalidConfig(f"LLM provider {row.key!r} is disabled")
    return d.Provider(id=row.id, key=row.key, kind=row.kind, base_url=row.base_url,
                      api_key_env=row.api_key_env, settings=row.settings)


def _model(row: m.LlmModel, kind: ModelKind, purpose: str) -> d.Model:
    if not row.is_enabled:
        raise InvalidConfig(f"Model {row.name!r} ({purpose}) is disabled")
    allowed = (ModelKind.CHAT, ModelKind.VISION) if kind == ModelKind.CHAT else (kind,)
    if row.kind not in allowed:
        raise InvalidConfig(f"Model {row.name!r} is a {row.kind} model and cannot be used for {purpose}")
    return d.Model(id=row.id, name=row.name, kind=row.kind, provider=_provider(row.provider),
                   context_window=row.context_window, embedding_dimension=row.embedding_dimension,
                   input_cost_per_mtok=row.input_cost_per_mtok, output_cost_per_mtok=row.output_cost_per_mtok)


def _profile(row: m.ModelProfile, kind: ModelKind, purpose: str) -> d.ModelProfile:
    return d.ModelProfile(id=row.id, name=row.name, model=_model(row.model, kind, purpose),
                          temperature=row.temperature, top_p=row.top_p, top_k=row.top_k, max_tokens=row.max_tokens,
                          num_ctx=row.num_ctx, json_mode=row.json_mode, timeout_seconds=row.timeout_seconds,
                          extra=row.extra)


def _prompt(row: m.PromptTemplate, role: PromptRole) -> d.Prompt:
    if row.role != role:
        raise InvalidConfig(f"Prompt {row.name!r} v{row.version} has role {row.role!r}, expected {role.value!r}")
    return d.Prompt(id=row.id, name=row.name, version=row.version, role=row.role, body=row.body)


def _decomposition(row: m.DecompositionConfig) -> d.DecompositionConfig:
    caption = _profile(row.caption_profile, ModelKind.VISION, "image captioning") if row.caption_profile else None
    return d.DecompositionConfig(id=row.id, name=row.name, method=row.method, text_format=row.text_format,
                                 keep_invisible_text=row.keep_invisible_text,
                                 remove_headers_footers=row.remove_headers_footers, ocr_language=row.ocr_language,
                                 dpi=row.dpi, caption_profile=caption, options=row.options)


def _index(row: m.IndexConfig) -> d.IndexConfig:
    return d.IndexConfig(id=row.id, name=row.name, embedding_model=_model(row.embedding_model, ModelKind.EMBEDDING, "embedding"),
                         chunk_size=row.chunk_size, chunk_overlap=row.chunk_overlap, vector_store=row.vector_store,
                         distance=row.distance, batch_size=row.batch_size)


def _retrieval(row: m.RetrievalConfig) -> d.RetrievalConfig:
    return d.RetrievalConfig(id=row.id, name=row.name, top_k=row.top_k, score_threshold=row.score_threshold,
                             query_expansion=row.query_expansion, per_query_top=row.per_query_top,
                             min_score=row.min_score)


def _field(row: m.Field) -> d.Field:
    return d.Field(id=row.id, key=row.key, label=row.label, description=row.description, value_type=row.value_type,
                   user_prompt=row.user_prompt, position=row.position, queries=tuple(q.query for q in row.queries))
