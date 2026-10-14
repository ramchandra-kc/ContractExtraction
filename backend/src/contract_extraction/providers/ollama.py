"""Ollama: /api/chat and /api/embed."""

from __future__ import annotations

import time
from typing import Any

import httpx

from ..domain.config import ModelProfile
from ._http import post_json
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

    def complete(self, system: str, user: str, profile: ModelProfile) -> ChatResult:
        body: dict[str, Any] = {
            "model": profile.model.name,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "options": self.options(profile),
        }
        if profile.json_mode:
            body["format"] = "json"
        started = time.perf_counter()
        data = post_json(self.client, "/api/chat", body, f"Ollama chat ({profile.model.name})", profile.timeout_seconds)
        latency = int((time.perf_counter() - started) * 1000)
        text = (data.get("message") or {}).get("content")
        if text is None:
            raise ProviderError(f"Ollama chat ({profile.model.name}): no message in response")
        return ChatResult(text=text, latency_ms=latency, prompt_tokens=data.get("prompt_eval_count"),
                          completion_tokens=data.get("eval_count"),
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
