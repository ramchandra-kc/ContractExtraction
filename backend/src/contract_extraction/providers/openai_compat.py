"""OpenAI-compatible APIs (OpenRouter and others): /chat/completions and /embeddings."""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import closing
from typing import Any

import httpx

from ..domain.config import ModelProfile
from ._http import cut_off, parse_chunk, post_json, stream_lines
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

    def complete(self, system: str, user: str, profile: ModelProfile,
                 checkpoint: Callable[[], None] | None = None) -> ChatResult:
        # Streamed (server-sent events), so the call can be aborted between chunks (see ChatClient.complete).
        params = self.params(profile)
        body = params | {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                         "stream": True, "stream_options": {"include_usage": True}}
        what = f"chat ({profile.model.name})"
        started = time.perf_counter()
        parts: list[str] = []
        usage: dict[str, Any] = {}
        finish: str | None = None
        done = False
        with closing(stream_lines(self.client, "/chat/completions", body, what, profile.timeout_seconds, checkpoint)) as lines:
            for line in lines:
                if not line.startswith("data:"):
                    continue  # comments (": keep-alive") and other SSE fields
                data = line[5:].strip()
                if data == "[DONE]":
                    done = True
                    break
                chunk = parse_chunk(data, what)
                usage = chunk.get("usage") or usage
                for choice in chunk.get("choices") or []:
                    parts.append((choice.get("delta") or {}).get("content") or "")
                    finish = choice.get("finish_reason") or finish
        latency = int((time.perf_counter() - started) * 1000)
        if not done and finish is None:
            raise ProviderError(f"{what}: the answer stream ended before it was done")
        if finish == "length":
            raise cut_off(what, profile, "".join(parts))
        return ChatResult(text="".join(parts), latency_ms=latency, prompt_tokens=usage.get("prompt_tokens"),
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
