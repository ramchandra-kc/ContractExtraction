"""Application settings: connection details and paths only.

Pipeline configuration (providers, models, prompts, RAG configs, fields) lives in the
database and is read through ``ConfigRepo``. Secrets such as API keys are read from the
environment at use time (see ``secrets.py``).

Files are read from the config folder (``backend/config`` or ``$CE_CONFIG_DIR``),
later files overriding earlier ones:

1. ``.env``                   shared defaults
2. ``.env.<APP_ENV>``         per environment (development / test / ...)
3. ``.env.local``             machine-local overrides, never committed
4. ``.env.<APP_ENV>.local``   machine-local overrides for one environment, never committed

Real environment variables override all files. Nested keys use ``__``,
e.g. ``DATABASE__URL`` or ``STORAGE__MAX_UPLOAD_MB``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, Field, PrivateAttr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_DIR = BACKEND_ROOT / "config"


class DatabaseSettings(BaseModel):
    url: str = "postgresql+psycopg://contract:contract@localhost:55432/contract_extraction"
    pool_size: int = Field(5, gt=0)
    max_overflow: int = Field(10, ge=0)
    echo: bool = False


class StorageSettings(BaseModel):
    # Relative paths resolve against the backend folder.
    root: str = "storage"
    max_upload_mb: int = Field(50, gt=0)


class QdrantSettings(BaseModel):
    url: str = "http://localhost:56333"
    api_key: str = ""


class ExecutorSettings(BaseModel):
    # Threads for judge calls when a pipeline enables judge_parallel (machine capacity, not research config).
    judge_workers: int = Field(4, gt=0)


class WorkerSettings(BaseModel):
    # Idle wait between queue checks.
    poll_seconds: float = Field(2, gt=0)
    # How often a running run proves it is alive (LLM calls can take minutes, so progress alone is not enough).
    heartbeat_seconds: float = Field(15, gt=0)
    # A running run without a heartbeat for this long is marked failed ("worker stopped responding").
    stale_after_seconds: float = Field(120, gt=0)


class ApiSettings(BaseModel):
    # Loopback only: the API is reached through the gateway.
    host: str = "127.0.0.1"
    port: int = Field(8000, gt=0, lt=65536)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    executor: ExecutorSettings = Field(default_factory=ExecutorSettings)
    worker: WorkerSettings = Field(default_factory=WorkerSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)

    # Raw values from the env files, for variables that are not settings (API keys named in the database).
    _file_values: dict[str, str] = PrivateAttr(default_factory=dict)

    @property
    def storage_root(self) -> Path:
        root = Path(self.storage.root)
        return root if root.is_absolute() else BACKEND_ROOT / root

    def env_value(self, name: str) -> str | None:
        """A variable from the real environment, else from the env files."""
        value = os.getenv(name)
        return value if value is not None else self._file_values.get(name)


def env_files(config_dir: Path, app_env: str) -> tuple[Path, ...]:
    names = (".env", f".env.{app_env}", ".env.local", f".env.{app_env}.local")
    return tuple(p for p in (config_dir / n for n in names) if p.is_file())


def load_settings(app_env: str | None = None, config_dir: str | os.PathLike | None = None) -> Settings:
    """Settings for ``app_env`` (default ``$APP_ENV``, else ``development``)."""
    env = app_env or os.getenv("APP_ENV") or "development"
    directory = Path(config_dir or os.getenv("CE_CONFIG_DIR") or DEFAULT_CONFIG_DIR)
    files = env_files(directory, env)
    settings = Settings(_env_file=files or None, app_env=env)  # type: ignore[call-arg]
    for path in files:
        settings._file_values.update({k: v for k, v in dotenv_values(path).items() if v is not None})
    return settings
