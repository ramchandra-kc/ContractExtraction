"""Ollama: /api/chat and /api/embed."""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import closing
from typing import Any

import httpx

from ..domain.config import ModelProfile
from ._http import cut_off, parse_chunk, post_json, stream_lines
from .base import ChatResult, ProviderError


class OllamaChat:
    def __init__(self, base_url: str, client: httpx.Client | None = None):
        self.client = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=600)

    @staticmethod
    def options(profile: ModelProfile) -> dict[str, Any]:
        opts: dict[str, Any] = {"temperature": float(profile.temperature)}
        if profile.top_p is not None:
            opts["top_p"] = float(profile.top_p)
        if profile.top_k is not None:
            opts["top_k"] = profile.top_k
        # Without num_ctx Ollama silently truncates prompts at its 4096-token default.
        if profile.num_ctx is not None:
            opts["num_ctx"] = profile.num_ctx
        if profile.max_tokens is not None:
            opts["num_predict"] = profile.max_tokens
        return opts | profile.extra.get("options", {})

    def complete(self, system: str, user: str, profile: ModelProfile,
                 checkpoint: Callable[[], None] | None = None) -> ChatResult:
        # Streamed, so the call can be aborted between chunks (see ChatClient.complete).
        body: dict[str, Any] = {
            "model": profile.model.name,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": True,
            "options": self.options(profile),
        }
        if profile.json_mode:
            body["format"] = "json"
        what = f"Ollama chat ({profile.model.name})"
        started = time.perf_counter()
        parts: list[str] = []
        final: dict[str, Any] | None = None
        with closing(stream_lines(self.client, "/api/chat", body, what, profile.timeout_seconds, checkpoint)) as lines:
            for line in lines:
                chunk = parse_chunk(line, what)
                parts.append((chunk.get("message") or {}).get("content") or "")
                if chunk.get("done"):
                    final = chunk
                    break
        latency = int((time.perf_counter() - started) * 1000)
        if final is None:
            raise ProviderError(f"{what}: the answer stream ended before it was done")
        if final.get("done_reason") == "length":
            raise cut_off(what, profile, "".join(parts))
        return ChatResult(text="".join(parts), latency_ms=latency, prompt_tokens=final.get("prompt_eval_count"),
                          completion_tokens=final.get("eval_count"),
                          params={k: v for k, v in body.items() if k not in ("messages", "stream")})


class OllamaEmbedder:
    def __init__(self, base_url: str, model: str, client: httpx.Client | None = None, timeout: float = 120):
        self.model = model
        self.client = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        data = post_json(self.client, "/api/embed", {"model": self.model, "input": texts}, f"Ollama embed ({self.model})")
        vectors = data.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise ProviderError(f"Ollama embed ({self.model}): expected {len(texts)} embeddings, got {len(vectors or [])}")
        return vectors
