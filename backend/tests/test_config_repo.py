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
    assert len(p.field_set.fields) == 12
    assert p.field_set.fields[0].key == "customer_name"
    assert all(len(f.queries) == 30 for f in p.field_set.fields)
    assert p.extraction_profile.model.name == "llama3.1:8b"
    assert p.extraction_profile.model.provider.key == "ollama-local"
    assert p.index.embedding_model.embedding_dimension == 768
    assert p.judge_enabled and p.judge_profile and p.judge_prompt
    assert "PASS" in p.judge_prompt.body


def test_snapshot_is_json_and_secret_free(session):
    snap = ConfigRepo(session).resolve_pipeline().snapshot()
    assert snap["extraction_profile"]["temperature"] == "0.200"
    assert snap["retrievals"][0]["name"] == "RAG01"
    provider = snap["extraction_profile"]["model"]["provider"]
    assert set(provider) == {"id", "key", "kind", "base_url", "api_key_env", "settings"}


def test_disabled_fields_are_skipped(session):
    session.execute(update(m.Field).where(m.Field.key == "penalties").values(is_enabled=False))
    p = ConfigRepo(session).resolve_pipeline()
    assert "penalties" not in [f.key for f in p.field_set.fields]


def test_disabled_provider_is_rejected(session):
    session.execute(update(m.LlmProvider).where(m.LlmProvider.key == "ollama-local").values(is_enabled=False))
    with pytest.raises(InvalidConfig, match="ollama-local"):
        ConfigRepo(session).resolve_pipeline()


def test_unknown_pipeline(session):
    with pytest.raises(NotFound):
        ConfigRepo(session).resolve_pipeline("nope")


def test_listings(session):
    repo = ConfigRepo(session)
    assert {p.key for p in repo.providers()} == {"ollama-local", "openrouter"}
    assert [mo.name for mo in repo.models(ModelKind.EMBEDDING)] == ["nomic-embed-text:latest"]
    assert len(repo.retrieval_configs()) == 7
