"""API keys: the database names the variable, the environment (or backend/config/.env.local) holds the value."""

from __future__ import annotations

from .core.errors import InvalidConfig
from .core.settings import Settings
from .domain.config import Provider


def resolve_api_key(provider: Provider, settings: Settings) -> str | None:
    """The provider's API key, or ``None`` when the provider needs none (e.g. local Ollama)."""
    if not provider.api_key_env:
        return None
    value = (settings.env_value(provider.api_key_env) or "").strip()
    if not value:
        raise InvalidConfig(
            f"Provider {provider.key!r} needs an API key: set {provider.api_key_env} "
            "in the environment or in backend/config/.env.local")
    return value
