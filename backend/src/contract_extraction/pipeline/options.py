"""Per-run options. Narrowing options are applied to the pipeline before its snapshot is stored,
so the snapshot always describes exactly what the run does."""

from __future__ import annotations

import difflib

from pydantic import BaseModel, ConfigDict

from ..core.errors import InvalidInput
from ..domain.config import PipelineConfig


class RunOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Exactly these field keys (None = the fields of the document's contract types).
    fields: list[str] | None = None
    # Treat the document as these contract types instead of detecting them (ignored when fields is set).
    contract_types: list[str] | None = None
    # Subset of RAG config names (None = all from the pipeline).
    retrievals: list[str] | None = None
    # False turns the judge off for this run; None keeps the pipeline's setting.
    judge: bool | None = None
    # Reuse an earlier answer in the run when a field gets exactly the same context again.
    reuse_calls: bool = True
    # Decompose again even if a decomposition with the same config exists.
    redecompose: bool = False


def narrow(pipeline: PipelineConfig, options: RunOptions) -> PipelineConfig:
    update: dict = {}
    if options.fields is not None:
        known = {f.key: f for f in pipeline.field_set.fields}
        unknown = [k for k in options.fields if k not in known]
        if unknown:
            close = sorted({c for k in unknown for c in difflib.get_close_matches(k, known, n=3)})
            hint = f"; did you mean {close}?" if close else ""
            raise InvalidInput(f"Unknown field(s) {unknown} in field set {pipeline.field_set.name!r} "
                               f"({len(known)} fields){hint}")
        keep = [f for f in pipeline.field_set.fields if f.key in set(options.fields)]
        update["field_set"] = pipeline.field_set.model_copy(update={"fields": tuple(keep)})
    if options.contract_types is not None:
        known_types = {t.key for t in pipeline.field_set.contract_types}
        unknown = [k for k in options.contract_types if k not in known_types]
        if unknown:
            raise InvalidInput(f"Unknown contract type(s) {unknown}; known: {sorted(known_types)}")
        if not options.contract_types:
            raise InvalidInput("No contract types selected")
    if options.retrievals is not None:
        known = {r.name for r in pipeline.retrievals}
        unknown = [n for n in options.retrievals if n not in known]
        if unknown:
            raise InvalidInput(f"Unknown RAG config(s) {unknown}; this pipeline has {sorted(known)}")
        update["retrievals"] = tuple(r for r in pipeline.retrievals if r.name in set(options.retrievals))
    if options.judge is False:
        update |= {"judge_enabled": False, "judge_profile": None, "judge_prompt": None}
    elif options.judge and not pipeline.judge_enabled:
        raise InvalidInput(f"Pipeline {pipeline.name!r} has no judge configured")
    if not (update.get("field_set") or pipeline.field_set).fields:
        raise InvalidInput("No fields selected")
    if not update.get("retrievals", pipeline.retrievals):
        raise InvalidInput("No RAG configs selected")
    return pipeline.model_copy(update=update)
