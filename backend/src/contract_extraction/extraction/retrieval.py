"""Retrieval of evidence chunks for one field under one RAG configuration.

1. Queries: the field's expansion queries when the config enables query expansion, else the field label.
   Group extraction searches with the queries of all the group's fields.
2. Each query fetches ``per_query_top`` dense (embedding) hits; hits below ``score_threshold`` or
   ``min_score`` are dropped.
3. With ``keyword_search``, each query also fetches ``per_query_top`` keyword (BM25) hits.
4. Hits are merged by chunk. Without keyword search they are ranked by their best dense score; with it,
   by reciprocal rank fusion (each chunk scores Σ 1/(RRF_K + rank) over every list it appears in), so a
   chunk both searches find comes first. The best ``top_k`` remain.

Query embeddings are cached for the retriever's lifetime (one run), so configs sharing
queries embed them once.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

from ..domain.config import Field, RetrievalConfig
from ..domain.enums import HitSource
from ..indexing import keywords
from ..providers.base import Embedder, SearchHit, VectorStore

RRF_K = 60


@dataclass(frozen=True)
class Hit:
    chunk_id: uuid.UUID
    # Best dense (cosine) score; None for a chunk only keyword search found.
    score: float | None
    page: int
    text: str
    # Expansion query that found the chunk (None when the field label was used).
    matched_query: str | None
    # Best keyword (BM25) score; None for a chunk only dense search found.
    keyword_score: float | None = None
    source: HitSource = HitSource.DENSE


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
        return self._search(list(field.queries) if expanded else [field.label], expanded, rc)

    def retrieve_group(self, fields: tuple[Field, ...], rc: RetrievalConfig) -> list[Hit]:
        """Evidence for several fields answered by one call: every field's queries, merged the same way."""
        queries: list[str] = []
        for f in fields:
            queries += list(f.queries) if rc.query_expansion and f.queries else [f.label]
        return self._search(list(dict.fromkeys(queries)), rc.query_expansion, rc)

    def _search(self, queries: list[str], expanded: bool, rc: RetrievalConfig) -> list[Hit]:
        threshold, floor = float(rc.score_threshold), float(rc.min_score)
        best: dict[uuid.UUID, Hit] = {}
        fused: dict[uuid.UUID, float] = {}

        def add(h: SearchHit, rank: int, query: str, keyword: bool) -> None:
            fused[h.id] = fused.get(h.id, 0.0) + 1 / (RRF_K + rank)
            found = Hit(h.id, None if keyword else h.score, int(h.payload.get("page", 0)), str(h.payload.get("text", "")),
                        query if expanded else None, h.score if keyword else None,
                        HitSource.KEYWORD if keyword else HitSource.DENSE)
            old = best.get(h.id)
            if old is None:
                best[h.id] = found
            elif keyword:
                best[h.id] = replace(old, keyword_score=max(old.keyword_score or 0.0, h.score),
                                     source=HitSource.BOTH if old.source != HitSource.KEYWORD else HitSource.KEYWORD)
            else:
                better = old.score is None or h.score > old.score
                best[h.id] = replace(old, score=h.score if better else old.score,
                                     matched_query=found.matched_query if better else old.matched_query,
                                     source=HitSource.BOTH if old.source != HitSource.DENSE else HitSource.DENSE)

        for query, vector in zip(queries, self._embed(queries), strict=True):
            dense = [h for h in self.store.search(self.collection, vector, rc.per_query_top)
                     if h.score >= threshold and h.score >= floor]
            for rank, h in enumerate(dense, start=1):
                add(h, rank, query, keyword=False)
            if rc.keyword_search:
                found = self.store.keyword_search(self.collection, keywords.query_vector(query), rc.per_query_top)
                for rank, h in enumerate(found, start=1):
                    add(h, rank, query, keyword=True)

        if rc.keyword_search:
            order = sorted(best.values(), key=lambda h: (-fused[h.chunk_id], -(h.score or 0.0), str(h.chunk_id)))
        else:
            order = sorted(best.values(), key=lambda h: (-(h.score or 0.0), str(h.chunk_id)))
        return order[:rc.top_k]
