"""Build provider clients from resolved database configuration."""

from __future__ import annotations

from ..core.settings import Settings
from ..domain.config import Model, ModelProfile
from ..domain.enums import ProviderKind, VectorStore as VectorStoreKind
from ..secrets import resolve_api_key
from .base import ChatClient, Embedder, VectorStore
from .memory import MemoryStore
from .ollama import OllamaChat, OllamaEmbedder
from .openai_compat import OpenAICompatChat, OpenAICompatEmbedder
from .qdrant import QdrantStore


def chat_client(profile: ModelProfile, settings: Settings) -> ChatClient:
    provider = profile.model.provider
    if provider.kind == ProviderKind.OLLAMA:
        return OllamaChat(provider.base_url)
    return OpenAICompatChat(provider.base_url, resolve_api_key(provider, settings))


def embedder(model: Model, settings: Settings) -> Embedder:
    provider = model.provider
    if provider.kind == ProviderKind.OLLAMA:
        return OllamaEmbedder(provider.base_url, model.name)
    return OpenAICompatEmbedder(provider.base_url, resolve_api_key(provider, settings), model.name)


# One in-memory store per process, so an index built earlier in the process can be searched later.
_MEMORY = MemoryStore()


def vector_store(kind: str, settings: Settings) -> VectorStore:
    if kind == VectorStoreKind.MEMORY:
        return _MEMORY
    return QdrantStore(settings.qdrant.url, settings.qdrant.api_key or None)
