"""Resolved pipeline configuration.

``ConfigRepo.resolve_pipeline`` turns the configuration rows into these frozen models.
The pipeline (Phase 3) only ever sees these objects, and ``PipelineConfig.snapshot()``
is what a run stores in ``runs.config_snapshot``: everything needed to reproduce the
run, by value, without secrets.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from .enums import (
    DecompositionMethod,
    Distance,
    ModelKind,
    Priority,
    PromptRole,
    ProviderKind,
    TextFormat,
    ValueType,
    VectorStore,
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Provider(_Frozen):
    id: uuid.UUID
    key: str
    kind: ProviderKind
    base_url: str
    # Name of the env var holding the API key; the key itself is never part of the config.
    api_key_env: str | None = None
    settings: dict[str, Any] = {}


class Model(_Frozen):
    id: uuid.UUID
    name: str
    kind: ModelKind
    provider: Provider
    context_window: int | None = None
    embedding_dimension: int | None = None
    input_cost_per_mtok: Decimal | None = None
    output_cost_per_mtok: Decimal | None = None


class ModelProfile(_Frozen):
    id: uuid.UUID
    name: str
    model: Model
    temperature: Decimal
    top_p: Decimal | None = None
    top_k: int | None = None
    max_tokens: int | None = None
    num_ctx: int | None = None
    json_mode: bool = True
    timeout_seconds: int = 600
    extra: dict[str, Any] = {}


class Prompt(_Frozen):
    id: uuid.UUID
    name: str
    version: int
    role: PromptRole
    body: str


class DecompositionConfig(_Frozen):
    id: uuid.UUID
    name: str
    method: DecompositionMethod
    text_format: TextFormat
    keep_invisible_text: bool
    remove_headers_footers: bool
    ocr_language: str
    dpi: int
    caption_profile: ModelProfile | None = None
    options: dict[str, Any] = {}


class IndexConfig(_Frozen):
    id: uuid.UUID
    name: str
    embedding_model: Model
    chunk_size: int
    chunk_overlap: int
    vector_store: VectorStore
    distance: Distance
    batch_size: int


class RetrievalConfig(_Frozen):
    id: uuid.UUID
    name: str
    top_k: int
    score_threshold: Decimal
    query_expansion: bool
    per_query_top: int
    min_score: Decimal


class Field(_Frozen):
    id: uuid.UUID
    key: str
    label: str
    description: str | None = None
    value_type: ValueType
    # Catalogue type, e.g. "object: rate, cap", and its JSON Schema ({} = any value).
    type_spec: str | None = None
    value_schema: dict[str, Any] = {}
    priority: Priority = Priority.P2
    # Hand-written instructions; None uses the generic template (extraction.prompts).
    user_prompt: str | None = None
    position: int
    queries: tuple[str, ...] = ()


class ContractTypeField(_Frozen):
    key: str
    # Group the field is listed under for this type: core, commercial, ..., or specific.
    group: str
    priority: Priority


class ContractType(_Frozen):
    id: uuid.UUID
    key: str
    label: str
    description: str
    is_fallback: bool = False
    fields: tuple[ContractTypeField, ...]


class FieldSet(_Frozen):
    id: uuid.UUID
    name: str
    version: int
    fields: tuple[Field, ...]
    contract_types: tuple[ContractType, ...] = ()

    @property
    def fallback_type(self) -> ContractType | None:
        return next((t for t in self.contract_types if t.is_fallback), None)

    def fields_for_types(self, type_keys: list[str] | tuple[str, ...], min_priority: Priority = Priority.P3) -> tuple[Field, ...]:
        """The union of the fields the given contract types expect, most important first.

        No types: the fallback type's fields, or every field when the set defines no types.
        A field's priority is the highest it has among the given types; ties keep the field-set order.
        Fields less important than ``min_priority`` are left out.
        """
        types = {t.key: t for t in self.contract_types}
        unknown = [k for k in type_keys if k not in types]
        if unknown:
            raise ValueError(f"Unknown contract type(s) {unknown}; known: {sorted(types)}")
        chosen = [types[k] for k in type_keys] or ([self.fallback_type] if self.fallback_type else [])
        if chosen:
            priority: dict[str, Priority] = {}
            for t in chosen:
                for member in t.fields:
                    priority[member.key] = min(priority.get(member.key, member.priority), member.priority)
        else:
            priority = {f.key: f.priority for f in self.fields}
        selected = [f for f in self.fields if f.key in priority and priority[f.key] <= min_priority]
        return tuple(sorted(selected, key=lambda f: (priority[f.key], f.position)))


class PipelineConfig(_Frozen):
    id: uuid.UUID
    name: str
    decomposition: DecompositionConfig
    index: IndexConfig
    field_set: FieldSet
    extraction_profile: ModelProfile
    extraction_prompt: Prompt
    judge_enabled: bool
    judge_profile: ModelProfile | None = None
    judge_prompt: Prompt | None = None
    judge_parallel: bool = False
    # Detect the contract type(s) first and extract only their fields (off: the fallback type's fields).
    classification_enabled: bool = False
    classification_profile: ModelProfile | None = None
    classification_prompt: Prompt | None = None
    classification_pages: int = 3
    classification_min_confidence: Decimal = Decimal("0.5")
    # Lowest field priority extracted (P3 = all fields).
    min_priority: Priority = Priority.P3
    # In priority order: the first entry's answer is preferred.
    retrievals: tuple[RetrievalConfig, ...]

    def snapshot(self) -> dict[str, Any]:
        """JSON-ready copy stored with each run (no secrets: providers only name their key's env var)."""
        return self.model_dump(mode="json")
