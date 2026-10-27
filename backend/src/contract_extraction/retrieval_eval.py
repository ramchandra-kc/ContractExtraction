"""Retrieval-only evaluation: how often RAG configs find a label's evidence, without any LLM call.

For every document, the pipeline's decomposition and index are ensured (reused when they exist), then each labelled
field whose label has a value and an evidence quote is retrieved under every RAG config variant, exactly as a run
would (``extraction.retrieval.Retriever``, field granularity), and matched against the quote (``evidence.py``).

Variants: each named RAG config as stored, or, with ``top_ks`` / ``thresholds``, one copy per value (the threshold
sets both ``score_threshold`` and ``min_score``). The rank of the first evidence chunk gives recall@n for every n up to
the variant's top_k, so one variant with a large top_k already traces the recall curve.

Embeddings of the queries are the only model calls (local), so sweeps take minutes and cost nothing.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from itertools import product
from typing import Any

from .core.settings import Settings
from .domain.config import RetrievalConfig
from .domain.enums import HitSource
from .evidence import Matcher, confidence_from_notes, quote_from_notes
from .extraction.retrieval import Hit, Retriever
from .indexing.indexer import build_index
from .ingestion import ensure_decomposition
from .persistence import models as m
from .persistence.db import Database
from .persistence.repositories import ConfigRepo
from .persistence.repositories.artifacts import IndexRepo
from .persistence.repositories.ground_truth import GroundTruthRepo
from .pipeline.executor import Providers
from .storage import FileStorage

RECALL_AT = (1, 3, 5, 10, 20)


@dataclass
class RetrievalRow:
    document: str
    field: str
    value_type: str
    priority: str
    retrieval_config: str
    top_k: int
    threshold: float
    hits: int
    evidence_fragments: int
    evidence_any: bool
    evidence_all: bool
    evidence_rank: int | None
    evidence_indexed: bool | None
    evidence_score: float | None  # dense score of the first evidence chunk (None: not retrieved or keyword-only)
    top_score: float | None  # best dense score among the hits
    label_confidence: str | None = None


def variants(configs: list[RetrievalConfig], top_ks: list[int] | None = None,
             thresholds: list[float] | None = None, per_query_tops: list[int] | None = None) -> list[RetrievalConfig]:
    """Each config, or one copy per top_k × threshold × per_query_top, named e.g. ``RAG02 k=10 t=0.3 q=5``.

    A config retrieves at most per_query_top hits per query before merging, so top_k only matters up to
    per_query_top × the number of queries (one without query expansion): sweep both."""
    out = []
    for rc in configs:
        for k, t, q in product(top_ks or [None], thresholds if thresholds is not None else [None], per_query_tops or [None]):
            update: dict[str, Any] = {}
            if k is not None:
                update["top_k"] = k
            if t is not None:
                update["score_threshold"] = update["min_score"] = Decimal(str(t))
            if q is not None:
                update["per_query_top"] = q
            name = (rc.name + (f" k={k}" if k is not None else "") + (f" t={t:g}" if t is not None else "")
                    + (f" q={q}" if q is not None else ""))
            out.append(rc.model_copy(update={**update, "name": name}) if update else rc)
    return out


def evaluate(db: Database, storage: FileStorage, settings: Settings, providers: Providers, pipeline_name: str | None,
             documents: list[m.Document], configs: list[RetrievalConfig],
             report: Callable[[str], None] = print) -> list[RetrievalRow]:
    with db.session() as s:
        pipeline = ConfigRepo(s).resolve_pipeline(pipeline_name)
    fields = {f.id: f for f in pipeline.field_set.fields}
    embedder = providers.embedder(pipeline.index.embedding_model)
    store = providers.store(pipeline.index.vector_store)
    matcher, rows = Matcher(), []
    for n, doc in enumerate(documents, start=1):
        with db.session() as s:
            gt = GroundTruthRepo(s)
            quoted = [(fields[f.id], quote, confidence_from_notes(label.notes))
                      for f, label in gt.labels(doc.id, gt.field_set())
                      if label is not None and label.expected_value not in (None, "") and f.id in fields
                      and (quote := quote_from_notes(label.notes))]
        if not quoted:
            report(f"[{n}/{len(documents)}] {doc.code}: no labels with an evidence quote, skipped")
            continue
        dec = ensure_decomposition(db, storage, doc.id, pipeline.decomposition)
        idx = build_index(db, dec.decomposition_id, dec.document_code, pipeline.index, embedder, store)
        with db.session() as s:
            chunks = IndexRepo(s).chunks(idx.vector_index_id)
            document = [Hit(c.id, None, c.page_start, c.text, None, source=HitSource.ANCHOR) for c in chunks]
            matcher.add_chunks({c.id: c.text for c in chunks})
        chunk_ids = [h.chunk_id for h in document]
        retriever = Retriever(store, idx.collection_name, embedder, document)
        for f, quote, confidence in quoted:
            for rc in configs:
                hits = retriever.retrieve(f, rc)
                ev = matcher.match(quote, [(i, h.chunk_id) for i, h in enumerate(hits, start=1)], chunk_ids)
                if ev is None:
                    continue
                first = hits[ev.rank - 1] if ev.rank else None
                dense = [h.score for h in hits if h.score is not None]
                rows.append(RetrievalRow(
                    doc.code, f.key, str(f.value_type), str(f.priority), rc.name, rc.top_k, float(rc.min_score), len(hits),
                    ev.fragments, ev.any, ev.all, ev.rank, ev.indexed, first.score if first else None,
                    max(dense) if dense else None, confidence))
        report(f"[{n}/{len(documents)}] {doc.code}: {len(quoted)} quoted labels × {len(configs)} RAG configs "
               f"({idx.chunk_count} chunks, index {'reused' if idx.reused else 'built'})")
    return rows


def _rate(xs: list[bool]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def _quality(rows: list[RetrievalRow]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "labels": len(rows),
        "documents": len({r.document for r in rows}),
        "recall": _rate([r.evidence_any for r in rows]),
        "recall_all": _rate([r.evidence_all for r in rows]),
        "mrr": round(statistics.fmean(1 / r.evidence_rank if r.evidence_rank else 0.0 for r in rows), 4) if rows else None,
    }
    for n in RECALL_AT:
        out[f"recall_at_{n}"] = _rate([r.evidence_rank is not None and r.evidence_rank <= n for r in rows])
    out["not_indexed"] = _rate([r.evidence_indexed is False for r in rows if r.evidence_indexed is not None])
    out["mean_hits"] = round(statistics.fmean(r.hits for r in rows), 2) if rows else None
    scores = [r.evidence_score for r in rows if r.evidence_score is not None]
    out["evidence_score_median"] = round(statistics.median(scores), 4) if scores else None
    return out


def summary(rows: list[RetrievalRow], by: tuple[str, ...] = ("retrieval_config",)) -> list[dict[str, Any]]:
    """Quality per group of rows (by RAG config by default; add e.g. ``value_type`` for a breakdown), in first-seen
    order. recall_at_N counts a hit at rank ≤ N, so N beyond the config's top_k equals plain recall."""
    groups: dict[tuple, list[RetrievalRow]] = defaultdict(list)
    for r in rows:
        groups[tuple(getattr(r, k) for k in by)].append(r)
    return [{**dict(zip(by, key, strict=True)), **_quality(g)} for key, g in groups.items()]
