"""Runs: list, detail, cancel, timeline and results."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...domain.enums import RunState
from ...persistence import models as m
from ...persistence.repositories import RunRepo
from ...persistence.repositories.results import Outcome, ResultRepo
from ..deps import get_session
from ..schemas import (
    BestValue,
    EvaluationOut,
    EventOut,
    FieldResultDetail,
    FieldResultOut,
    HitOut,
    JudgementOut,
    LlmCallOut,
    Page,
    RunOut,
    RunResults,
    RunSummary,
)

router = APIRouter(prefix="/runs", tags=["runs"])


def run_out(run: m.Run) -> RunOut:
    return RunOut.model_validate({
        **RunSummary.model_validate(run).model_dump(),
        "pipeline": run.config_snapshot.get("name"), "options": run.options, "worker_id": run.worker_id,
        "heartbeat_at": run.heartbeat_at, "cancel_requested": run.cancel_requested, "attempts": run.attempts,
        "decomposition_id": run.decomposition_id, "vector_index_id": run.vector_index_id,
    })


def _outcome_out(o: Outcome) -> dict:
    j = o.judgement
    return {"id": o.result.id, "field_key": o.field.key, "field_label": o.field.label,
            "retrieval_config": o.retrieval_config, "status": o.result.status, "value": o.result.value,
            "error": o.result.error, "extraction_ms": o.result.extraction_ms, "verdict": j.verdict if j else None,
            "issue": j.issue if j else None, "created_at": o.result.created_at}


@router.get("", response_model=Page[RunSummary])
def list_runs(session: Session = Depends(get_session), state: RunState | None = None,
              document_id: uuid.UUID | None = None, limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0)):
    """Newest first."""
    rows, total = RunRepo(session).list(state, document_id, limit, offset)
    return Page[RunSummary](items=[RunSummary.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: uuid.UUID, session: Session = Depends(get_session)):
    return run_out(RunRepo(session).get(run_id))


@router.post("/{run_id}/cancel", response_model=RunOut)
def cancel_run(run_id: uuid.UUID, session: Session = Depends(get_session)):
    """Queued: cancelled at once. Running: stops before its next field. Finished: 409."""
    return run_out(RunRepo(session).cancel(run_id))


@router.get("/{run_id}/events", response_model=list[EventOut])
def list_run_events(run_id: uuid.UUID, after: int | None = Query(None, description="Only events with a larger id"),
                    session: Session = Depends(get_session)):
    """The run's timeline; poll with ``after`` set to the last id received."""
    RunRepo(session).get(run_id)
    return RunRepo(session).events(run_id, after)


@router.get("/{run_id}/results", response_model=RunResults)
def get_run_results(run_id: uuid.UUID, session: Session = Depends(get_session)):
    """Best value per field plus every outcome per RAG config (partial while the run is going)."""
    run = RunRepo(session).get(run_id)
    repo = ResultRepo(session)
    order = {r["name"]: i for i, r in enumerate(run.config_snapshot.get("retrievals", []))}
    outcomes = sorted(repo.outcomes(run.id), key=lambda o: (order.get(o.retrieval_config, 99), o.field.position))
    best = [BestValue(field_id=b["field_id"], field_key=b["field_key"], field_label=b["field_label"],
                      value_type=b["value_type"], value=b["value"],
                      status=b["status"], retrieval_config=b["retrieval_config"], verdict=b["verdict"], issue=b["issue"],
                      explanation=b["explanation"], field_result_id=b["field_result_id"],
                      expected_value=b["expected_value"], exact_match=b["exact_match"])
            for b in repo.best_values(run.id)]
    evaluation = EvaluationOut(fields=len(best), labelled=sum(b.exact_match is not None for b in best),
                               matched=sum(b.exact_match is True for b in best))
    return RunResults(run=run_out(run), best=best, evaluation=evaluation,
                      results=[FieldResultOut(**_outcome_out(o)) for o in outcomes])


@router.get("/{run_id}/results/{field_result_id}", response_model=FieldResultDetail)
def get_field_result(run_id: uuid.UUID, field_result_id: uuid.UUID, session: Session = Depends(get_session)):
    """Evidence, LLM calls (for a reused result: those of the original) and judgements of one outcome."""
    repo = ResultRepo(session)
    o = repo.outcome(run_id, field_result_id)
    return FieldResultDetail(
        **_outcome_out(o),
        raw_answer=o.result.raw_answer,
        reused_from=repo.reused_from(field_result_id),
        hits=[HitOut(rank=h.rank, score=h.score, page=c.page_start, matched_query=h.matched_query, chunk_id=c.id, text=c.text)
              for h, c in repo.evidence(field_result_id)],
        llm_calls=[LlmCallOut.model_validate(c) for c in repo.llm_calls(field_result_id)],
        judgements=[JudgementOut.model_validate(j) for j in repo.judgements(field_result_id)],
    )
