"""Gateway application: the single entry point in front of the backend API.

* ``/api/v1/*`` (all methods) is streamed to the backend; every other path is 404.
* ``GET /health``: the gateway plus the backend's liveness (200, or 503 with components).
* CORS for the configured origins; request ids, ``nosniff`` and one access-log line on every response.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

import httpx
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .headers import REQUEST_ID, request_id
from .proxy import forward, problem
from .settings import Settings, load_settings

log = logging.getLogger("contract_gateway")

API_PREFIX = "/api/v1"
METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


class RequestContext:
    """Outermost middleware: request id in ``scope['state']``, response headers on every response, access log."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = next((v.decode("latin-1") for k, v in scope["headers"] if k == REQUEST_ID.encode()), None)
        rid = request_id(incoming)
        scope.setdefault("state", {})["request_id"] = rid
        started, status = time.perf_counter(), 500

        async def send_with_headers(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in (b"x-request-id", b"x-content-type-options")]
                message["headers"] = headers + [(b"x-request-id", rid.encode()), (b"x-content-type-options", b"nosniff")]
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            log.info("%s %s %d %.0fms rid=%s", scope["method"], scope["path"], status,
                     (time.perf_counter() - started) * 1000, rid)


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> Starlette:
    settings = settings or load_settings()
    up = settings.upstream

    @asynccontextmanager
    async def lifespan(app: Starlette):
        timeout = httpx.Timeout(connect=up.connect_timeout, read=up.read_timeout, write=up.write_timeout, pool=up.pool_timeout)
        async with httpx.AsyncClient(timeout=timeout, transport=transport, follow_redirects=False) as client:
            app.state.client = client
            yield

    async def proxy(request: Request) -> Response:
        return await forward(request, request.app.state.client, up.url, settings.max_upload_bytes,
                             request.scope["state"]["request_id"])

    async def health(request: Request) -> JSONResponse:
        components = [{"name": "gateway", "ok": True, "detail": "up"}]
        try:
            r = await request.app.state.client.get(f"{up.url.rstrip('/')}{API_PREFIX}/health",
                                                   timeout=settings.gateway.health_timeout_seconds,
                                                   headers={"x-request-id": request.scope["state"]["request_id"]})
            ok = r.status_code == 200
            components.append({"name": "backend", "ok": ok, "detail": f"{up.url} answered {r.status_code}"})
        except httpx.HTTPError as exc:
            components.append({"name": "backend", "ok": False, "detail": f"{up.url} unreachable ({exc.__class__.__name__})"})
        healthy = all(c["ok"] for c in components)
        return JSONResponse({"status": "ok" if healthy else "degraded", "components": components},
                            status_code=200 if healthy else 503)

    async def http_error(request: Request, exc: HTTPException) -> Response:
        return problem(exc.status_code, exc.detail if exc.status_code != 404 else "No such endpoint")

    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route(API_PREFIX + "/{path:path}", proxy, methods=METHODS),
        ],
        middleware=[
            Middleware(RequestContext),
            Middleware(CORSMiddleware, allow_origins=settings.gateway.cors_origins, allow_methods=METHODS,
                       allow_headers=["*"], expose_headers=["Location", "X-Request-ID"], allow_credentials=False),
        ],
        exception_handlers={HTTPException: http_error},
        lifespan=lifespan,
    )
