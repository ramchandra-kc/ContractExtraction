"""Shared httpx call wrappers: one place that turns transport problems into ProviderError."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from ..domain.config import ModelProfile
from .base import ProviderError


def request_json(client: httpx.Client, method: str, url: str, what: str, body: dict[str, Any] | None = None,
                 timeout: float | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        resp = client.request(method, url, json=body, params=params,
                              timeout=timeout if timeout is not None else client.timeout)
    except httpx.TimeoutException as exc:
        raise ProviderError(f"{what}: timed out ({exc.__class__.__name__})", timeout=True) from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f"{what}: {exc.__class__.__name__}: {exc}") from exc
    if resp.status_code >= 400:
        raise ProviderError(f"{what}: HTTP {resp.status_code}: {resp.text[:500]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise ProviderError(f"{what}: response is not JSON: {resp.text[:200]}") from exc


def post_json(client: httpx.Client, url: str, body: dict[str, Any], what: str,
              timeout: float | None = None) -> dict[str, Any]:
    return request_json(client, "POST", url, what, body, timeout)


def stream_lines(client: httpx.Client, url: str, body: dict[str, Any], what: str, timeout: float | None = None,
                 checkpoint: Callable[[], None] | None = None) -> Iterator[str]:
    """POST ``body`` and yield the non-empty lines of the response as they arrive.

    ``timeout`` bounds each wait for data and the whole call. ``checkpoint`` runs before each line;
    an exception it raises ends the call: the connection is closed, so the server stops generating.
    Consume this inside ``contextlib.closing`` so the connection is also closed when the caller stops early.
    """
    timeout = timeout if timeout is not None else client.timeout.read
    deadline = time.monotonic() + timeout if timeout is not None else None
    try:
        with client.stream("POST", url, json=body, timeout=timeout) as resp:
            if resp.status_code >= 400:
                resp.read()
                raise ProviderError(f"{what}: HTTP {resp.status_code}: {resp.text[:500]}")
            for line in resp.iter_lines():
                if checkpoint is not None:
                    checkpoint()
                if deadline is not None and time.monotonic() > deadline:
                    raise ProviderError(f"{what}: timed out (no complete answer after {timeout:g} s)", timeout=True)
                if line.strip():
                    yield line
    except httpx.TimeoutException as exc:
        raise ProviderError(f"{what}: timed out ({exc.__class__.__name__})", timeout=True) from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f"{what}: {exc.__class__.__name__}: {exc}") from exc


def parse_chunk(text: str, what: str) -> dict[str, Any]:
    """One JSON object of a streamed answer."""
    try:
        chunk = json.loads(text)
    except ValueError as exc:
        raise ProviderError(f"{what}: stream chunk is not JSON: {text[:200]}") from exc
    if not isinstance(chunk, dict):
        raise ProviderError(f"{what}: unexpected stream chunk {text[:200]}")
    if chunk.get("error"):
        raise ProviderError(f"{what}: {chunk['error']}")
    return chunk


def cut_off(what: str, profile: ModelProfile, text: str) -> ProviderError:
    """The answer stopped at the output token limit (a JSON answer cut there never parses)."""
    limit = f"max_tokens ({profile.max_tokens})" if profile.max_tokens else "the model's output limit"
    return ProviderError(f"{what}: answer cut off at {limit}: {text[:200]!r}")
