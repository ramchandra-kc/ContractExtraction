# ADR 0004: App services run locally, infrastructure runs in Docker

- Status: accepted
- Date: 2026-10-14

## Context

This is a research project that runs on one developer machine. Iterating fast on Python and TypeScript code matters more
than production parity. Postgres, Qdrant and Ollama are stateful third-party services that are tedious to install natively.

## Decision

- **Docker** (`database/docker-compose.yml`): Postgres, Qdrant, Ollama, each with a named volume and a healthcheck. Ports are published to localhost.
- **Local processes**: backend API, backend worker(s), gateway (each via `uv run`) and frontend (`npm run dev`).
- `scripts/infra-up.sh` starts the containers. It reuses a Qdrant or Ollama that is already running locally (e.g. native
  Ollama with GPU access on macOS) and pulls the required models.

## Consequences

- Hot reload and debuggers work directly on app code.
- Native Ollama on macOS can use the GPU, which Docker on macOS cannot. The script lets us prefer it.
- Containerizing the app services is deferred. The separation of parts keeps that option open.
