"""Shared httpx call wrapper: one place that turns transport problems into ProviderError."""

from __future__ import annotations

from typing import Any

import httpx

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
