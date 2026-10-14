"""Streaming forward of one request to the backend.

The request body is streamed upstream (never buffered) through a byte counter that enforces
the upload limit; the response is streamed back as raw bytes (content encoding untouched) and
the upstream connection is closed when the client finishes or disconnects.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from http import HTTPStatus

import httpx
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from .headers import downstream_response_headers, upstream_request_headers

log = logging.getLogger(__name__)

PROBLEM = "application/problem+json"


class BodyTooLarge(Exception):
    pass


def problem(status: int, detail: str | None = None) -> JSONResponse:
    body = {"type": "about:blank", "title": HTTPStatus(status).phrase, "status": status}
    if detail:
        body["detail"] = detail
    return JSONResponse(body, status_code=status, media_type=PROBLEM)


async def _limited(stream: AsyncIterator[bytes], limit: int) -> AsyncIterator[bytes]:
    seen = 0
    async for chunk in stream:
        seen += len(chunk)
        if seen > limit:
            raise BodyTooLarge
        yield chunk


def _has_body(request: Request) -> bool:
    return "content-length" in request.headers or "chunked" in request.headers.get("transfer-encoding", "").lower()


async def forward(request: Request, client: httpx.AsyncClient, upstream: str, max_bytes: int, rid: str) -> Response:
    too_large = problem(413, f"Request body exceeds the {max_bytes // (1024 * 1024)} MB limit")
    length = request.headers.get("content-length")
    if length is not None:
        if not length.isdigit():
            return problem(400, "Invalid Content-Length")
        if int(length) > max_bytes:
            return too_large  # rejected before the backend is contacted

    # Original path and query bytes, so percent-encoding (e.g. %2F) reaches the backend unchanged.
    raw = request.scope.get("raw_path") or request.url.path.encode()
    query = request.scope.get("query_string") or b""
    url = httpx.URL(upstream).copy_with(raw_path=raw + (b"?" + query if query else b""))
    client_host = request.client.host if request.client else None
    headers = upstream_request_headers(list(request.headers.items()), client_host, request.url.scheme,
                                       request.headers.get("host"), rid)
    content = _limited(request.stream(), max_bytes) if _has_body(request) else None
    outgoing = client.build_request(request.method, url, headers=headers, content=content)

    try:
        response = await client.send(outgoing, stream=True)
    except BodyTooLarge:
        return too_large
    except httpx.TimeoutException as exc:
        log.warning("Upstream timeout (%s) for %s %s rid=%s", exc.__class__.__name__, request.method, request.url.path, rid)
        return problem(504, "The backend did not respond in time")
    except httpx.TransportError as exc:
        if isinstance(exc.__cause__ or exc.__context__, BodyTooLarge):
            return too_large
        log.warning("Upstream unreachable (%s) for %s %s rid=%s", exc, request.method, request.url.path, rid)
        return problem(502, "The backend is not reachable")

    out = StreamingResponse(response.aiter_raw(), status_code=response.status_code, background=BackgroundTask(response.aclose))
    out.raw_headers = [(k.encode("latin-1"), v.encode("latin-1"))
                       for k, v in downstream_response_headers(list(response.headers.multi_items()))]
    return out
