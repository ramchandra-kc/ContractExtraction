"""Qdrant vector store over its REST API."""

from __future__ import annotations

import uuid

import httpx

from ._http import request_json
from .base import Point, ProviderError, SearchHit

_DISTANCE = {"cosine": "Cosine", "dot": "Dot", "euclid": "Euclid"}
_UPSERT_BATCH = 256


class QdrantStore:
    def __init__(self, url: str, api_key: str | None = None, client: httpx.Client | None = None, timeout: float = 60):
        headers = {"api-key": api_key} if api_key else {}
        self.client = client or httpx.Client(base_url=url.rstrip("/"), headers=headers, timeout=timeout)

    def ping(self) -> None:
        request_json(self.client, "GET", "/collections", "Qdrant")

    def exists(self, collection: str) -> bool:
        data = request_json(self.client, "GET", f"/collections/{collection}/exists", f"Qdrant exists {collection}")
        return bool((data.get("result") or {}).get("exists"))

    def ensure_collection(self, collection: str, dimension: int, distance: str) -> None:
        if self.exists(collection):
            info = request_json(self.client, "GET", f"/collections/{collection}", f"Qdrant info {collection}")
            size = (((info.get("result") or {}).get("config") or {}).get("params") or {}).get("vectors", {}).get("size")
            if size is not None and size != dimension:
                raise ProviderError(f"Qdrant collection {collection} has dimension {size}, expected {dimension}")
            return
        request_json(self.client, "PUT", f"/collections/{collection}", f"Qdrant create {collection}",
                     {"vectors": {"size": dimension, "distance": _DISTANCE[distance]}})

    def upsert(self, collection: str, points: list[Point]) -> None:
        for i in range(0, len(points), _UPSERT_BATCH):
            batch = points[i:i + _UPSERT_BATCH]
            request_json(self.client, "PUT", f"/collections/{collection}/points", f"Qdrant upsert {collection}",
                         {"points": [{"id": str(p.id), "vector": p.vector, "payload": p.payload} for p in batch]},
                         params={"wait": "true"})

    def search(self, collection: str, vector: list[float], limit: int) -> list[SearchHit]:
        data = request_json(self.client, "POST", f"/collections/{collection}/points/search", f"Qdrant search {collection}",
                            {"vector": vector, "limit": limit, "with_payload": True})
        return [SearchHit(id=uuid.UUID(str(h["id"])), score=float(h["score"]), payload=h.get("payload") or {})
                for h in data.get("result") or []]

    def delete_collection(self, collection: str) -> None:
        request_json(self.client, "DELETE", f"/collections/{collection}", f"Qdrant delete {collection}")
