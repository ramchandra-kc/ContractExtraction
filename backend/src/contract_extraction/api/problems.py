"""Error responses as RFC 9457 Problem Details (``application/problem+json``), for every error."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..core.errors import AppError, Conflict, InvalidConfig, InvalidInput, NotFound, PayloadTooLarge

log = logging.getLogger(__name__)

MEDIA_TYPE = "application/problem+json"

# Most specific first.
_STATUS: list[tuple[type[AppError], int]] = [
    (PayloadTooLarge, 413),
    (NotFound, 404),
    (Conflict, 409),
    (InvalidInput, 422),
    (InvalidConfig, 422),
]


def problem(status: int, detail: str | None = None, errors: list[dict[str, Any]] | None = None,
            headers: dict[str, str] | None = None) -> JSONResponse:
    body: dict[str, Any] = {"type": "about:blank", "title": HTTPStatus(status).phrase, "status": status}
    if detail:
        body["detail"] = detail
    if errors:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type=MEDIA_TYPE, headers=headers)


def status_for(exc: AppError) -> int:
    return next((code for cls, code in _STATUS if isinstance(exc, cls)), 400)


def install(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    def app_error(request: Request, exc: AppError) -> JSONResponse:
        return problem(status_for(exc), str(exc))

    @app.exception_handler(RequestValidationError)
    def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")} for e in exc.errors()]
        return problem(422, "The request is not valid", errors)

    @app.exception_handler(StarletteHTTPException)
    def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return problem(exc.status_code, exc.detail if isinstance(exc.detail, str) else None, headers=exc.headers)

    @app.exception_handler(Exception)
    def unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return problem(500, "Internal error; see the server log")
