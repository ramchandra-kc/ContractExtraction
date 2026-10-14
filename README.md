# ContractExtraction

A research project that extracts structured data points from contract PDFs, such as customer name, payment terms, project
dates, penalties and force majeure provisions. It combines PDF decomposition, retrieval-augmented generation with a local LLM,
and an LLM judge that grades every answer.

```
PDF ─► decompose ─► chunk + embed ─► vector index ─► retrieve ─► extract (LLM) ─► judge (LLM) ─► results
```

## Parts

The project is a monorepo with separate parts. Each part has its own folder, config and run command.

| Folder | Part | Runs as | Port |
|---|---|---|---|
| [`frontend/`](frontend/) | React single-page app | local process (Vite) | 5173 |
| [`gateway/`](gateway/) | API gateway: the single entry point for the frontend (`uv run contract-gateway`) | local process | 8080 |
| [`backend/`](backend/) | REST API (`contract-extraction api`) and pipeline worker (`contract-extraction worker`) | local processes | 8000 (API) |
| [`docker/`](docker/) | Postgres (with the schema and default config), Qdrant, and optionally Ollama | Docker | 5432 / 6333 / 11434 |

LLMs are pluggable: a local Ollama (Docker or native) or a hosted provider such as OpenRouter, configured in the database.

## Quick start (services)

```bash
docker compose -f docker/docker-compose.yml up -d --build --wait                    # Postgres + Qdrant
docker compose -f docker/docker-compose.yml down -v                                 # wipe everything (clean database)
```

**LLMs:** choose either Ollama, or both. The `ollama-local` provider in the database decides which one is used.

| Ollama | Port | Start | Notes |
|---|---|---|---|
| native (`Ollama.app`) | 11434 | open the app, then `ollama pull nomic-embed-text` and `ollama pull llama3.1:8b` | uses the Apple GPU, about 8× faster on macOS (default) |
| Docker | 11435 | add `--profile ollama` to the `up` command | CPU-only on macOS; runs next to the native one |

```bash
cd backend
uv run contract-extraction providers                                                   # which URL is in use
uv run contract-extraction providers set ollama-local --base-url http://localhost:11435  # use Docker Ollama
uv run contract-extraction providers set ollama-local --base-url http://localhost:11434  # back to native
```

Each run records the provider URL it used in its config snapshot.

Ports can be changed with `POSTGRES_PORT`, `QDRANT_PORT` and `OLLAMA_PORT`. Postgres credentials default to
`contract` / `contract`, database `contract_extraction`.

## Documentation

- [Architecture](docs/architecture.md): components, boundaries, data flow and conventions
- [Project plan](docs/project-plan.md): roadmap and status of each phase
- [Architecture decision records](docs/adr/)

## Status

Phases 0–7 are done: architecture, Docker services, the backend (core, pipeline, worker, API), the gateway and the frontend.
Next are config editing and ground truth (7b), the dev script (8) and authentication (9). Each phase gets its own plan, which is approved before implementation.
See the [project plan](docs/project-plan.md).
