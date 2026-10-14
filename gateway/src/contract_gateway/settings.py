"""Gateway settings from layered .env files in ``gateway/config`` (or ``$GW_CONFIG_DIR``).

Same convention as the backend (its own copy; parts never import each other):
``.env`` → ``.env.<APP_ENV>`` → ``.env.local`` → ``.env.<APP_ENV>.local`` → real environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

GATEWAY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = GATEWAY_ROOT / "config"


class GatewaySettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(8080, gt=0, lt=65536)
    max_upload_mb: int = Field(50, gt=0)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    # Budget for the backend liveness call made by GET /health.
    health_timeout_seconds: float = Field(2, gt=0)


class UpstreamSettings(BaseModel):
    url: str = "http://127.0.0.1:8000"
    connect_timeout: float = Field(5, gt=0)
    read_timeout: float = Field(60, gt=0)
    write_timeout: float = Field(60, gt=0)
    pool_timeout: float = Field(5, gt=0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    gateway: GatewaySettings = Field(default_factory=GatewaySettings)
    upstream: UpstreamSettings = Field(default_factory=UpstreamSettings)

    @property
    def max_upload_bytes(self) -> int:
        return self.gateway.max_upload_mb * 1024 * 1024


def load_settings(app_env: str | None = None, config_dir: str | os.PathLike | None = None) -> Settings:
    env = app_env or os.getenv("APP_ENV") or "development"
    directory = Path(config_dir or os.getenv("GW_CONFIG_DIR") or DEFAULT_CONFIG_DIR)
    names = (".env", f".env.{env}", ".env.local", f".env.{env}.local")
    files = tuple(p for p in (directory / n for n in names) if p.is_file())
    return Settings(_env_file=files or None, app_env=env)  # type: ignore[call-arg]
