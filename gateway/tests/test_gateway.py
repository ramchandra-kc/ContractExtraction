"""Gateway behaviour against a fake backend (httpx.MockTransport, no network)."""

from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from contract_gateway.app import create_app
from contract_gateway.settings import GatewaySettings, Settings

PROBLEM = "application/problem+json"


def streamed(status: int, body: object, headers: dict | None = None) -> httpx.Response:
    """A response whose body arrives as a stream, like from a real server (a Response built with
    json= is pre-read and could not be streamed through the proxy)."""
    data = json.dumps(body).encode()

    async def chunks():
        yield data

    return httpx.Response(status, headers={"content-type": "application/json", "content-length": str(len(data)),
                                           **(headers or {})}, content=chunks())


class FakeBackend:
    """Records what reached the backend; answers like the real API would."""

    def __init__(self, handler=None):
        self.requests: list[httpx.Request] = []
        self.bodies: list[bytes] = []
        self.handler = handler

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(await request.aread())
        self.requests.append(request)
        if self.handler:
            return self.handler(request)
        if request.url.path == "/api/v1/health":
            return streamed(200, {"status": "ok"})
        return streamed(201, {"echo": request.url.raw_path.decode().split("?")[0]}, {
            "Location": "/api/v1/documents/42", "Server": "uvicorn", "Connection": "keep-alive, X-Secret",
            "X-Secret": "hop", "Set-Cookie": "a=1", "X-Custom": "kept"})


def client_for(backend, **gateway) -> TestClient:
    settings = Settings(gateway=GatewaySettings(**({"max_upload_mb": 1} | gateway)))
    return TestClient(create_app(settings, transport=httpx.MockTransport(backend)))


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def client(backend):
    with client_for(backend) as c:
        yield c


def test_pass_through(client, backend):
    r = client.get("/api/v1/documents/a%2Fb?limit=5&offset=10", headers={"X-Custom-In": "yes", "Connection": "close, X-Drop", "X-Drop": "1"})
    assert r.status_code == 201 and r.json() == {"echo": "/api/v1/documents/a%2Fb"}
    sent = backend.requests[0]
    assert sent.url.raw_path == b"/api/v1/documents/a%2Fb?limit=5&offset=10", "path encoding and query untouched"
    assert sent.url.host == "127.0.0.1" and sent.url.port == 8000
    assert sent.headers["x-custom-in"] == "yes" and "x-drop" not in sent.headers
    assert r.headers["location"] == "/api/v1/documents/42" and r.headers["x-custom"] == "kept"
    assert "server" not in r.headers and "x-secret" not in r.headers, "Server and Connection-listed headers dropped"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_forwarding_headers_are_set_by_the_gateway(client, backend):
    client.get("/api/v1/runs", headers={"X-Forwarded-For": "6.6.6.6", "Forwarded": "for=6.6.6.6", "X-Real-IP": "6.6.6.6"})
    sent = backend.requests[0].headers
    assert sent["x-forwarded-for"] == "testclient" and "6.6.6.6" not in str(dict(sent))
    assert sent["x-forwarded-proto"] == "http" and sent["x-forwarded-host"] == "testserver"


@pytest.mark.parametrize("incoming, kept", [("abc-123.X_y", True), ("bad\nid", False), ("x" * 200, False), (None, False)])
def test_request_id(client, backend, incoming, kept):
    headers = {"X-Request-ID": incoming} if incoming is not None else {}
    r = client.get("/api/v1/runs", headers=headers)
    rid = r.headers["x-request-id"]
    assert (rid == incoming) is kept and len(rid) <= 64
    assert backend.requests[0].headers["x-request-id"] == rid


def test_upload_is_streamed_unchanged(backend):
    payload = bytes(range(256)) * 4096  # 1 MiB
    with client_for(backend, max_upload_mb=5) as c:
        r = c.post("/api/v1/documents", files={"file": ("a.pdf", payload, "application/pdf")})
    assert r.status_code == 201
    assert payload in backend.bodies[0], "multipart body reached the backend byte for byte"


def test_body_over_limit_with_length_never_reaches_backend(client, backend):
    r = client.post("/api/v1/documents", content=b"x" * (1024 * 1024 + 1), headers={"content-type": "application/pdf"})
    assert r.status_code == 413 and r.headers["content-type"] == PROBLEM and "1 MB" in r.json()["detail"]
    assert backend.requests == []


def test_chunked_body_over_limit(client, backend):
    def chunks():
        for _ in range(3):
            yield b"x" * (512 * 1024)

    r = client.post("/api/v1/documents", content=chunks())
    assert r.status_code == 413 and r.headers["content-type"] == PROBLEM


def test_backend_unreachable_is_502(backend):
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    with client_for(FakeBackend(refuse)) as c:
        r = c.get("/api/v1/runs")
    assert r.status_code == 502 and r.headers["content-type"] == PROBLEM and r.json()["title"] == "Bad Gateway"


@pytest.mark.parametrize("error", [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout])
def test_timeouts_are_504(error):
    def slow(request):
        raise error("slow", request=request)

    with client_for(FakeBackend(slow)) as c:
        r = c.get("/api/v1/runs")
    assert r.status_code == 504 and r.json()["status"] == 504


def test_backend_errors_pass_through(backend):
    backend.handler = lambda request: streamed(409, {"title": "Conflict", "status": 409}, {"content-type": PROBLEM})
    with client_for(backend) as c:
        r = c.post("/api/v1/documents/1/runs", json={"fields": ["x"]})
    assert r.status_code == 409 and r.headers["content-type"] == PROBLEM and r.json()["status"] == 409
    assert json.loads(backend.bodies[0]) == {"fields": ["x"]}


def test_cors(client):
    allowed = client.options("/api/v1/documents", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert allowed.status_code == 200 and allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    other = client.options("/api/v1/documents", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in other.headers
    simple = client.get("/api/v1/runs", headers={"Origin": "http://localhost:5173"})
    assert simple.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "location" in simple.headers["access-control-expose-headers"].lower()


def test_only_the_api_is_exposed(client, backend):
    r = client.get("/admin")
    assert r.status_code == 404 and r.headers["content-type"] == PROBLEM and r.headers["x-request-id"]
    assert backend.requests == []


def test_health(backend):
    with client_for(backend) as c:
        ok = c.get("/health")
    assert ok.status_code == 200 and ok.json()["status"] == "ok"

    def down(request):
        raise httpx.ConnectError("refused", request=request)

    with client_for(FakeBackend(down)) as c:
        bad = c.get("/health")
    body = bad.json()
    assert bad.status_code == 503 and body["status"] == "degraded"
    assert {x["name"]: x["ok"] for x in body["components"]} == {"gateway": True, "backend": False}
