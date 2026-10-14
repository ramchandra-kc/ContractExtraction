"""Per-run options. Narrowing options are applied to the pipeline before its snapshot is stored,
so the snapshot always describes exactly what the run does."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ..core.errors import InvalidInput
from ..domain.config import PipelineConfig


class RunOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Subset of field keys / RAG config names (None = all from the pipeline).
    fields: list[str] | None = None
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
            raise InvalidInput(f"Unknown field(s) {unknown}; known: {sorted(known)}")
        keep = [f for f in pipeline.field_set.fields if f.key in set(options.fields)]
        update["field_set"] = pipeline.field_set.model_copy(update={"fields": tuple(keep)})
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
