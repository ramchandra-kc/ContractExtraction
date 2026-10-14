from __future__ import annotations

import pytest

from contract_extraction.core.errors import InvalidConfig
from contract_extraction.core.settings import load_settings
from contract_extraction.domain.config import Provider
from contract_extraction.secrets import resolve_api_key


@pytest.fixture
def config_dir(tmp_path):
    (tmp_path / ".env").write_text("LOG_LEVEL=INFO\nDATABASE__URL=postgresql+psycopg://a@h/base\nSTORAGE__MAX_UPLOAD_MB=10\n")
    (tmp_path / ".env.test").write_text("DATABASE__URL=postgresql+psycopg://a@h/from_test\n")
    (tmp_path / ".env.local").write_text("STORAGE__MAX_UPLOAD_MB=20\nMY_KEY=from-local\n")
    return tmp_path


def test_layering(config_dir):
    s = load_settings("test", config_dir)
    assert s.app_env == "test"
    assert s.database.url.endswith("/from_test")
    assert s.storage.max_upload_mb == 20


def test_environment_wins(config_dir, monkeypatch):
    monkeypatch.setenv("STORAGE__MAX_UPLOAD_MB", "99")
    assert load_settings("test", config_dir).storage.max_upload_mb == 99


def test_api_key_resolution(config_dir, monkeypatch):
    s = load_settings("test", config_dir)
    provider = Provider(id="00000000-0000-0000-0000-000000000001", key="openrouter", kind="openrouter",
                        base_url="https://openrouter.ai/api/v1", api_key_env="MY_KEY")
    assert resolve_api_key(provider, s) == "from-local"
    monkeypatch.setenv("MY_KEY", "from-env")
    assert resolve_api_key(provider, s) == "from-env"
    with pytest.raises(InvalidConfig, match="OTHER_KEY"):
        resolve_api_key(provider.model_copy(update={"api_key_env": "OTHER_KEY"}), s)
    assert resolve_api_key(provider.model_copy(update={"api_key_env": None}), s) is None
