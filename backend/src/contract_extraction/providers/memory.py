"""In-process vector store for tests and quick experiments (lost when the process exits)."""

from __future__ import annotations

import math

from .base import Point, ProviderError, SearchHit


def _score(a: list[float], b: list[float], distance: str) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    if distance == "dot":
        return dot
    if distance == "euclid":
        return -math.dist(a, b)
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class MemoryStore:
    def __init__(self) -> None:
        self._collections: dict[str, tuple[int, str, dict]] = {}

    def exists(self, collection: str) -> bool:
        return collection in self._collections

    def ensure_collection(self, collection: str, dimension: int, distance: str) -> None:
        existing = self._collections.get(collection)
        if existing and existing[0] != dimension:
            raise ProviderError(f"Collection {collection} has dimension {existing[0]}, expected {dimension}")
        self._collections.setdefault(collection, (dimension, distance, {}))

    def upsert(self, collection: str, points: list[Point]) -> None:
        dimension, _, store = self._collections[collection]
        for p in points:
            if len(p.vector) != dimension:
                raise ProviderError(f"Vector of size {len(p.vector)} for a {dimension}-dimension collection")
            store[p.id] = p

    def search(self, collection: str, vector: list[float], limit: int) -> list[SearchHit]:
        _, distance, store = self._collections[collection]
        hits = [SearchHit(p.id, _score(vector, p.vector, distance), p.payload) for p in store.values()]
        return sorted(hits, key=lambda h: h.score, reverse=True)[:limit]

    def delete_collection(self, collection: str) -> None:
        self._collections.pop(collection, None)
