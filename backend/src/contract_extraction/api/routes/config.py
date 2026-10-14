"""Configuration summaries for running (resolved pipelines, providers). Editing is in config_edit.py."""

from __future__ import annotations

from fastapi import APIRouter

from ...core.errors import AppError
from ...domain.config import ModelProfile, PipelineConfig
from ...persistence.repositories import ConfigRepo
from ..deps import SessionDep
from ..schemas import FieldOut, PipelineOut, ProfileOut, ProviderOut, RetrievalOut

router = APIRouter(prefix="/config", tags=["config"])


def _profile(p: ModelProfile | None) -> ProfileOut | None:
    if p is None:
        return None
    return ProfileOut(name=p.name, model=p.model.name, provider=p.model.provider.key, temperature=p.temperature)


def _pipeline(p: PipelineConfig, is_default: bool, description: str | None) -> PipelineOut:
    return PipelineOut(
        name=p.name, is_default=is_default, description=description,
        decomposition=f"{p.decomposition.name} ({p.decomposition.method}, {p.decomposition.text_format})",
        index=f"{p.index.name} ({p.index.chunk_size}/{p.index.chunk_overlap}, {p.index.vector_store})",
        embedding_model=p.index.embedding_model.name,
        extraction=_profile(p.extraction_profile), judge=_profile(p.judge_profile if p.judge_enabled else None),
        retrievals=[RetrievalOut.model_validate(r.model_dump()) for r in p.retrievals],
        fields=[FieldOut(key=f.key, label=f.label, description=f.description, value_type=f.value_type,
                         query_count=len(f.queries)) for f in p.field_set.fields],
    )


@router.get("/pipelines", response_model=list[PipelineOut])
def list_pipelines(session: SessionDep):
    """Pipeline configs with their RAG configs (priority order), fields and models."""
    repo = ConfigRepo(session)
    out = []
    for row in repo.pipelines():
        try:
            out.append(_pipeline(repo.resolve_pipeline(row.name), row.is_default, row.description))
        except AppError as exc:
            out.append(PipelineOut(name=row.name, is_default=row.is_default, description=row.description, error=str(exc)))
    return out


@router.get("/providers", response_model=list[ProviderOut])
def list_providers(session: SessionDep):
    """LLM providers with their URLs and models (API keys are never returned, only the variable name)."""
    return ConfigRepo(session).providers()
