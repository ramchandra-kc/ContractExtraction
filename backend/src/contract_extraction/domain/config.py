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
    Anchor,
    DecompositionMethod,
    Distance,
    Granularity,
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
    timeout_seconds: int = 180
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
    # Also search by keyword (BM25) and fuse the rankings (extraction.retrieval).
    keyword_search: bool = False
    # Opening/closing chunks added for fields with an anchor (0 = off).
    anchor_chunks: int = 0


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
    # Evidence always includes the document's opening/closing chunks (RetrievalConfig.anchor_chunks).
    anchor: Anchor | None = None


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

    def batches(self, fields: tuple[Field, ...], type_keys: list[str] | tuple[str, ...],
                max_fields: int) -> list[tuple[str, tuple[Field, ...]]]:
        """``fields`` split into named batches for group extraction, at most ``max_fields`` each.

        A field's group is the one it is listed under in the first of ``type_keys`` (then the fallback
        type, then any type) that has it: a shared group such as ``core``, or ``<type>`` for the type's
        own fields. Groups come in the order of their first field; fields keep their order.
        """
        types = {t.key: t for t in self.contract_types}
        order = [types[k] for k in type_keys if k in types]
        order += [t for t in ([self.fallback_type] if self.fallback_type else []) + list(self.contract_types) if t not in order]
        groups: dict[str, list[Field]] = {}
        for f in fields:
            member = next(((t, mb) for t in order for mb in t.fields if mb.key == f.key), None)
            name = "fields" if member is None else (member[0].key if member[1].group == "specific" else member[1].group)
            groups.setdefault(name, []).append(f)
        out: list[tuple[str, tuple[Field, ...]]] = []
        for name, members in groups.items():
            parts = [tuple(members[i:i + max_fields]) for i in range(0, len(members), max_fields)]
            out += [(name if len(parts) == 1 else f"{name} {n}/{len(parts)}", part) for n, part in enumerate(parts, start=1)]
        return out


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
    # One extraction call per field, or per field group of at most group_max_fields fields.
    extraction_granularity: Granularity = Granularity.FIELD
    group_max_fields: int = 8
    # In priority order: the first entry's answer is preferred.
    retrievals: tuple[RetrievalConfig, ...]

    def snapshot(self) -> dict[str, Any]:
        """JSON-ready copy stored with each run (no secrets: providers only name their key's env var)."""
        return self.model_dump(mode="json")
