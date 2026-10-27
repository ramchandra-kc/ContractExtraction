"""Local cross-encoder rerankers (fastembed, ONNX on CPU): score how well each text answers a query.

A cross-encoder reads the query and a chunk together, so it judges relevance better than comparing two separately
made embeddings; it is too slow to run over a whole document, so it re-scores the best candidates of the fused
dense + keyword search (``extraction.retrieval``). Models download once to ``~/.cache/fastembed`` (override with
``FASTEMBED_CACHE_PATH``) and load once per process.
"""

from __future__ import annotations

import os
import threading
from functools import cache
from pathlib import Path

from .base import ProviderError


class FastEmbedReranker:
    def __init__(self, model: str):
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except ImportError as exc:  # pragma: no cover - fastembed is a project dependency
            raise ProviderError(f"Reranker {model}: fastembed is not installed") from exc
        cache_dir = os.environ.get("FASTEMBED_CACHE_PATH") or str(Path.home() / ".cache" / "fastembed")
        try:
            self._encoder = TextCrossEncoder(model_name=model, cache_dir=cache_dir)
        except ValueError as exc:
            raise ProviderError(f"Reranker {model}: {exc}") from exc
        self._lock = threading.Lock()  # one ONNX session; parallel judge/extraction threads take turns

    def score(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        with self._lock:
            return [float(s) for s in self._encoder.rerank(query, texts, batch_size=8)]


@cache
def reranker(model: str) -> FastEmbedReranker:
    return FastEmbedReranker(model)
