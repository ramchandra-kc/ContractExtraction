"""Header rules for a proxy at the edge (RFC 9110 §7.6.1).

* Hop-by-hop headers (and any listed in ``Connection``) apply to one connection only and are
  never forwarded, in either direction.
* The gateway is the edge, so forwarding headers sent by the client cannot be trusted: they are
  removed and set from what the gateway itself observed.
* Request ids are accepted only in a safe shape; anything else is replaced.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable

HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "proxy-connection",
    "te", "trailer", "trailers", "transfer-encoding", "upgrade",
})
FORWARDING = frozenset({"forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-port", "x-forwarded-proto", "x-real-ip"})
REQUEST_ID = "x-request-id"
_REQUEST_ID_SHAPE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def request_id(value: str | None) -> str:
    """The client's id when it is safe to log, else a new one."""
    return value if value and _REQUEST_ID_SHAPE.match(value) else uuid.uuid4().hex


def _connection_tokens(headers: Iterable[tuple[str, str]]) -> set[str]:
    return {t.strip().lower() for k, v in headers if k.lower() == "connection" for t in v.split(",") if t.strip()}


def _strip(headers: list[tuple[str, str]], also: Iterable[str]) -> list[tuple[str, str]]:
    drop = HOP_BY_HOP | _connection_tokens(headers) | set(also)
    return [(k, v) for k, v in headers if k.lower() not in drop]


def upstream_request_headers(headers: list[tuple[str, str]], client_host: str | None, scheme: str, host: str | None,
                             rid: str) -> list[tuple[str, str]]:
    """Headers for the backend: hop-by-hop, client forwarding headers, Host and request id removed, then set by us."""
    out = _strip(headers, FORWARDING | {"host", REQUEST_ID})
    if client_host:
        out.append(("x-forwarded-for", client_host))
    out.append(("x-forwarded-proto", scheme))
    if host:
        out.append(("x-forwarded-host", host))
    out.append(("x-request-id", rid))
    return out


def downstream_response_headers(headers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Headers for the client: hop-by-hop and the backend's Server removed. The request id and
    nosniff are set on every response (proxied or not) by the app's middleware, so they are dropped here."""
    return _strip(headers, {"server", REQUEST_ID, "x-content-type-options"})
