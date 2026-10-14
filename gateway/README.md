# gateway

Custom API gateway (FastAPI + httpx). Built in **Phase 6**. See [ADR 0002](../docs/adr/0002-custom-gateway.md).

**Owns:** the single entry point. It streams proxying of `/api/*` → backend, request IDs, access logs, timeouts, the upload
size limit, CORS and the aggregated `/health`. Authentication comes in the last phase.

**Talks to:** the [backend](../backend/) API.

**Must not:** contain business logic or access the database or file storage.

Port: **8080**.
