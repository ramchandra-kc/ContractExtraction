"""Editing configuration: one catalog read and the writes.

Runs execute from their snapshot, so these changes only affect runs queued afterwards. Creates answer
201 with the row (rows are read back through the catalog), updates 200 with the row, deletes 204.
Rules and their reasons are in persistence/repositories/config_writes.py.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ...core.errors import AppError
from ...persistence import models as m
from ...persistence.repositories import ConfigRepo
from ...persistence.repositories.config_writes import ConfigWriter
from ..config_schemas import (
    Catalog,
    CatalogContractType,
    CatalogDecomposition,
    CatalogField,
    CatalogFieldSet,
    CatalogIndex,
    CatalogModel,
    CatalogPipeline,
    CatalogPrompt,
    CatalogProfile,
    CatalogProvider,
    CatalogRetrieval,
    CatalogTypeField,
    DecompositionCreate,
    FieldCreate,
    FieldUpdate,
    IndexCreate,
    ModelCreate,
    ModelUpdate,
    PipelineCreate,
    PipelineUpdate,
    ProfileCreate,
    ProfileUpdate,
    PromptCreate,
    PromptVersionCreate,
    ProviderUpdate,
    RetrievalCreate,
    RetrievalUpdate,
    VersionRef,
)
from ..deps import SessionDep

router = APIRouter(prefix="/config", tags=["config"])

CREATED = {"status_code": status.HTTP_201_CREATED}
NO_CONTENT = {"status_code": status.HTTP_204_NO_CONTENT, "response_class": Response}


# ---- row → catalog form ---------------------------------------------------------------------------


def _model(row: m.LlmModel) -> CatalogModel:
    return CatalogModel(id=row.id, name=row.name, kind=row.kind, context_window=row.context_window,
                        embedding_dimension=row.embedding_dimension, input_cost_per_mtok=row.input_cost_per_mtok,
                        output_cost_per_mtok=row.output_cost_per_mtok, is_enabled=row.is_enabled)


def _provider(row: m.LlmProvider) -> CatalogProvider:
    return CatalogProvider(key=row.key, kind=row.kind, base_url=row.base_url, api_key_env=row.api_key_env,
                           is_enabled=row.is_enabled,
                           models=[_model(x) for x in sorted(row.models, key=lambda x: (x.kind, x.name))])


def _profile(row: m.ModelProfile) -> CatalogProfile:
    return CatalogProfile(name=row.name, description=row.description, model_id=row.model_id, model=row.model.name,
                          provider=row.model.provider.key, temperature=row.temperature, top_p=row.top_p, top_k=row.top_k,
                          max_tokens=row.max_tokens, num_ctx=row.num_ctx, json_mode=row.json_mode,
                          timeout_seconds=row.timeout_seconds)


def _prompt(row: m.PromptTemplate) -> CatalogPrompt:
    return CatalogPrompt(name=row.name, version=row.version, role=row.role, body=row.body, notes=row.notes,
                         is_active=row.is_active, created_at=row.created_at)


def _decomposition(row: m.DecompositionConfig) -> CatalogDecomposition:
    return CatalogDecomposition(name=row.name, description=row.description, method=row.method,
                                text_format=row.text_format, keep_invisible_text=row.keep_invisible_text,
                                remove_headers_footers=row.remove_headers_footers, ocr_language=row.ocr_language,
                                dpi=row.dpi)


def _index(row: m.IndexConfig) -> CatalogIndex:
    return CatalogIndex(name=row.name, description=row.description, embedding_model_id=row.embedding_model_id,
                        embedding_model=row.embedding_model.name, chunk_size=row.chunk_size,
                        chunk_overlap=row.chunk_overlap, vector_store=row.vector_store, distance=row.distance,
                        batch_size=row.batch_size)


def _retrieval(row: m.RetrievalConfig) -> CatalogRetrieval:
    return CatalogRetrieval(name=row.name, description=row.description, top_k=row.top_k,
                            score_threshold=row.score_threshold, query_expansion=row.query_expansion,
                            per_query_top=row.per_query_top, min_score=row.min_score,
                            keyword_search=row.keyword_search, anchor_chunks=row.anchor_chunks)


def _field(row: m.Field) -> CatalogField:
    return CatalogField(id=row.id, key=row.key, label=row.label, description=row.description,
                        value_type=row.value_type, type_spec=row.type_spec, value_schema=row.value_schema,
                        priority=row.priority, user_prompt=row.user_prompt, position=row.position,
                        is_enabled=row.is_enabled, queries=[q.query for q in row.queries], anchor=row.anchor)


def _contract_type(row: m.ContractType) -> CatalogContractType:
    return CatalogContractType(key=row.key, label=row.label, description=row.description, is_fallback=row.is_fallback,
                               position=row.position,
                               fields=[CatalogTypeField(key=mb.field.key, group=mb.field_group, priority=mb.priority)
                                       for mb in row.members])


def _ref(row: m.PromptTemplate | m.FieldSet | None) -> VersionRef | None:
    return VersionRef(name=row.name, version=row.version) if row else None


def _pipeline(row: m.PipelineConfig, repo: ConfigRepo) -> CatalogPipeline:
    try:
        repo.resolve_pipeline(row.name)
        error = None
    except AppError as exc:
        error = str(exc)
    return CatalogPipeline(
        name=row.name, description=row.description, is_default=row.is_default,
        decomposition=row.decomposition_config.name, index=row.index_config.name,
        field_set=_ref(row.field_set), extraction_profile=row.extraction_profile.name,  # type: ignore[arg-type]
        extraction_prompt=_ref(row.extraction_prompt),  # type: ignore[arg-type]
        judge_enabled=row.judge_enabled, judge_profile=row.judge_profile.name if row.judge_profile else None,
        judge_prompt=_ref(row.judge_prompt), judge_parallel=row.judge_parallel,
        classification_enabled=row.classification_enabled,
        classification_profile=row.classification_profile.name if row.classification_profile else None,
        classification_prompt=_ref(row.classification_prompt), classification_pages=row.classification_pages,
        classification_min_confidence=row.classification_min_confidence, min_priority=row.min_priority,
        extraction_granularity=row.extraction_granularity, group_max_fields=row.group_max_fields,
        retrievals=[r.retrieval_config.name for r in row.retrievals], error=error,
    )


# ---- read -----------------------------------------------------------------------------------------


@router.get("/catalog", response_model=Catalog)
def get_catalog(session: SessionDep):
    """All configuration rows with what they reference, for editing. Pipelines carry ``error`` when they cannot run."""
    q = lambda model, *order: session.scalars(select(model).order_by(*order)).all()  # noqa: E731
    repo = ConfigRepo(session)
    field_sets = session.scalars(select(m.FieldSet).options(
        selectinload(m.FieldSet.fields).selectinload(m.Field.queries),
        selectinload(m.FieldSet.contract_types).selectinload(m.ContractType.members).selectinload(m.ContractTypeField.field),
    ).order_by(m.FieldSet.name, m.FieldSet.version)).all()
    return Catalog(
        providers=[_provider(r) for r in session.scalars(select(m.LlmProvider).options(selectinload(m.LlmProvider.models))
                                                         .order_by(m.LlmProvider.key)).all()],
        profiles=[_profile(r) for r in q(m.ModelProfile, m.ModelProfile.name)],
        prompts=[_prompt(r) for r in q(m.PromptTemplate, m.PromptTemplate.name, m.PromptTemplate.version.desc())],
        decompositions=[_decomposition(r) for r in q(m.DecompositionConfig, m.DecompositionConfig.name)],
        indexes=[_index(r) for r in q(m.IndexConfig, m.IndexConfig.name)],
        retrievals=[_retrieval(r) for r in q(m.RetrievalConfig, m.RetrievalConfig.name)],
        field_sets=[CatalogFieldSet(name=fs.name, version=fs.version, description=fs.description,
                                    fields=[_field(f) for f in fs.fields],
                                    contract_types=[_contract_type(t) for t in fs.contract_types]) for fs in field_sets],
        pipelines=[_pipeline(r, repo) for r in q(m.PipelineConfig, m.PipelineConfig.name)],
    )


# ---- pipelines ------------------------------------------------------------------------------------


@router.post("/pipelines", response_model=CatalogPipeline, **CREATED)
def create_pipeline(body: PipelineCreate, session: SessionDep):
    """A new pipeline; 422 when it could not run (e.g. a prompt with the wrong role or a disabled model)."""
    return _pipeline(ConfigWriter(session).create_pipeline(body.model_dump()), ConfigRepo(session))


@router.patch("/pipelines/{name}", response_model=CatalogPipeline)
def update_pipeline(name: str, body: PipelineUpdate, session: SessionDep):
    """Change what a pipeline uses; ``retrievals`` replaces the RAG configs in the given priority order."""
    return _pipeline(ConfigWriter(session).update_pipeline(name, body.model_dump(exclude_unset=True)), ConfigRepo(session))


@router.delete("/pipelines/{name}", **NO_CONTENT)
def delete_pipeline(name: str, session: SessionDep):
    """409 for the default pipeline or one that runs used."""
    ConfigWriter(session).delete_pipeline(name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/pipelines/{name}/default", response_model=CatalogPipeline)
def set_default_pipeline(name: str, session: SessionDep):
    """Make this the default pipeline (runs queued without a pipeline name use it)."""
    return _pipeline(ConfigWriter(session).set_default_pipeline(name), ConfigRepo(session))


# ---- RAG configs ----------------------------------------------------------------------------------


@router.post("/retrievals", response_model=CatalogRetrieval, **CREATED)
def create_retrieval(body: RetrievalCreate, session: SessionDep):
    return _retrieval(ConfigWriter(session).create_retrieval(body.model_dump()))


@router.patch("/retrievals/{name}", response_model=CatalogRetrieval)
def update_retrieval(name: str, body: RetrievalUpdate, session: SessionDep):
    return _retrieval(ConfigWriter(session).update_retrieval(name, body.model_dump(exclude_unset=True)))


@router.delete("/retrievals/{name}", **NO_CONTENT)
def delete_retrieval(name: str, session: SessionDep):
    """409 while a pipeline or a result refers to it."""
    ConfigWriter(session).delete_retrieval(name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- model profiles -------------------------------------------------------------------------------


@router.post("/profiles", response_model=CatalogProfile, **CREATED)
def create_profile(body: ProfileCreate, session: SessionDep):
    return _profile(ConfigWriter(session).create_profile(body.model_dump()))


@router.patch("/profiles/{name}", response_model=CatalogProfile)
def update_profile(name: str, body: ProfileUpdate, session: SessionDep):
    return _profile(ConfigWriter(session).update_profile(name, body.model_dump(exclude_unset=True)))


@router.delete("/profiles/{name}", **NO_CONTENT)
def delete_profile(name: str, session: SessionDep):
    """409 while a pipeline uses it (LLM calls keep their model name, so past calls do not block it)."""
    ConfigWriter(session).delete_profile(name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- decomposition and index configs (create-only) ------------------------------------------------


@router.post("/decompositions", response_model=CatalogDecomposition, **CREATED)
def create_decomposition(body: DecompositionCreate, session: SessionDep):
    """Create-only: decompositions are reused by config id, so a config never changes after it is made."""
    return _decomposition(ConfigWriter(session).create_decomposition(body.model_dump()))


@router.delete("/decompositions/{name}", **NO_CONTENT)
def delete_decomposition(name: str, session: SessionDep):
    ConfigWriter(session).delete_decomposition(name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/indexes", response_model=CatalogIndex, **CREATED)
def create_index_config(body: IndexCreate, session: SessionDep):
    """Create-only: vector indexes are reused by config id, so a config never changes after it is made."""
    return _index(ConfigWriter(session).create_index_config(body.model_dump()))


@router.delete("/indexes/{name}", **NO_CONTENT)
def delete_index_config(name: str, session: SessionDep):
    ConfigWriter(session).delete_index_config(name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- prompts --------------------------------------------------------------------------------------


@router.post("/prompts", response_model=CatalogPrompt, **CREATED)
def create_prompt(body: PromptCreate, session: SessionDep):
    """A new prompt name at version 1; 409 when the name exists (save a new version instead)."""
    return _prompt(ConfigWriter(session).create_prompt(body.model_dump()))


@router.post("/prompts/{name}/versions", response_model=CatalogPrompt, **CREATED)
def create_prompt_version(name: str, body: PromptVersionCreate, session: SessionDep):
    """The next version becomes active. Pipelines keep the version they use until they are changed."""
    return _prompt(ConfigWriter(session).create_prompt_version(name, body.body, body.notes))


# ---- fields ---------------------------------------------------------------------------------------


@router.post("/field-sets/{name}/{version}/fields", response_model=CatalogField, **CREATED)
def create_field(name: str, version: int, body: FieldCreate, session: SessionDep):
    """Add a field after the last one of the field set."""
    return _field(ConfigWriter(session).create_field({"name": name, "version": version}, body.model_dump()))


@router.patch("/fields/{field_id}", response_model=CatalogField)
def update_field(field_id: uuid.UUID, body: FieldUpdate, session: SessionDep):
    """``queries`` replaces the expansion queries in the given order. Disable a field instead of deleting it."""
    return _field(ConfigWriter(session).update_field(field_id, body.model_dump(exclude_unset=True)))


# ---- providers and models -------------------------------------------------------------------------


@router.patch("/providers/{key}", response_model=CatalogProvider)
def update_provider(key: str, body: ProviderUpdate, session: SessionDep):
    """Point a provider at another server or enable/disable it (pipelines using it then show an error)."""
    changes = body.model_dump(exclude_unset=True)
    return _provider(ConfigWriter(session).update_provider(key, changes.get("base_url"), changes.get("is_enabled")))


@router.post("/providers/{key}/models", response_model=CatalogModel, **CREATED)
def create_model(key: str, body: ModelCreate, session: SessionDep):
    return _model(ConfigWriter(session).create_model(key, body.model_dump()))


@router.patch("/models/{model_id}", response_model=CatalogModel)
def update_model(model_id: uuid.UUID, body: ModelUpdate, session: SessionDep):
    """Enabled flag, context window and prices. Name, kind and embedding dimension never change."""
    return _model(ConfigWriter(session).update_model(model_id, body.model_dump(exclude_unset=True)))
