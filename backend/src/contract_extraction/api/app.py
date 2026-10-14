"""FastAPI application.

The API stores uploads and queues runs; workers execute them (``contract-extraction worker``).
It listens on loopback only and is reached through the gateway, which owns CORS and (later) auth.

    contract-extraction api        # serve on API__HOST:API__PORT
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.routing import APIRoute

from .. import __version__
from ..core.logging import setup_logging
from ..core.settings import Settings, load_settings
from ..persistence.db import Database
from ..storage import FileStorage
from . import problems
from .routes import config, documents, ground_truth, runs, system

API_PREFIX = "/api/v1"
REQUEST_ID = "X-Request-ID"

log = logging.getLogger("contract_extraction.api")


def _operation_id(route: APIRoute) -> str:
    # Stable operationIds (the endpoint function name) for generated client types.
    return route.name


def create_app(settings: Settings | None = None, db: Database | None = None, storage: FileStorage | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owns_db = db is None
        app.state.settings = settings
        app.state.db = db or Database(settings.database)
        app.state.storage = storage or FileStorage(settings.storage_root)
        try:
            yield
        finally:
            if owns_db:
                app.state.db.dispose()

    app = FastAPI(
        title="ContractExtraction API", version=__version__, lifespan=lifespan,
        docs_url=f"{API_PREFIX}/docs", redoc_url=None, openapi_url=f"{API_PREFIX}/openapi.json",
        generate_unique_id_function=_operation_id,
    )
    problems.install(app)

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = request.headers.get(REQUEST_ID) or uuid.uuid4().hex
        started = time.perf_counter()
        response = await call_next(request)
        response.headers[REQUEST_ID] = rid
        log.info("%s %s %d %.0fms rid=%s", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - started) * 1000, rid)
        return response

    for module in (system, config, documents, ground_truth, runs):
        app.include_router(module.router, prefix=API_PREFIX)
    return app


def serve() -> None:
    import uvicorn

    settings = load_settings()
    setup_logging(settings.log_level)
    uvicorn.run(create_app(settings), host=settings.api.host, port=settings.api.port, log_config=None, access_log=False)
