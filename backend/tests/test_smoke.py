"""End to end against the running dev stack (scripts/dev.sh): CE_SMOKE=1 uv run pytest -m smoke -s

Black box over HTTP, the way the browser goes: frontend (Vite) → gateway → API → Postgres queue → worker → models.
It uses no database fixtures. It leaves one document (always the same PDF, cached in .dev/smoke.pdf) and its runs in the
dev database. A narrow run (one field, one RAG config, judge on) takes about 30 s with native Ollama.

CE_GATEWAY_URL (http://127.0.0.1:8080), CE_FRONTEND_URL (http://localhost:5173), CE_SMOKE_TIMEOUT (600 s),
CE_SMOKE_FIELD (customer_name) and CE_SMOKE_RETRIEVAL (RAG02) override the defaults.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import httpx
import pytest

from helpers import make_pdf

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(not os.getenv("CE_SMOKE"), reason="set CE_SMOKE=1 to run against the running dev stack"),
]

GATEWAY = os.getenv("CE_GATEWAY_URL", "http://127.0.0.1:8080").rstrip("/")
FRONTEND = os.getenv("CE_FRONTEND_URL", "http://localhost:5173").rstrip("/")
TIMEOUT = float(os.getenv("CE_SMOKE_TIMEOUT", "600"))
FIELD = os.getenv("CE_SMOKE_FIELD", "customer_name")
RETRIEVAL = os.getenv("CE_SMOKE_RETRIEVAL", "RAG02")
# make_pdf writes a new trailer id every time, so the PDF is generated once and reused: the same bytes are the same document.
PDF = Path(__file__).resolve().parents[2] / ".dev" / "smoke.pdf"


@pytest.fixture(scope="module")
def api():
    with httpx.Client(base_url=f"{GATEWAY}/api/v1", timeout=30) as client:
        yield client


def test_gateway_health_and_request_id():
    request_id = f"smoke-{uuid.uuid4().hex[:12]}"
    r = httpx.get(f"{GATEWAY}/health", headers={"X-Request-ID": request_id}, timeout=10)
    assert r.status_code == 200, r.text
    assert r.headers["x-request-id"] == request_id
    assert {c["name"] for c in r.json()["components"]} == {"gateway", "backend"}


def test_frontend_and_its_proxy():
    assert httpx.get(f"{FRONTEND}/", timeout=10).status_code == 200
    r = httpx.get(f"{FRONTEND}/api/v1/health", timeout=10)
    assert r.status_code == 200, f"Vite → gateway proxy: {r.status_code} {r.text}"


def test_upload_run_results(api):
    if not PDF.exists():
        PDF.parent.mkdir(parents=True, exist_ok=True)
        make_pdf(PDF)
    with PDF.open("rb") as fh:
        r = api.post("/documents", files={"file": ("smoke.pdf", fh, "application/pdf")})
    assert r.status_code in (200, 201), r.text
    doc = r.json()

    active = [run for run in api.get(f"/documents/{doc['id']}").json()["runs"] if run["state"] in ("queued", "running")]
    if active:
        pytest.fail(f"{doc['code']} already has an active run {active[0]['id']} ({active[0]['state']}); wait for it, or "
                    f"cancel it: uv run contract-extraction cancel {active[0]['id']}")

    r = api.post(f"/documents/{doc['id']}/runs", json={"fields": [FIELD], "retrievals": [RETRIEVAL], "judge": True})
    assert r.status_code == 202, r.text
    assert r.headers["location"] == f"/api/v1/runs/{r.json()['id']}"
    run_id = r.json()["id"]

    deadline = time.monotonic() + TIMEOUT
    while (run := api.get(f"/runs/{run_id}").json())["state"] in ("queued", "running"):
        if time.monotonic() > deadline:
            pytest.fail(f"run {run_id} still {run['state']} ({run['stage']}) after {TIMEOUT:.0f}s; is a worker running?")
        time.sleep(2)
    assert run["state"] == "succeeded", f"run {run_id} ended {run['state']}: {run['error']}"

    assert api.get(f"/runs/{run_id}/events").json(), "the run has no events"
    results = api.get(f"/runs/{run_id}/results").json()
    [best] = results["best"]
    assert best["field_key"] == FIELD
    assert best["status"] != "error", best
    detail = api.get(f"/runs/{run_id}/results/{best['field_result_id']}").json()
    assert detail["hits"], "the result has no evidence"
    assert detail["llm_calls"], "the result has no LLM calls"

    print(f"\n{doc['code']} run {run_id}: {FIELD} = {best['value']!r} ({best['status']}, verdict {best['verdict']}; "
          f"the PDF names 'Acme Pty Ltd')")
