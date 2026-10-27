"""Retrieval of evidence chunks for one field under one RAG configuration.

1. Queries: the field's expansion queries when the config enables query expansion, else the field label.
   Group extraction searches with the queries of all the group's fields.
2. Each query fetches ``per_query_top`` dense (embedding) hits; hits below ``score_threshold`` or
   ``min_score`` are dropped.
3. With ``keyword_search``, each query also fetches ``per_query_top`` keyword (BM25) hits.
4. Hits are merged by chunk. Without keyword search they are ranked by their best dense score; with it,
   by reciprocal rank fusion (each chunk scores Σ 1/(RRF_K + rank) over every list it appears in), so a
   chunk both searches find comes first. The best ``top_k`` remain.
   With ``rerank_model``, the best ``rerank_candidates`` (at least ``top_k``) are scored instead by a
   cross-encoder against the field's label and description (in a group: every field's), and the best
   ``top_k`` by that score remain. The candidate pool is still capped by ``per_query_top`` × queries.
5. With ``anchor_chunks``, a field with an anchor (in a group: any of its fields) also gets the
   document's first and/or last ``anchor_chunks`` chunks, beyond ``top_k``: opening chunks first, then
   the retrieved ones, then closing chunks. A retrieved chunk that is also an anchor keeps its scores.

Query embeddings and rerank scores are cached for the retriever's lifetime (one run), so configs sharing
queries embed them once and score a chunk once.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from ..domain.config import Field, RetrievalConfig
from ..domain.enums import Anchor, HitSource
from ..indexing import keywords
from ..providers.base import Embedder, Reranker, SearchHit, VectorStore

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
    # Cross-encoder score when the config reranks.
    rerank_score: float | None = None


def rerank_query(fields: Sequence[Field]) -> str:
    """What the reranker judges chunks against: each field's label and description."""
    return "; ".join(f"{f.label}: {f.description}" if f.description else f.label for f in fields)


class Retriever:
    def __init__(self, store: VectorStore, collection: str, embedder: Embedder, document: Sequence[Hit] = (),
                 reranker: Callable[[str], Reranker] | None = None):
        """``document``: the index's chunks in order, as ``anchor`` hits (needed when a config sets anchor_chunks).
        ``reranker``: cross-encoder by model name (needed when a config sets rerank_model)."""
        self.store = store
        self.collection = collection
        self.embedder = embedder
        self.document = list(document)
        self.reranker = reranker
        self._vectors: dict[str, list[float]] = {}
        self._rerank: dict[tuple[str, str, uuid.UUID], float] = {}

    def _embed(self, queries: list[str]) -> list[list[float]]:
        missing = [q for q in dict.fromkeys(queries) if q not in self._vectors]
        if missing:
            self._vectors.update(zip(missing, self.embedder.embed(missing), strict=True))
        return [self._vectors[q] for q in queries]

    def retrieve(self, field: Field, rc: RetrievalConfig) -> list[Hit]:
        expanded = rc.query_expansion and bool(field.queries)
        hits = self._search(list(field.queries) if expanded else [field.label], expanded, rc)
        return self._anchored(self._reranked(hits, rerank_query([field]), rc), {field.anchor}, rc)

    def retrieve_group(self, fields: tuple[Field, ...], rc: RetrievalConfig) -> list[Hit]:
        """Evidence for several fields answered by one call: every field's queries, merged the same way."""
        queries: list[str] = []
        for f in fields:
            queries += list(f.queries) if rc.query_expansion and f.queries else [f.label]
        hits = self._search(list(dict.fromkeys(queries)), rc.query_expansion, rc)
        return self._anchored(self._reranked(hits, rerank_query(fields), rc), {f.anchor for f in fields}, rc)

    def _reranked(self, hits: list[Hit], query: str, rc: RetrievalConfig) -> list[Hit]:
        if not rc.rerank_model:
            return hits
        if self.reranker is None:
            raise ValueError(f"RAG config {rc.name} reranks with {rc.rerank_model}, but the retriever has no reranker")
        model = rc.rerank_model
        missing = [h for h in hits if (model, query, h.chunk_id) not in self._rerank]
        if missing:
            scores = self.reranker(model).score(query, [h.text for h in missing])
            self._rerank.update({(model, query, h.chunk_id): s for h, s in zip(missing, scores, strict=True)})
        scored = [replace(h, rerank_score=self._rerank[(model, query, h.chunk_id)]) for h in hits]
        return sorted(scored, key=lambda h: (-(h.rerank_score or 0.0), str(h.chunk_id)))[:rc.top_k]

    def _anchored(self, hits: list[Hit], anchors: set[Anchor | None], rc: RetrievalConfig) -> list[Hit]:
        n = rc.anchor_chunks
        if not n or not self.document:
            return hits
        start = self.document[:n] if anchors & {Anchor.START, Anchor.BOTH} else []
        end = self.document[-n:] if anchors & {Anchor.END, Anchor.BOTH} else []
        if not start and not end:
            return hits
        pinned = {h.chunk_id for h in start}
        end = [h for h in end if h.chunk_id not in pinned]  # a short document: start and end overlap
        pinned |= {h.chunk_id for h in end}
        retrieved = {h.chunk_id: h for h in hits}
        return ([retrieved.get(h.chunk_id, h) for h in start] + [h for h in hits if h.chunk_id not in pinned]
                + [retrieved.get(h.chunk_id, h) for h in end])

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
        return order[:max(rc.top_k, rc.rerank_candidates) if rc.rerank_model else rc.top_k]
