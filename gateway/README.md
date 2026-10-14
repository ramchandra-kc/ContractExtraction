# gateway

The single entry point to the API: a small **streaming reverse proxy** (Starlette + httpx) in front of the backend.
It has no business logic and no database. See [ADR 0002](../docs/adr/0002-custom-gateway.md) and [architecture §9](../docs/architecture.md).

```bash
cd gateway
uv sync
uv run contract-gateway        # 127.0.0.1:8080 → backend 127.0.0.1:8000
uv run pytest
```

| Path | Behavior |
|---|---|
| `/api/v1/*` (all methods) | streamed to the backend unchanged (path encoding, query, headers except hop-by-hop) and streamed back |
| `GET /health` | the gateway itself + the backend's `/api/v1/health`: 200, or 503 with components |
| anything else | 404 (problem details) |

**What it does on every request:**
- **Request id:** `X-Request-ID` is kept when it matches `[A-Za-z0-9._-]{1,64}`, otherwise replaced. It's sent to the backend, returned to the client and logged.
- **Forwarding headers:** client-sent `X-Forwarded-*` / `Forwarded` / `X-Real-IP` are dropped. The gateway sets `X-Forwarded-For/-Proto/-Host` itself.
  Uvicorn runs with `proxy_headers=False`, because this is the edge.
- **Upload limit:** `GATEWAY__MAX_UPLOAD_MB` (50). A larger `Content-Length` → **413 before the backend is contacted**; chunked bodies are counted while streaming.
  Keep it at or below the backend's `STORAGE__MAX_UPLOAD_MB`.
- **Failures:** the backend is unreachable → **502**; a connect, read, write or pool timeout → **504**. Both are RFC 9457 problem details,
  like the backend's errors. Nothing is retried.
- **CORS:** only for `GATEWAY__CORS_ORIGINS` (default `http://localhost:5173`); `Location` and `X-Request-ID` are exposed to the browser.
- **Hardening:** `X-Content-Type-Options: nosniff`; the backend's `Server` header is not passed on.

Configuration is in `config/.env` (copy `config/.env.local.example` to `.env.local` for overrides).

Later: authentication goes here (last phase). Rate limiting and serving the built frontend may be added when needed.
