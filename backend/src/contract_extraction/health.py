"""Service checks shared by the API (``/health``, ``/health/ready``) and the CLI (``check``).

* liveness: the process can reach the database (cheap; polled by the gateway).
* readiness: the schema is present, the default pipeline resolves, and its vector store and
  model endpoints are reachable with the models available.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy import inspect

from .core.errors import AppError
from .core.settings import Settings
from .domain.config import PipelineConfig
from .domain.enums import ProviderKind, VectorStore
from .persistence import models as m
from .persistence.db import Database
from .persistence.repositories import ConfigRepo
from .providers.base import ProviderError
from .providers.qdrant import QdrantStore
from .secrets import resolve_api_key


@dataclass(frozen=True)
class Component:
    name: str
    ok: bool
    detail: str


def liveness(db: Database) -> list[Component]:
    try:
        db.ping()
        return [Component("database", True, "reachable")]
    except Exception as exc:  # noqa: BLE001 - any failure means not alive
        return [Component("database", False, f"{exc.__class__.__name__}: {exc}")]


def _models(pipeline: PipelineConfig):
    models = [pipeline.extraction_profile.model, pipeline.index.embedding_model]
    if pipeline.judge_enabled and pipeline.judge_profile:
        models.append(pipeline.judge_profile.model)
    seen = set()
    for model in models:
        if (model.provider.key, model.name) not in seen:
            seen.add((model.provider.key, model.name))
            yield model


def readiness(db: Database, settings: Settings) -> tuple[list[Component], PipelineConfig | None]:
    """Components plus the resolved default pipeline (None when it cannot be resolved)."""
    components = liveness(db)
    if not components[0].ok:
        return components, None

    missing = set(m.Base.metadata.tables) - set(inspect(db.engine).get_table_names())
    if missing:
        components.append(Component("schema", False, f"missing tables {sorted(missing)}; recreate from docker/schema.sql"))
        return components, None
    components.append(Component("schema", True, "all tables present"))

    try:
        with db.session() as s:
            pipeline = ConfigRepo(s).resolve_pipeline()
        components.append(Component("pipeline", True, f"default pipeline {pipeline.name!r} resolves"))
    except AppError as exc:
        components.append(Component("pipeline", False, str(exc)))
        return components, None

    if pipeline.index.vector_store == VectorStore.QDRANT:
        try:
            QdrantStore(settings.qdrant.url, settings.qdrant.api_key or None, timeout=5).ping()
            components.append(Component("qdrant", True, settings.qdrant.url))
        except ProviderError as exc:
            components.append(Component("qdrant", False, str(exc)))

    for model in _models(pipeline):
        p = model.provider
        name = f"{p.key}:{model.name}"
        if p.kind != ProviderKind.OLLAMA:
            try:
                resolve_api_key(p, settings)
                components.append(Component(name, True, f"hosted at {p.base_url}; API key present"))
            except AppError as exc:
                components.append(Component(name, False, str(exc)))
            continue
        try:
            tags = httpx.get(f"{p.base_url.rstrip('/')}/api/tags", timeout=5).json()
            available = {t.get("name") for t in tags.get("models", [])}
            if model.name in available:
                components.append(Component(name, True, p.base_url))
            else:
                components.append(Component(name, False, f"not available at {p.base_url} (pull it, or point the provider elsewhere)"))
        except (httpx.HTTPError, ValueError) as exc:
            components.append(Component(name, False, f"{p.base_url} unreachable ({exc.__class__.__name__})"))
    return components, pipeline
