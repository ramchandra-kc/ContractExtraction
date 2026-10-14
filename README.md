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

## Quick start

Needs bash, curl, Docker, [uv](https://docs.astral.sh/uv/), Node.js with npm, and an LLM (see below).

```bash
scripts/dev.sh                 # Docker services, dependencies, check, then API + worker + gateway + frontend
                               # → http://localhost:5173 ; Ctrl-C stops the app processes
scripts/dev.sh status          # every service, ok / FAIL
scripts/dev.sh smoke           # end to end through the gateway: upload, a one-field run, results (~30 s)
scripts/dev.sh test            # every offline test suite
scripts/dev.sh down            # stop the Docker services (data is kept)
scripts/dev.sh reset           # wipe the database, vectors and stored files (asks first; --yes skips that)
```

**Platforms:** `scripts/dev.sh` is a bash script for macOS, Linux and Windows. On Windows, run it in **Git Bash** (from
Git for Windows) or WSL2, not in PowerShell or cmd.

| Platform | Status | Ctrl-C |
|---|---|---|
| macOS (bash 3.2+) | tested end to end | graceful: the worker cancels its current run at the next field |
| Linux | the script's logic tested on Debian (bash 5, no `lsof` / `pgrep`); the full stack not yet | graceful |
| Windows, WSL2 | behaves as Linux | graceful |
| Windows, Git Bash | not tested yet | processes are terminated (`taskkill`); a run in progress is marked failed by the next worker after 120 s |

`up` takes `--workers N` (default 1) and `--ollama docker`. Each process's output is shown with a `[name]` prefix and
kept in `.dev/logs/`. If a process exits, the script stops the others and shows the end of its log. On Ctrl-C the worker
cancels its current run at the next field, the same as a single Ctrl-C on `contract-extraction worker`. The API and
the worker don't reload code changes, so restart the script after editing backend code.

**LLMs:** choose either Ollama, or both. The `ollama-local` provider in the database decides which one is used.

| Ollama | Port | Start | Notes |
|---|---|---|---|
| native (`Ollama.app`) | 11434 | open the app, then `ollama pull nomic-embed-text` and `ollama pull llama3.1:8b` | uses the Apple GPU, about 8× faster on macOS (default) |
| Docker | 11435 | `scripts/dev.sh --ollama docker` | CPU-only on macOS; runs next to the native one |

```bash
cd backend
uv run contract-extraction providers                                                   # which URL is in use
uv run contract-extraction providers set ollama-local --base-url http://localhost:11435  # use Docker Ollama
uv run contract-extraction providers set ollama-local --base-url http://localhost:11434  # back to native
```

Each run records the provider URL it used in its config snapshot. Without a reachable model, `scripts/dev.sh` warns
and still starts: uploads, the page viewer, configuration and ground truth work, runs don't.

### Running parts by hand

```bash
docker compose -f docker/docker-compose.yml up -d --build --wait     # Postgres + Qdrant (add --profile ollama for Docker Ollama)
cd backend  && uv run contract-extraction api                         # :8000
cd backend  && uv run contract-extraction worker                      # executes queued runs
cd gateway  && uv run contract-gateway                                # :8080
cd frontend && npm run dev                                            # :5173
```

Each part's README has the details.

### Ports and troubleshooting

Ports can be changed with `POSTGRES_PORT`, `QDRANT_PORT` and `OLLAMA_PORT` (Docker), and `API__PORT` and `GATEWAY__PORT`
(app processes). Export them in the shell rather than putting them in a part's `.env.local`, so that `scripts/dev.sh` uses
the same values. The script then points the gateway and Vite at the moved ports. Postgres credentials default to
`contract` / `contract`, database `contract_extraction`.

| Symptom | Fix |
|---|---|
| `Docker isn't running` | start Docker Desktop |
| `port 8080 is already in use by …` | stop that process (often a stack in another terminal), or move the port as above |
| `FAIL ollama-local:…: not available` | `ollama pull <model>`, or point the provider at a running Ollama |
| `FAIL schema: missing tables` after editing `docker/schema.sql` | `scripts/dev.sh reset` (the schema has no migrations) |
| a process exits at start | the end of its log is printed; the full log is in `.dev/logs/<name>.log` |
| smoke: `already has an active run` | wait for it, or `uv run contract-extraction cancel <run id>` in `backend/` |

## Documentation

- [Architecture](docs/architecture.md): components, boundaries, data flow and conventions
- [Project plan](docs/project-plan.md): roadmap and status of each phase
- [Architecture decision records](docs/adr/)

## Status

Phases 0–8 are done: architecture, Docker services, the backend (core, pipeline, worker, API), the gateway, the frontend,
ground truth with evaluation, config editing, and the dev script with its smoke test. Next is authentication (9). Each phase gets its own plan, which is approved before implementation.
See the [project plan](docs/project-plan.md).
