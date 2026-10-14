# ADR 0002: Custom API gateway service (FastAPI + httpx)

- Status: accepted
- Date: 2026-10-14

## Context

In the prototype the browser reached the backend directly, through the Vite dev proxy. CORS and upload limits lived in the
backend. We want one entry point that owns cross-cutting concerns, so the backend can focus on the domain.

We considered config-driven proxies (Nginx, Traefik), full API gateways (Kong, Envoy) and a small custom service.

## Decision

Write a **custom gateway** in Python (FastAPI + httpx, managed with uv), listening on `:8080`. It:

- proxies `/api/*` to the backend with streaming (no buffering of PDF uploads)
- adds and propagates `X-Request-ID`, writes access logs
- enforces the upload size limit and upstream timeouts, mapping upstream failures to `502`/`504`
- owns CORS
- exposes an aggregated `/health`
- will host authentication in the last phase

## Consequences

- We fully control the behavior, and it uses the same language and toolchain as the backend.
- It's more code to maintain than an Nginx config, so it must stay thin: **no business logic, no database access**.
- One extra hop locally. That's negligible next to LLM latency.

## Note (Phase 6)

Built with **Starlette** rather than FastAPI. FastAPI is built on Starlette, and the gateway needs no request models or OpenAPI of its own.
The decision stands: it's a custom Python gateway, using the same ASGI stack and httpx.
