"""HTTP API against the test database; runs are executed with the worker and scripted models."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, update

from contract_extraction.api.app import create_app
from contract_extraction.core.settings import StorageSettings
from contract_extraction.persistence import models as m
from contract_extraction.worker import Worker
from helpers import BODY, make_pdf
from test_executor import Harness

PROBLEM = "application/problem+json"


@pytest.fixture(autouse=True)
def empty_queue(db):
    with db.session() as s:
        s.execute(update(m.Run).where(m.Run.state.in_(["queued", "running"])).values(state="cancelled", finished_at=func.now()))


@pytest.fixture
def harness(db, storage, tmp_path):
    return Harness(db, storage, tmp_path, "api")


@pytest.fixture
def client(db, storage, harness):
    with TestClient(create_app(harness.settings, db, storage)) as c:
        yield c


def _upload(client, path, name="contract.pdf"):
    with open(path, "rb") as fh:
        return client.post("/api/v1/documents", files={"file": (name, fh, "application/pdf")})


def _run_options(**extra):
    return {"fields": ["customer_name", "payment_terms"], "retrievals": ["RAG01", "RAG07"], **extra}


def _process(db, storage, harness):
    """Execute queued runs like a worker would, with the scripted models (thresholds loosened as in test_executor)."""
    from contract_extraction.persistence.repositories import RunRepo

    with db.session() as s:
        for run in RunRepo(s).list(state="queued")[0]:
            snap = dict(run.config_snapshot)
            snap["retrievals"] = [{**r, "score_threshold": "0", "min_score": "0"} for r in snap["retrievals"]]
            run.config_snapshot = snap
    return Worker(db, storage, harness.settings, harness.providers, worker_id="api-test").run_once()


def test_upload_and_dedupe(client, harness):
    first = _upload(client, harness.pdf)
    assert first.status_code == 201, first.text
    doc = first.json()
    assert first.headers["Location"] == f"/api/v1/documents/{doc['id']}"
    assert doc["code"].startswith("DOC") and doc["original_filename"] == "contract.pdf" and doc["latest_run"] is None
    assert "storage_path" not in doc

    again = _upload(client, harness.pdf, "copy.pdf")
    assert again.status_code == 200 and again.json()["id"] == doc["id"]


def test_upload_rejects_bad_files(client, harness, tmp_path):
    not_pdf = tmp_path / "notes.pdf"
    not_pdf.write_text("hello")
    r = _upload(client, not_pdf)
    assert r.status_code == 422 and r.headers["content-type"] == PROBLEM
    assert r.json()["title"] == "Unprocessable Content" and "not a PDF" in r.json()["detail"]

    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    assert _upload(client, empty).status_code == 422


def test_upload_too_large(db, storage, harness, tmp_path):
    settings = harness.settings.model_copy(update={"storage": StorageSettings(root=str(storage.root), max_upload_mb=1)})
    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF-" + b"0" * (2 * 1024 * 1024))
    with TestClient(create_app(settings, db, storage)) as c:
        r = _upload(c, big)
    assert r.status_code == 413 and r.headers["content-type"] == PROBLEM


def test_run_lifecycle_and_results(client, db, storage, harness):
    doc = _upload(client, harness.pdf).json()
    created = client.post(f"/api/v1/documents/{doc['id']}/runs", json=_run_options())
    assert created.status_code == 202, created.text
    run = created.json()
    assert created.headers["Location"] == f"/api/v1/runs/{run['id']}"
    assert run["state"] == "queued" and run["pipeline"] == "default" and run["options"]["fields"] == ["customer_name", "payment_terms"]

    conflict = client.post(f"/api/v1/documents/{doc['id']}/runs", json=_run_options())
    assert conflict.status_code == 409 and conflict.headers["content-type"] == PROBLEM

    assert _process(db, storage, harness) is not None
    detail = client.get(f"/api/v1/runs/{run['id']}").json()
    assert detail["state"] == "succeeded" and detail["progress_done"] == detail["progress_total"] == 4

    events = client.get(f"/api/v1/runs/{run['id']}/events").json()
    assert events[0]["message"].startswith("Run started")
    newer = client.get(f"/api/v1/runs/{run['id']}/events", params={"after": events[2]["id"]}).json()
    assert [e["id"] for e in newer] == [e["id"] for e in events[3:]]

    results = client.get(f"/api/v1/runs/{run['id']}/results").json()
    best = {b["field_key"]: b for b in results["best"]}
    assert best["customer_name"]["value"] == "Acme Pty Ltd" and best["customer_name"]["verdict"] == "PASS"
    assert [r["retrieval_config"] for r in results["results"]] == ["RAG01", "RAG01", "RAG07", "RAG07"]

    original = client.get(f"/api/v1/runs/{run['id']}/results/{best['customer_name']['field_result_id']}").json()
    assert original["hits"] and original["hits"][0]["text"] and original["reused_from"] is None
    assert [c["purpose"] for c in original["llm_calls"]] == ["extraction", "judge"]
    assert original["llm_calls"][0]["user_prompt"].endswith(">>>") and original["judgements"][0]["verdict"] == "PASS"

    reused_id = next(r["id"] for r in results["results"] if r["retrieval_config"] == "RAG07" and r["field_key"] == "customer_name")
    reused = client.get(f"/api/v1/runs/{run['id']}/results/{reused_id}").json()
    assert reused["reused_from"] == original["id"] and len(reused["llm_calls"]) == 2

    listed = client.get("/api/v1/documents").json()
    assert listed["total"] >= 1 and any(d["id"] == doc["id"] and d["latest_run"]["state"] == "succeeded" for d in listed["items"])
    runs = client.get("/api/v1/runs", params={"document_id": doc["id"]}).json()
    assert runs["total"] == 1 and runs["items"][0]["id"] == run["id"]


def test_document_detail_file_pages_and_images(client, db, storage, harness):
    doc = _upload(client, harness.pdf).json()
    client.post(f"/api/v1/documents/{doc['id']}/runs", json=_run_options(kind="decompose"))
    _process(db, storage, harness)

    detail = client.get(f"/api/v1/documents/{doc['id']}").json()
    assert detail["page_count"] == 3 and len(detail["runs"]) == 1 and detail["decompositions"][0]["method"] == "pymupdf"

    pdf = client.get(f"/api/v1/documents/{doc['id']}/file")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-") and pdf.headers["content-type"] == "application/pdf"

    pages = client.get(f"/api/v1/documents/{doc['id']}/pages").json()
    assert [p["page_number"] for p in pages["pages"]] == [1, 2, 3]
    image = pages["pages"][1]["images"][0]
    img = client.get(image["url"])
    assert img.status_code == 200 and img.content


def test_cancel(client, harness):
    doc = _upload(client, harness.pdf).json()
    run = client.post(f"/api/v1/documents/{doc['id']}/runs", json=_run_options()).json()
    cancelled = client.post(f"/api/v1/runs/{run['id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled"
    assert client.post(f"/api/v1/runs/{run['id']}/cancel").status_code == 409


def test_errors_are_problem_details(client, harness):
    missing = client.get("/api/v1/documents/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404 and missing.headers["content-type"] == PROBLEM and missing.json()["status"] == 404

    doc = _upload(client, harness.pdf).json()
    bad_field = client.post(f"/api/v1/documents/{doc['id']}/runs", json={"fields": ["nope"]})
    assert bad_field.status_code == 422 and "Unknown field" in bad_field.json()["detail"]

    bad_body = client.post(f"/api/v1/documents/{doc['id']}/runs", json={"kind": "bogus", "extra": 1})
    assert bad_body.status_code == 422 and {tuple(e["loc"]) for e in bad_body.json()["errors"]} >= {("body", "kind"), ("body", "extra")}

    assert client.get("/api/v1/nowhere").status_code == 404
    assert client.get("/api/v1/runs/not-a-uuid").status_code == 422


def test_health(client, harness, monkeypatch):
    live = client.get("/api/v1/health")
    assert live.status_code == 200 and live.json()["status"] == "ok"

    from contract_extraction import health

    monkeypatch.setattr(health.QdrantStore, "ping", lambda self: (_ for _ in ()).throw(health.ProviderError("down")))
    ready = client.get("/api/v1/health/ready")
    body = ready.json()
    assert ready.status_code == 503 and body["status"] == "degraded"
    assert {c["name"]: c["ok"] for c in body["components"]}["qdrant"] is False


def test_config_endpoints(client):
    pipelines = client.get("/api/v1/config/pipelines").json()
    default = next(p for p in pipelines if p["is_default"])
    assert [r["name"] for r in default["retrievals"]] == [f"RAG0{i}" for i in range(1, 8)]
    assert len(default["fields"]) == 12 and default["judge"]["temperature"] == "0.100"
    providers = {p["key"]: p for p in client.get("/api/v1/config/providers").json()}
    assert providers["openrouter"]["api_key_env"] == "OPENROUTER_API_KEY" and providers["ollama-local"]["models"]


def test_request_id_and_openapi(client):
    r = client.get("/api/v1/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"
    assert client.get("/api/v1/health").headers["X-Request-ID"]

    spec = client.get("/api/v1/openapi.json").json()
    operation_ids = {op["operationId"] for path in spec["paths"].values() for op in path.values()}
    assert operation_ids == {
        "health", "health_ready", "list_pipelines", "list_providers", "upload_document", "list_documents",
        "get_document", "get_document_file", "get_pages", "get_image", "create_run", "list_runs", "get_run",
        "cancel_run", "list_run_events", "get_run_results", "get_field_result",
        "list_ground_truth", "set_ground_truth", "delete_ground_truth",
    }


def test_ground_truth_and_evaluation(client, db, storage, harness):
    doc = _upload(client, harness.pdf).json()
    base = f"/api/v1/documents/{doc['id']}/ground-truth"
    listed = client.get(base).json()
    assert (listed["field_set"]["name"], listed["field_set"]["version"]) == ("contract_fields", 1)
    assert len(listed["items"]) == 12 and all(i["expected_value"] is None and i["updated_at"] is None for i in listed["items"])
    fields = {i["field_key"]: i["field_id"] for i in listed["items"]}

    put = client.put(f"{base}/{fields['customer_name']}", json={"expected_value": "acme pty ltd", "notes": "preamble"})
    assert put.status_code == 200, put.text
    assert put.json()["expected_value"] == "acme pty ltd" and put.json()["notes"] == "preamble" and put.json()["updated_at"]
    assert client.put(f"{base}/{fields['payment_terms']}", json={"expected_value": "60 days"}).status_code == 200

    null = client.put(f"{base}/{fields['payment_terms']}", json={"expected_value": None})
    assert null.status_code == 422 and null.headers["content-type"] == PROBLEM and "must not be null" in null.json()["detail"]
    assert client.put(f"{base}/{fields['payment_terms']}", json={"notes": "x"}).status_code == 422
    assert client.put(f"{base}/{doc['id']}", json={"expected_value": "x"}).status_code == 404
    unknown_doc = f"/api/v1/documents/{fields['customer_name']}/ground-truth"
    assert client.get(unknown_doc).status_code == 404

    client.post(f"/api/v1/documents/{doc['id']}/runs", json=_run_options())
    _process(db, storage, harness)
    run_id = client.get("/api/v1/runs", params={"document_id": doc["id"]}).json()["items"][0]["id"]
    results = client.get(f"/api/v1/runs/{run_id}/results").json()
    best = {b["field_key"]: b for b in results["best"]}
    assert best["customer_name"]["field_id"] == fields["customer_name"]
    assert (best["customer_name"]["expected_value"], best["customer_name"]["exact_match"]) == ("acme pty ltd", True)
    assert (best["payment_terms"]["expected_value"], best["payment_terms"]["exact_match"]) == ("60 days", False)
    assert results["evaluation"] == {"fields": 2, "labelled": 2, "matched": 1}

    assert client.delete(f"{base}/{fields['payment_terms']}").status_code == 204
    assert client.delete(f"{base}/{fields['payment_terms']}").status_code == 404
    results = client.get(f"/api/v1/runs/{run_id}/results").json()
    assert results["evaluation"] == {"fields": 2, "labelled": 1, "matched": 1}
    assert next(b for b in results["best"] if b["field_key"] == "payment_terms")["exact_match"] is None
