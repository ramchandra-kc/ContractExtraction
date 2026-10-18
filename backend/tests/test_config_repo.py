from __future__ import annotations

import pytest
from sqlalchemy import update

from contract_extraction.core.errors import InvalidConfig, NotFound
from contract_extraction.domain.enums import ModelKind
from contract_extraction.persistence import models as m
from contract_extraction.persistence.repositories import ConfigRepo


def test_default_pipeline_resolves(session):
    p = ConfigRepo(session).resolve_pipeline()

    assert p.name == "default"
    assert [r.name for r in p.retrievals] == [f"RAG0{i}" for i in range(1, 8)]
    hybrid = p.retrievals[-1]
    assert (hybrid.keyword_search, hybrid.anchor_chunks) == (True, 2)
    assert not any(r.keyword_search or r.anchor_chunks for r in p.retrievals[:-1])
    assert len(p.field_set.fields) == 286
    assert {f.key: f.anchor for f in p.field_set.fields}["parties"] == "start"
    assert p.field_set.fields[0].key == "title"
    assert all(f.queries and f.user_prompt is None and f.value_schema for f in p.field_set.fields)
    types = {t.key: t for t in p.field_set.contract_types}
    assert len(types) == 19 and p.field_set.fallback_type.key == "other"
    assert len(types["msa"].fields) == 66 and len(types["other"].fields) == 44
    sla = next(f for f in types["saas"].fields if f.key == "service_levels")
    assert (sla.group, sla.priority) == ("specific", "P2"), "priority is per contract type"
    assert next(f for f in p.field_set.fields if f.key == "service_levels").priority == "P1", "field keeps its highest"
    assert p.extraction_profile.model.name == "llama3.1:8b"
    assert p.extraction_profile.model.provider.key == "ollama-local"
    assert p.index.embedding_model.embedding_dimension == 768
    assert p.judge_enabled and p.judge_profile and p.judge_prompt
    assert "PASS" in p.judge_prompt.body


def test_preset_pipelines_resolve(session):
    repo = ConfigRepo(session)
    with pytest.raises(InvalidConfig, match="disabled"):
        repo.resolve_pipeline("or-haiku")
    repo.update_provider("openrouter", enabled=True)

    pipelines = {row.name: repo.resolve_pipeline(row.name) for row in repo.pipelines()}
    assert len(pipelines) == 10
    assert [r.name for r in pipelines["or-rag-sweep"].retrievals] == ["RAG08", "RAG07", "RAG09", "RAG10", "RAG11"]
    assert [r.name for r in pipelines["or-llama31-8b"].retrievals] == [r.name for r in pipelines["default"].retrievals]
    triage = pipelines["or-p1-triage"]
    assert not triage.judge_enabled and triage.judge_prompt is None and triage.min_priority == "P1"
    assert pipelines["or-haiku"].judge_profile.model.name == "openai/gpt-6-luna"
    budget = pipelines["or-budget"].extraction_profile
    assert budget.extra == {"params": {"reasoning": {"enabled": False}}} and budget.top_k is None
    assert pipelines["local-fast"].extraction_profile.model.provider.key == "ollama-local"


def test_snapshot_is_json_and_secret_free(session):
    snap = ConfigRepo(session).resolve_pipeline().snapshot()
    assert snap["extraction_profile"]["temperature"] == "0.200"
    assert snap["retrievals"][0]["name"] == "RAG01"
    provider = snap["extraction_profile"]["model"]["provider"]
    assert set(provider) == {"id", "key", "kind", "base_url", "api_key_env", "settings"}


def test_disabled_fields_are_skipped(session):
    session.execute(update(m.Field).where(m.Field.key == "payment_terms").values(is_enabled=False))
    p = ConfigRepo(session).resolve_pipeline()
    assert "payment_terms" not in [f.key for f in p.field_set.fields]
    assert all("payment_terms" not in [f.key for f in t.fields] for t in p.field_set.contract_types)


def test_contract_types_need_a_fallback(session):
    session.execute(update(m.ContractType).values(is_fallback=False))
    with pytest.raises(InvalidConfig, match="no fallback type"):
        ConfigRepo(session).resolve_pipeline()


def test_disabled_provider_is_rejected(session):
    session.execute(update(m.LlmProvider).where(m.LlmProvider.key == "ollama-local").values(is_enabled=False))
    with pytest.raises(InvalidConfig, match="ollama-local"):
        ConfigRepo(session).resolve_pipeline()


def test_unknown_pipeline(session):
    with pytest.raises(NotFound):
        ConfigRepo(session).resolve_pipeline("nope")


def test_switch_provider_url(session):
    from contract_extraction.core.errors import InvalidInput

    repo = ConfigRepo(session)
    repo.update_provider("ollama-local", base_url="http://localhost:11435/")
    p = repo.resolve_pipeline()
    assert p.extraction_profile.model.provider.base_url == "http://localhost:11435"
    assert p.snapshot()["index"]["embedding_model"]["provider"]["base_url"] == "http://localhost:11435"

    repo.update_provider("openrouter", enabled=True)
    assert {x.key: x.is_enabled for x in repo.providers()}["openrouter"] is True
    with pytest.raises(InvalidInput):
        repo.update_provider("ollama-local", base_url="localhost:11435")
    with pytest.raises(NotFound):
        repo.update_provider("nope", enabled=False)


def test_listings(session):
    repo = ConfigRepo(session)
    assert {p.key for p in repo.providers()} == {"ollama-local", "openrouter"}
    assert [mo.name for mo in repo.models(ModelKind.EMBEDDING)] == ["nomic-embed-text:latest"]
    assert len(repo.retrieval_configs()) == 11
