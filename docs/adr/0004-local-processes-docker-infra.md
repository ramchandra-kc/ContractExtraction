# ADR 0004: App services run locally, infrastructure runs in Docker

- Status: accepted (revised in Phase 1)
- Date: 2026-10-14

## Context

This is a research project that runs on one developer machine. Iterating fast on Python and TypeScript code matters more
than production parity. Postgres, Qdrant and a local LLM server are stateful third-party services that are tedious to
install natively.

## Decision

- **Docker**: one compose file, `docker/docker-compose.yml`. It runs:
  - **Postgres**, built from `docker/Dockerfile` with `schema.sql` and `seed.sql` baked in
  - **Qdrant**
  - **Ollama**, behind the optional `ollama` profile

  Each service has a named volume. Ports are published to 127.0.0.1 and can be overridden with `POSTGRES_PORT`, `QDRANT_PORT` and `OLLAMA_PORT`.
- **No migrations.** `schema.sql` is the single source of truth. It runs when the Postgres volume is empty.
  To change the schema, edit the file and recreate the database (`down -v`, then `up --build`).
- **Pluggable LLM providers.** Providers and models are rows in the database. Ollama can run in Docker or natively (native gives
  GPU access on macOS). A hosted provider such as OpenRouter needs no container.
- **Local processes**: backend API, backend worker(s), gateway (each via `uv run`) and frontend (`npm run dev`).

## Consequences

- Hot reload and debuggers work directly on app code.
- A clean database is one command away. The cost is that schema changes discard data, which is acceptable for research.
  Back up first with `pg_dump` if needed.
- The schema and seed are copied into the image rather than bind-mounted, so this works even when Docker Desktop can't
  access the project folder (e.g. macOS privacy restrictions on `~/Documents`).
- Five processes plus Docker are a lot to start by hand, so `scripts/dev.sh` (Phase 8) starts them all in one terminal
  and stops them together.
- Containerizing the app services is deferred. The separation of parts keeps that option open.
