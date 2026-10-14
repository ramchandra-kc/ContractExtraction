"""OpenAI-compatible APIs (OpenRouter and others): /chat/completions and /embeddings."""

from __future__ import annotations

import time
from typing import Any

import httpx

from ..domain.config import ModelProfile
from ._http import post_json
from .base import ChatResult, ProviderError


def _client(base_url: str, api_key: str | None, timeout: float) -> httpx.Client:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout)


class OpenAICompatChat:
    def __init__(self, base_url: str, api_key: str | None, client: httpx.Client | None = None):
        self.client = client or _client(base_url, api_key, 600)

    @staticmethod
    def params(profile: ModelProfile) -> dict[str, Any]:
        p: dict[str, Any] = {"model": profile.model.name, "temperature": float(profile.temperature)}
        if profile.top_p is not None:
            p["top_p"] = float(profile.top_p)
        if profile.top_k is not None:
            p["top_k"] = profile.top_k  # OpenRouter accepts it; strict OpenAI servers ignore or reject it
        if profile.max_tokens is not None:
            p["max_tokens"] = profile.max_tokens
        if profile.json_mode:
            p["response_format"] = {"type": "json_object"}
        return p | profile.extra.get("params", {})

    def complete(self, system: str, user: str, profile: ModelProfile) -> ChatResult:
        params = self.params(profile)
        body = params | {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        started = time.perf_counter()
        data = post_json(self.client, "/chat/completions", body, f"chat ({profile.model.name})", profile.timeout_seconds)
        latency = int((time.perf_counter() - started) * 1000)
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise ProviderError(f"chat ({profile.model.name}): unexpected response {str(data)[:300]}") from None
        usage = data.get("usage") or {}
        return ChatResult(text=text, latency_ms=latency, prompt_tokens=usage.get("prompt_tokens"),
                          completion_tokens=usage.get("completion_tokens"), params=params)


class OpenAICompatEmbedder:
    def __init__(self, base_url: str, api_key: str | None, model: str, client: httpx.Client | None = None):
        self.model = model
        self.client = client or _client(base_url, api_key, 120)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        data = post_json(self.client, "/embeddings", {"model": self.model, "input": texts}, f"embed ({self.model})")
        items = sorted(data.get("data") or [], key=lambda d: d.get("index", 0))
        if len(items) != len(texts):
            raise ProviderError(f"embed ({self.model}): expected {len(texts)} embeddings, got {len(items)}")
        return [item["embedding"] for item in items]
