"""Changes to the configuration stored in the database.

Runs execute from their snapshot, so editing rows in place never changes a queued or past run.
The rules that keep that true and keep the system runnable:

* Names, keys and a model's name/kind/embedding dimension never change (run options, snapshots and
  results refer to them; indexes are reused per embedding model).
* Decomposition and index configs are create-only: ingestion reuses their outputs by config id.
* Pipeline writes must leave the pipeline resolvable; every other write (except enabling or disabling
  a provider or model, a deliberate operator action) must leave the default pipeline resolvable.
* Every write flushes, so constraint violations surface inside the request (the API maps them to
  409/422) and ordered replacements (positions, the default flag, the active prompt) happen in order.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any, TypeVar

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ...core.errors import AppError, Conflict, InvalidConfig, InvalidInput, NotFound
from ...domain.enums import ModelKind
from .. import models as m
from .config import ConfigRepo

T = TypeVar("T")


class ConfigWriter:
    def __init__(self, session: Session):
        self.session = session

    # ---- helpers ----------------------------------------------------------------------------------

    def _named(self, model: type[T], name: str, what: str) -> T:
        row = self.session.scalars(select(model).where(model.name == name)).one_or_none()  # type: ignore[attr-defined]
        if row is None:
            raise NotFound(f"{what} {name!r} not found")
        return row

    def _versioned(self, model: type[T], ref: dict[str, Any], what: str) -> T:
        row = self.session.scalars(
            select(model).where(model.name == ref["name"], model.version == ref["version"])  # type: ignore[attr-defined]
        ).one_or_none()
        if row is None:
            raise NotFound(f"{what} {ref['name']!r} v{ref['version']} not found")
        return row

    def _model(self, model_id: uuid.UUID) -> m.LlmModel:
        row = self.session.get(m.LlmModel, model_id)
        if row is None:
            raise NotFound(f"Model {model_id} not found")
        return row

    def _flush(self) -> None:
        self.session.flush()
        # Relationship collections (fields, queries, RAG lists) were loaded before the change.
        self.session.expire_all()

    def _resolve(self, name: str | None, what: str) -> None:
        try:
            ConfigRepo(self.session).resolve_pipeline(name)
        except NotFound:
            if name is not None:
                raise
        except AppError as exc:
            raise InvalidConfig(f"{what}: {exc}") from exc

    def _keep_default_runnable(self) -> None:
        self._flush()
        self._resolve(None, "This change would leave the default pipeline unable to run")

    @staticmethod
    def _apply(row: Any, changes: dict[str, Any]) -> None:
        for key, value in changes.items():
            setattr(row, key, value)

    # ---- pipelines --------------------------------------------------------------------------------

    def _pipeline_refs(self, values: dict[str, Any]) -> dict[str, Any]:
        """Request references (names and {name, version}) → foreign-key columns."""
        out: dict[str, Any] = {}
        if "decomposition" in values:
            out["decomposition_config_id"] = self._named(m.DecompositionConfig, values["decomposition"], "Decomposition config").id
        if "index" in values:
            out["index_config_id"] = self._named(m.IndexConfig, values["index"], "Index config").id
        if "field_set" in values:
            out["field_set_id"] = self._versioned(m.FieldSet, values["field_set"], "Field set").id
        if "extraction_profile" in values:
            out["extraction_profile_id"] = self._named(m.ModelProfile, values["extraction_profile"], "Model profile").id
        if "extraction_prompt" in values:
            out["extraction_prompt_id"] = self._versioned(m.PromptTemplate, values["extraction_prompt"], "Prompt").id
        if "judge_profile" in values:
            ref = values["judge_profile"]
            out["judge_profile_id"] = self._named(m.ModelProfile, ref, "Model profile").id if ref else None
        if "judge_prompt" in values:
            ref = values["judge_prompt"]
            out["judge_prompt_id"] = self._versioned(m.PromptTemplate, ref, "Prompt").id if ref else None
        if "classification_profile" in values:
            ref = values["classification_profile"]
            out["classification_profile_id"] = self._named(m.ModelProfile, ref, "Model profile").id if ref else None
        if "classification_prompt" in values:
            ref = values["classification_prompt"]
            out["classification_prompt_id"] = self._versioned(m.PromptTemplate, ref, "Prompt").id if ref else None
        for key in ("description", "judge_enabled", "judge_parallel", "classification_enabled", "classification_pages",
                    "classification_min_confidence", "min_priority"):
            if key in values:
                out[key] = values[key]
        return out

    def _set_retrievals(self, pipeline: m.PipelineConfig, names: list[str]) -> None:
        """Replace the RAG configs, in priority order (positions are unique, so delete first)."""
        if not names:
            raise InvalidInput("A pipeline needs at least one RAG config")
        if len(set(names)) != len(names):
            raise InvalidInput("A RAG config can appear only once in a pipeline")
        configs = [self._named(m.RetrievalConfig, n, "RAG config") for n in names]
        self.session.execute(delete(m.PipelineConfigRetrieval).where(m.PipelineConfigRetrieval.pipeline_config_id == pipeline.id))
        self.session.flush()
        self.session.add_all(m.PipelineConfigRetrieval(pipeline_config_id=pipeline.id, retrieval_config_id=rc.id, position=i)
                             for i, rc in enumerate(configs, start=1))

    def create_pipeline(self, values: dict[str, Any]) -> m.PipelineConfig:
        row = m.PipelineConfig(name=values["name"], is_default=False, **self._pipeline_refs(values))
        self.session.add(row)
        self.session.flush()
        self._set_retrievals(row, values["retrievals"])
        self._flush()
        self._resolve(row.name, f"Pipeline {row.name!r} cannot run")
        return self._named(m.PipelineConfig, values["name"], "Pipeline config")

    def update_pipeline(self, name: str, changes: dict[str, Any]) -> m.PipelineConfig:
        row = self._named(m.PipelineConfig, name, "Pipeline config")
        self._apply(row, self._pipeline_refs(changes))
        if "retrievals" in changes:
            self._set_retrievals(row, changes["retrievals"])
        self._flush()
        self._resolve(name, f"Pipeline {name!r} cannot run")
        return self._named(m.PipelineConfig, name, "Pipeline config")

    def delete_pipeline(self, name: str) -> None:
        row = self._named(m.PipelineConfig, name, "Pipeline config")
        if row.is_default:
            raise Conflict(f"{name!r} is the default pipeline; make another pipeline the default first")
        self.session.delete(row)
        self._flush()

    def set_default_pipeline(self, name: str) -> m.PipelineConfig:
        row = self._named(m.PipelineConfig, name, "Pipeline config")
        self._resolve(name, f"Pipeline {name!r} cannot be the default")
        # Only one default may exist (partial unique index): clear the old one first.
        self.session.execute(update(m.PipelineConfig).where(m.PipelineConfig.is_default).values(is_default=False))
        self.session.flush()
        row.is_default = True
        self._flush()
        return self._named(m.PipelineConfig, name, "Pipeline config")

    # ---- RAG configs, profiles, decomposition and index configs -------------------------------------

    def create_retrieval(self, values: dict[str, Any]) -> m.RetrievalConfig:
        self.session.add(m.RetrievalConfig(**values))
        self._flush()
        return self._named(m.RetrievalConfig, values["name"], "RAG config")

    def update_retrieval(self, name: str, changes: dict[str, Any]) -> m.RetrievalConfig:
        self._apply(self._named(m.RetrievalConfig, name, "RAG config"), changes)
        self._keep_default_runnable()
        return self._named(m.RetrievalConfig, name, "RAG config")

    def delete_retrieval(self, name: str) -> None:
        self.session.delete(self._named(m.RetrievalConfig, name, "RAG config"))
        self._flush()

    def _check_chat_model(self, model_id: uuid.UUID) -> None:
        if self._model(model_id).kind == ModelKind.EMBEDDING:
            raise InvalidInput("A model profile needs a chat or vision model, not an embedding model")

    def create_profile(self, values: dict[str, Any]) -> m.ModelProfile:
        self._check_chat_model(values["model_id"])
        self.session.add(m.ModelProfile(**values))
        self._flush()
        return self._named(m.ModelProfile, values["name"], "Model profile")

    def update_profile(self, name: str, changes: dict[str, Any]) -> m.ModelProfile:
        if "model_id" in changes:
            self._check_chat_model(changes["model_id"])
        self._apply(self._named(m.ModelProfile, name, "Model profile"), changes)
        self._keep_default_runnable()
        return self._named(m.ModelProfile, name, "Model profile")

    def delete_profile(self, name: str) -> None:
        self.session.delete(self._named(m.ModelProfile, name, "Model profile"))
        self._flush()

    def create_decomposition(self, values: dict[str, Any]) -> m.DecompositionConfig:
        self.session.add(m.DecompositionConfig(**values))
        self._flush()
        return self._named(m.DecompositionConfig, values["name"], "Decomposition config")

    def delete_decomposition(self, name: str) -> None:
        self.session.delete(self._named(m.DecompositionConfig, name, "Decomposition config"))
        self._flush()

    def create_index_config(self, values: dict[str, Any]) -> m.IndexConfig:
        if self._model(values["embedding_model_id"]).kind != ModelKind.EMBEDDING:
            raise InvalidInput("An index config needs an embedding model")
        self.session.add(m.IndexConfig(**values))
        self._flush()
        return self._named(m.IndexConfig, values["name"], "Index config")

    def delete_index_config(self, name: str) -> None:
        self.session.delete(self._named(m.IndexConfig, name, "Index config"))
        self._flush()

    # ---- prompts ------------------------------------------------------------------------------------

    def create_prompt(self, values: dict[str, Any]) -> m.PromptTemplate:
        if self.session.scalar(select(func.count()).where(m.PromptTemplate.name == values["name"])):
            raise Conflict(f"Prompt {values['name']!r} exists; save a new version of it instead")
        self.session.add(m.PromptTemplate(version=1, is_active=True, **values))
        self._flush()
        return self._versioned(m.PromptTemplate, {"name": values["name"], "version": 1}, "Prompt")

    def create_prompt_version(self, name: str, body: str, notes: str | None) -> m.PromptTemplate:
        """The next version becomes the active one; pipelines keep the version they are pinned to."""
        latest = self.session.scalars(
            select(m.PromptTemplate).where(m.PromptTemplate.name == name).order_by(m.PromptTemplate.version.desc()).limit(1)
        ).one_or_none()
        if latest is None:
            raise NotFound(f"Prompt {name!r} not found")
        version = latest.version + 1
        # Only one active version per name (partial unique index): deactivate first.
        self.session.execute(update(m.PromptTemplate).where(m.PromptTemplate.name == name).values(is_active=False))
        self.session.flush()
        self.session.add(m.PromptTemplate(name=name, version=version, role=latest.role, body=body, notes=notes, is_active=True))
        self._flush()
        return self._versioned(m.PromptTemplate, {"name": name, "version": version}, "Prompt")

    # ---- fields -------------------------------------------------------------------------------------

    def _set_queries(self, field_id: uuid.UUID, queries: Iterable[str]) -> None:
        cleaned = [q.strip() for q in queries if q.strip()]
        self.session.execute(delete(m.FieldQuery).where(m.FieldQuery.field_id == field_id))
        self.session.flush()
        self.session.add_all(m.FieldQuery(field_id=field_id, position=i, query=q) for i, q in enumerate(cleaned, start=1))

    def _field(self, field_id: uuid.UUID) -> m.Field:
        row = self.session.get(m.Field, field_id)
        if row is None:
            raise NotFound(f"Field {field_id} not found")
        return row

    def create_field(self, field_set: dict[str, Any], values: dict[str, Any]) -> m.Field:
        fs = self._versioned(m.FieldSet, field_set, "Field set")
        position = (self.session.scalar(select(func.max(m.Field.position)).where(m.Field.field_set_id == fs.id)) or 0) + 1
        queries = values.pop("queries", [])
        row = m.Field(field_set_id=fs.id, position=position, **values)
        self.session.add(row)
        self.session.flush()
        self._set_queries(row.id, queries)
        self._keep_default_runnable()
        return self._field(row.id)

    def update_field(self, field_id: uuid.UUID, changes: dict[str, Any]) -> m.Field:
        row = self._field(field_id)
        queries = changes.pop("queries", None)
        self._apply(row, changes)
        if queries is not None:
            self._set_queries(row.id, queries)
        self._keep_default_runnable()
        return self._field(field_id)

    # ---- providers and models -----------------------------------------------------------------------

    def update_provider(self, key: str, base_url: str | None, enabled: bool | None) -> m.LlmProvider:
        row = ConfigRepo(self.session).update_provider(key, base_url, enabled)
        self._flush()
        return self.session.get(m.LlmProvider, row.id)  # type: ignore[return-value]

    def create_model(self, provider_key: str, values: dict[str, Any]) -> m.LlmModel:
        provider = self.session.scalars(select(m.LlmProvider).where(m.LlmProvider.key == provider_key)).one_or_none()
        if provider is None:
            raise NotFound(f"LLM provider {provider_key!r} not found")
        row = m.LlmModel(provider_id=provider.id, **values)
        self.session.add(row)
        self._flush()
        return self._model(row.id)

    def update_model(self, model_id: uuid.UUID, changes: dict[str, Any]) -> m.LlmModel:
        """Enabled flag, context window and prices only; disabling may leave pipelines unable to run (shown as their error)."""
        self._apply(self._model(model_id), changes)
        self._flush()
        return self._model(model_id)
