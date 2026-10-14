"""Health: liveness (cheap, for the gateway) and readiness (services and models)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ...core.settings import Settings
from ...health import Component, liveness, readiness
from ...persistence.db import Database
from ..deps import get_db, get_settings
from ..schemas import ComponentOut, HealthOut

router = APIRouter(prefix="/health", tags=["system"])

_RESPONSES = {503: {"model": HealthOut, "description": "A component is not available"}}


def _report(components: list[Component]) -> JSONResponse:
    ok = all(c.ok for c in components)
    body = HealthOut(status="ok" if ok else "degraded", components=[ComponentOut.model_validate(c) for c in components])
    return JSONResponse(body.model_dump(), status_code=200 if ok else 503)


@router.get("", response_model=HealthOut, responses=_RESPONSES)
def health(db: Database = Depends(get_db)):
    """Liveness: the API process is up and can reach the database."""
    return _report(liveness(db))


@router.get("/ready", response_model=HealthOut, responses=_RESPONSES)
def health_ready(db: Database = Depends(get_db), settings: Settings = Depends(get_settings)):
    """Readiness: schema, default pipeline, vector store and model endpoints."""
    components, _ = readiness(db, settings)
    return _report(components)
