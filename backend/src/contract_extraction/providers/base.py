"""Provider interfaces: chat models, embedding models and vector stores.

Implementations are chosen from database configuration by ``factory.py``; the pipeline
only depends on these protocols, so tests can pass fakes.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..domain.config import ModelProfile


class ProviderError(Exception):
    """A provider call failed. ``timeout`` tells timeouts apart from other failures."""

    def __init__(self, message: str, timeout: bool = False):
        super().__init__(message)
        self.timeout = timeout


@dataclass(frozen=True)
class ChatResult:
    text: str
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    # Request parameters actually sent (recorded in llm_calls.params).
    params: dict[str, Any] = field(default_factory=dict)


class ChatClient(Protocol):
    def complete(self, system: str, user: str, profile: ModelProfile,
                 checkpoint: Callable[[], None] | None = None) -> ChatResult:
        """Answer ``user``. ``checkpoint`` is called while the answer streams in; an exception it raises
        aborts the call (closing the connection, so the server stops generating) and propagates."""
        ...


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class SparseVector:
    """Keyword (BM25) vector: term ids and weights (``indexing.keywords``)."""
    indices: list[int]
    values: list[float]


@dataclass(frozen=True)
class Point:
    id: uuid.UUID
    vector: list[float]
    payload: dict[str, Any]
    # Keyword vector; the store applies inverse document frequency when searching.
    keywords: SparseVector | None = None


@dataclass(frozen=True)
class SearchHit:
    id: uuid.UUID
    score: float
    payload: dict[str, Any]


class VectorStore(Protocol):
    def exists(self, collection: str) -> bool: ...

    def ensure_collection(self, collection: str, dimension: int, distance: str) -> None: ...

    def upsert(self, collection: str, points: list[Point]) -> None: ...

    def search(self, collection: str, vector: list[float], limit: int) -> list[SearchHit]: ...

    def keyword_search(self, collection: str, query: SparseVector, limit: int) -> list[SearchHit]:
        """BM25: the sum over query terms of the chunk's term weight times the term's IDF in the collection."""
        ...

    def delete_collection(self, collection: str) -> None: ...
