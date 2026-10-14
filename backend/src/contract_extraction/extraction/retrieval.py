"""Retrieval of evidence chunks for one field under one RAG configuration.

1. Queries: the field's expansion queries when the config enables query expansion, else the field label.
2. Each query fetches ``per_query_top`` hits; hits below ``score_threshold`` are dropped.
3. Hits are de-duplicated by chunk, keeping the best score and the query that produced it.
4. Hits below ``min_score`` are dropped; the best ``top_k`` remain, highest score first.

Query embeddings are cached for the retriever's lifetime (one run), so configs sharing
queries embed them once.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from ..domain.config import Field, RetrievalConfig
from ..providers.base import Embedder, VectorStore


@dataclass(frozen=True)
class Hit:
    chunk_id: uuid.UUID
    score: float
    page: int
    text: str
    # Expansion query that found the chunk (None when the field label was used).
    matched_query: str | None


class Retriever:
    def __init__(self, store: VectorStore, collection: str, embedder: Embedder):
        self.store = store
        self.collection = collection
        self.embedder = embedder
        self._vectors: dict[str, list[float]] = {}

    def _embed(self, queries: list[str]) -> list[list[float]]:
        missing = [q for q in dict.fromkeys(queries) if q not in self._vectors]
        if missing:
            self._vectors.update(zip(missing, self.embedder.embed(missing), strict=True))
        return [self._vectors[q] for q in queries]

    def retrieve(self, field: Field, rc: RetrievalConfig) -> list[Hit]:
        expanded = rc.query_expansion and bool(field.queries)
        queries = list(field.queries) if expanded else [field.label]
        threshold, floor = float(rc.score_threshold), float(rc.min_score)
        best: dict[uuid.UUID, Hit] = {}
        for query, vector in zip(queries, self._embed(queries), strict=True):
            for h in self.store.search(self.collection, vector, rc.per_query_top):
                if h.score < threshold or h.score < floor:
                    continue
                if h.id not in best or h.score > best[h.id].score:
                    best[h.id] = Hit(h.id, h.score, int(h.payload.get("page", 0)), str(h.payload.get("text", "")),
                                     query if expanded else None)
        return sorted(best.values(), key=lambda h: (-h.score, str(h.chunk_id)))[:rc.top_k]
