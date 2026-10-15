"""Editing configuration over HTTP. Each test runs in the rolled-back test transaction: every request
gets its own savepoint, so a failed request (e.g. a 409) undoes only itself."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from contract_extraction.api.app import create_app
from contract_extraction.api.deps import get_session
from contract_extraction.core.settings import load_settings

PROBLEM = "application/problem+json"
C = "/api/v1/config"


@pytest.fixture
def client(session, db, storage):
    app = create_app(load_settings("test"), db, storage)

    def per_request_savepoint():
        with session.begin_nested():
            yield session

    app.dependency_overrides[get_session] = per_request_savepoint
    with TestClient(app) as c:
        yield c


def catalog(client) -> dict:
    r = client.get(f"{C}/catalog")
    assert r.status_code == 200, r.text
    return r.json()


def pipeline(client, name="default") -> dict:
    return next(p for p in catalog(client)["pipelines"] if p["name"] == name)


def model_id(client, name: str) -> str:
    return next(mm["id"] for p in catalog(client)["providers"] for mm in p["models"] if mm["name"] == name)


def problem(r, status: int, text: str = "") -> dict:
    assert r.status_code == status, r.text
    assert r.headers["content-type"] == PROBLEM
    assert text in (r.json().get("detail") or "") + str(r.json().get("errors", "")), r.json()
    return r.json()


def new_pipeline(client, name="trial", **changes) -> dict:
    d = pipeline(client)
    body = {"name": name, "decomposition": d["decomposition"], "index": d["index"], "field_set": d["field_set"],
            "extraction_profile": d["extraction_profile"], "extraction_prompt": d["extraction_prompt"],
            "judge_profile": d["judge_profile"], "judge_prompt": d["judge_prompt"], "retrievals": ["RAG02", "RAG01"],
            **changes}
    return client.post(f"{C}/pipelines", json=body)


def test_catalog_lists_everything(client):
    cat = catalog(client)
    default = next(p for p in cat["pipelines"] if p["is_default"])
    assert default["retrievals"] == [f"RAG0{i}" for i in range(1, 8)] and default["error"] is None
    assert default["extraction_prompt"] == {"name": "extraction_system", "version": 1}
    assert {"extraction_system", "judge_system"} <= {p["name"] for p in cat["prompts"] if p["is_active"]}
    fields = cat["field_sets"][0]["fields"]
    assert len(fields) == 286 and all(f["queries"] and f["value_schema"] for f in fields)
    fee = next(f for f in fields if f["key"] == "termination_for_convenience")
    assert (fee["type_spec"], fee["priority"], fee["user_prompt"]) == (
        "object: available_to, party_refs, notice_period, termination_fee", "P1", None)
    assert any(mm["kind"] == "embedding" and mm["embedding_dimension"] for p in cat["providers"] for mm in p["models"])
    assert {r["name"] for r in cat["retrievals"]} >= {"RAG01", "RAG07"}


def test_retrieval_configs(client):
    r = client.post(f"{C}/retrievals", json={"name": "RAG99", "top_k": 4, "score_threshold": "0.45"})
    assert r.status_code == 201 and r.json()["score_threshold"] == "0.450" and r.json()["min_score"] == "0.300"
    problem(client.post(f"{C}/retrievals", json={"name": "RAG99", "top_k": 4, "score_threshold": "0.4"}), 409, "already exists")

    r = client.patch(f"{C}/retrievals/RAG99", json={"top_k": 3, "description": "smaller"})
    assert r.status_code == 200 and (r.json()["top_k"], r.json()["description"]) == (3, "smaller")
    assert client.patch(f"{C}/retrievals/RAG99", json={"description": None}).json()["description"] is None
    problem(client.patch(f"{C}/retrievals/RAG99", json={"top_k": None}), 422)
    problem(client.patch(f"{C}/retrievals/RAG99", json={"name": "RAG98"}), 422)
    problem(client.patch(f"{C}/retrievals/RAG99", json={"score_threshold": "1.5"}), 422)
    problem(client.patch(f"{C}/retrievals/NOPE", json={"top_k": 3}), 404)

    assert client.delete(f"{C}/retrievals/RAG99").status_code == 204
    problem(client.delete(f"{C}/retrievals/RAG01"), 409, "in use")


def test_pipelines(client):
    r = new_pipeline(client)
    assert r.status_code == 201, r.text
    assert r.json()["retrievals"] == ["RAG02", "RAG01"] and r.json()["error"] is None and not r.json()["is_default"]
    problem(new_pipeline(client), 409, "already exists")

    r = client.patch(f"{C}/pipelines/trial", json={"retrievals": ["RAG07", "RAG02", "RAG01"], "judge_parallel": True})
    assert r.status_code == 200 and r.json()["retrievals"] == ["RAG07", "RAG02", "RAG01"] and r.json()["judge_parallel"]
    problem(client.patch(f"{C}/pipelines/trial", json={"retrievals": []}), 422)
    problem(client.patch(f"{C}/pipelines/trial", json={"retrievals": ["RAG01", "RAG01"]}), 422, "only once")
    judge_prompt = pipeline(client)["judge_prompt"]
    problem(client.patch(f"{C}/pipelines/trial", json={"extraction_prompt": judge_prompt}), 422, "cannot run")
    problem(new_pipeline(client, "nojudge", judge_profile=None), 422, "judge_profile")
    assert new_pipeline(client, "nojudge", judge_enabled=False, judge_profile=None, judge_prompt=None).status_code == 201

    r = client.post(f"{C}/pipelines/trial/default")
    assert r.status_code == 200 and r.json()["is_default"]
    assert [p["name"] for p in catalog(client)["pipelines"] if p["is_default"]] == ["trial"]
    problem(client.delete(f"{C}/pipelines/trial"), 409, "default")
    client.post(f"{C}/pipelines/default/default")
    assert client.delete(f"{C}/pipelines/trial").status_code == 204
    problem(client.delete(f"{C}/pipelines/trial"), 404)


def test_prompt_versions(client):
    body = next(p["body"] for p in catalog(client)["prompts"] if p["name"] == "extraction_system")
    r = client.post(f"{C}/prompts/extraction_system/versions", json={"body": body + "\nBe brief.", "notes": "shorter"})
    assert r.status_code == 201 and (r.json()["version"], r.json()["is_active"], r.json()["role"]) == (2, True, "extraction_system")
    versions = {p["version"]: p["is_active"] for p in catalog(client)["prompts"] if p["name"] == "extraction_system"}
    assert versions == {1: False, 2: True}
    assert pipeline(client)["extraction_prompt"]["version"] == 1, "pipelines stay pinned"

    problem(client.post(f"{C}/prompts", json={"name": "extraction_system", "role": "extraction_system", "body": "x"}), 409, "new version")
    r = client.post(f"{C}/prompts", json={"name": "terse_judge", "role": "judge_system", "body": "Judge tersely."})
    assert r.status_code == 201 and r.json()["version"] == 1
    problem(client.post(f"{C}/prompts/nope/versions", json={"body": "x"}), 404)


def test_fields(client):
    fields = catalog(client)["field_sets"][0]["fields"]
    title = next(f for f in fields if f["key"] == "title")
    r = client.patch(f"{C}/fields/{title['id']}", json={"label": "Name", "queries": ["agreement title", "  ", "heading"]})
    assert r.status_code == 200 and r.json()["label"] == "Name" and r.json()["queries"] == ["agreement title", "heading"]
    problem(client.patch(f"{C}/fields/{title['id']}", json={"label": None}), 422)
    problem(client.patch(f"{C}/fields/{title['id']}", json={"key": "name"}), 422)
    r = client.patch(f"{C}/fields/{title['id']}", json={"user_prompt": "Find the title.", "priority": "P1"})
    assert (r.json()["user_prompt"], r.json()["priority"]) == ("Find the title.", "P1")
    assert client.patch(f"{C}/fields/{title['id']}", json={"user_prompt": None}).json()["user_prompt"] is None
    problem(client.patch(f"{C}/fields/{title['id']}", json={"user_prompt": ""}), 422)

    r = client.post(f"{C}/field-sets/contract_fields/1/fields",
                    json={"key": "notice_period", "label": "Notice period", "queries": ["notice period"]})
    assert r.status_code == 201 and r.json()["position"] == 287 and r.json()["user_prompt"] is None
    assert (r.json()["priority"], r.json()["value_schema"]) == ("P2", {})
    problem(client.post(f"{C}/field-sets/contract_fields/1/fields", json={"key": "Bad Key", "label": "x", "user_prompt": "x"}), 422)


def test_disabling_the_last_field_of_a_type_is_refused(client, session):
    from sqlalchemy import select, update

    from contract_extraction.persistence import models as m

    other = select(m.ContractTypeField.field_id).join(m.ContractType).where(m.ContractType.key == "other")
    session.execute(update(m.Field).where(m.Field.id.in_(other), m.Field.key != "payment_terms").values(is_enabled=False))
    last = next(f for f in catalog(client)["field_sets"][0]["fields"] if f["key"] == "payment_terms")
    problem(client.patch(f"{C}/fields/{last['id']}", json={"is_enabled": False}), 422, "'other' has no enabled fields")


def test_profiles_and_models(client):
    embedding = next(mm["id"] for p in catalog(client)["providers"] for mm in p["models"] if mm["kind"] == "embedding")
    chat = next(mm["id"] for p in catalog(client)["providers"] for mm in p["models"] if mm["kind"] == "chat")
    problem(client.post(f"{C}/profiles", json={"name": "emb", "model_id": embedding}), 422, "chat or vision")
    r = client.post(f"{C}/profiles", json={"name": "hot", "model_id": chat, "temperature": "0.9", "num_ctx": 4096})
    assert r.status_code == 201 and r.json()["temperature"] == "0.900"
    problem(client.patch(f"{C}/profiles/hot", json={"temperature": "3"}), 422)
    assert client.patch(f"{C}/profiles/hot", json={"num_ctx": None}).json()["num_ctx"] is None
    problem(client.delete(f"{C}/profiles/extraction-default"), 409, "in use")
    assert client.delete(f"{C}/profiles/hot").status_code == 204

    r = client.post(f"{C}/providers/ollama-local/models", json={"name": "llama3.2:3b", "kind": "chat", "context_window": 131072})
    assert r.status_code == 201 and r.json()["is_enabled"]
    problem(client.post(f"{C}/providers/ollama-local/models", json={"name": "e5", "kind": "embedding"}), 422, "embedding_dimension")
    problem(client.patch(f"{C}/models/{r.json()['id']}", json={"embedding_dimension": 5}), 422)
    assert client.patch(f"{C}/models/{r.json()['id']}", json={"input_cost_per_mtok": "0.05"}).json()["input_cost_per_mtok"] == "0.050000"

    # Disabling the model behind the default pipeline is allowed; the pipeline then reports why it cannot run.
    assert client.patch(f"{C}/models/{chat}", json={"is_enabled": False}).status_code == 200
    assert "disabled" in pipeline(client)["error"]


def test_decomposition_and_index_configs_are_create_only(client):
    r = client.post(f"{C}/decompositions", json={"name": "ocr-300", "method": "ocr", "dpi": 300})
    assert r.status_code == 201 and (r.json()["method"], r.json()["dpi"]) == ("ocr", 300)
    assert client.patch(f"{C}/decompositions/ocr-300", json={"dpi": 200}).status_code == 405
    problem(client.post(f"{C}/decompositions", json={"name": "x", "dpi": 50}), 422)

    embedding = next(mm["id"] for p in catalog(client)["providers"] for mm in p["models"] if mm["kind"] == "embedding")
    chat = next(mm["id"] for p in catalog(client)["providers"] for mm in p["models"] if mm["kind"] == "chat")
    problem(client.post(f"{C}/indexes", json={"name": "small", "embedding_model_id": chat}), 422, "embedding model")
    problem(client.post(f"{C}/indexes", json={"name": "small", "embedding_model_id": embedding, "chunk_size": 500,
                                              "chunk_overlap": 500}), 422, "chunk_overlap")
    r = client.post(f"{C}/indexes", json={"name": "small", "embedding_model_id": embedding, "chunk_size": 800, "chunk_overlap": 100})
    assert r.status_code == 201 and r.json()["chunk_size"] == 800
    assert client.delete(f"{C}/indexes/small").status_code == 204
    assert client.delete(f"{C}/decompositions/ocr-300").status_code == 204
    problem(client.delete(f"{C}/decompositions/default"), 409, "in use")


def test_provider_url(client):
    problem(client.patch(f"{C}/providers/ollama-local", json={"base_url": "localhost:1"}), 422, "http")
    r = client.patch(f"{C}/providers/ollama-local", json={"base_url": "http://localhost:11435/"})
    assert r.status_code == 200 and r.json()["base_url"] == "http://localhost:11435"
    problem(client.patch(f"{C}/providers/nope", json={"is_enabled": False}), 404)
