"""Local cross-encoder rerankers (fastembed, ONNX on CPU): score how well each text answers a query.

A cross-encoder reads the query and a chunk together, so it judges relevance better than comparing two separately
made embeddings; it is too slow to run over a whole document, so it re-scores the best candidates of the fused
dense + keyword search (``extraction.retrieval``).

A model takes 2-3.5 GB of memory once loaded, so it loads only when a score is missing from the on-disk cache
(SQLite, keyed by model, query and chunk text; scores never change), and one process can fill the cache for many
(``experiment retrieval-eval`` does) before workers run. ``RERANK_THREADS`` caps the CPU threads a model uses
(default 4); ``RERANK_CACHE`` moves the cache (default ``~/.cache/contract-extraction/rerank.sqlite``). Models
download once to ``~/.cache/fastembed`` (override with ``FASTEMBED_CACHE_PATH``).
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from functools import cache
from pathlib import Path

from .base import ProviderError


class ScoreCache:
    """Cross-encoder scores by model, query and text, shared by every process on the machine."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, timeout=30, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS scores (key TEXT PRIMARY KEY, score REAL NOT NULL)")
        self._lock = threading.Lock()

    @staticmethod
    def key(model: str, query: str, text: str) -> str:
        return hashlib.sha256("\x1f".join((model, query, text)).encode()).hexdigest()

    def get(self, keys: list[str]) -> dict[str, float]:
        out: dict[str, float] = {}
        with self._lock:
            for i in range(0, len(keys), 500):
                part = keys[i:i + 500]
                rows = self._db.execute(f"SELECT key, score FROM scores WHERE key IN ({','.join('?' * len(part))})", part)
                out.update(rows.fetchall())
        return out

    def put(self, scores: dict[str, float]) -> None:
        with self._lock:
            self._db.executemany("INSERT OR REPLACE INTO scores VALUES (?, ?)", scores.items())


class FastEmbedReranker:
    def __init__(self, model: str, scores: ScoreCache | None = None, threads: int | None = None):
        self.model, self.scores = model, scores
        self.threads = threads or int(os.environ.get("RERANK_THREADS", "4"))
        self._encoder = None
        self._lock = threading.Lock()  # one ONNX session; parallel judge/extraction threads take turns

    def _load(self):
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except ImportError as exc:  # pragma: no cover - fastembed is a project dependency
            raise ProviderError(f"Reranker {self.model}: fastembed is not installed") from exc
        cache_dir = os.environ.get("FASTEMBED_CACHE_PATH") or str(Path.home() / ".cache" / "fastembed")
        try:
            return TextCrossEncoder(model_name=self.model, cache_dir=cache_dir, threads=self.threads)
        except ValueError as exc:
            raise ProviderError(f"Reranker {self.model}: {exc}") from exc

    def score(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        keys = [ScoreCache.key(self.model, query, t) for t in texts]
        known = self.scores.get(keys) if self.scores else {}
        missing = [i for i, k in enumerate(keys) if k not in known]
        if missing:
            with self._lock:
                if self._encoder is None:
                    self._encoder = self._load()
                new = [float(s) for s in self._encoder.rerank(query, [texts[i] for i in missing], batch_size=4)]
            fresh = {keys[i]: s for i, s in zip(missing, new, strict=True)}
            if self.scores:
                self.scores.put(fresh)
            known = {**known, **fresh}
        return [known[k] for k in keys]


@cache
def _scores() -> ScoreCache:
    path = os.environ.get("RERANK_CACHE") or Path.home() / ".cache" / "contract-extraction" / "rerank.sqlite"
    return ScoreCache(Path(path))


@cache
def reranker(model: str) -> FastEmbedReranker:
    return FastEmbedReranker(model, _scores())
