# backend

The Python package `contract_extraction`. It will contain the REST API (Phase 5) and the pipeline worker (Phases 3–4).
It currently provides the core they build on: settings, domain models, persistence and file storage.
See [architecture §4–§8](../docs/architecture.md).

## Setup

```bash
cd backend
uv sync
docker compose -f ../docker/docker-compose.yml up -d --build --wait   # Postgres + Qdrant
uv run contract-extraction check                                      # settings, DB, schema, pipeline, Qdrant, LLM providers
uv run contract-extraction ingest path/to/contract.pdf                # register → decompose → chunk → embed → index
uv run pytest
```

`ingest` reuses earlier work. The same file is stored once. The latest decomposition with the pipeline's decomposition config is reused
unless you pass `--redecompose`. A ready index is reused, and it's rebuilt from its stored chunk rows if the Qdrant collection was lost.
Use `--pipeline NAME` for a non-default pipeline config.

OCR and hybrid decomposition (`decomposition_configs` rows `ocr` and `hybrid`) need Tesseract (`brew install tesseract`).

### HTTP API

```bash
uv run contract-extraction api       # 127.0.0.1:8000 (API__HOST / API__PORT); docs at /api/v1/docs
uv run contract-extraction worker    # executes the runs the API queues
```

```bash
B=http://localhost:8000/api/v1
curl -F file=@contract.pdf $B/documents                                   # 201 new / 200 already stored
curl -X POST $B/documents/<id>/runs -H 'content-type: application/json' \
     -d '{"fields":["customer_name"],"retrievals":["RAG02"]}'               # 202, Location: /api/v1/runs/<run id>
curl $B/runs/<run id>                                                      # poll state and progress
curl $B/runs/<run id>/results                                              # best values + every outcome
```

See [architecture §8](../docs/architecture.md) for all endpoints. Errors are RFC 9457 problem details.
The API has no CORS or auth of its own; it sits behind the gateway.

### Worker, status and cancel

```bash
uv run contract-extraction worker                       # executes queued runs (start more processes to scale)
uv run contract-extraction run contract.pdf --queue     # only queue; prints the run id
uv run contract-extraction status                       # recent runs: state, stage, progress, duration, error
uv run contract-extraction status RUN_ID                # one run: timeline (run_events) and best values
uv run contract-extraction cancel RUN_ID                # queued → cancelled now; running → stops before its next field
```

- **Heartbeat:** while a run executes (in a worker or inline), its `heartbeat_at` is updated every `WORKER__HEARTBEAT_SECONDS` (15 s).
- **Dead runs:** workers mark a running run without a heartbeat for `WORKER__STALE_AFTER_SECONDS` (120 s) as failed
  ("worker stopped responding"). There are no automatic retries; run it again.
- **Stopping a worker:** Ctrl-C (or SIGTERM) once cancels the current run at its next field and exits. Twice exits at once.

### LLM providers

```bash
uv run contract-extraction providers                                                    # list providers, URLs, models
uv run contract-extraction providers set ollama-local --base-url http://localhost:11435   # Docker Ollama
uv run contract-extraction providers set ollama-local --base-url http://localhost:11434   # native Ollama (default)
uv run contract-extraction providers set openrouter --enable                              # needs OPENROUTER_API_KEY
```

### Extraction runs

```bash
uv run contract-extraction run contract.pdf                                    # every field x every RAG config
uv run contract-extraction run contract.pdf --fields customer_name,payment_terms --retrievals RAG02
uv run contract-extraction run contract.pdf --no-judge --no-reuse --pipeline my-pipeline
```

`run` registers the file and queues a run. The run's snapshot holds the pipeline narrowed by your options. `run` then executes it
inline and prints the best value per field. Ctrl-C marks the run cancelled. Every call, its evidence and the verdicts are in the
database (`field_results`, `retrieval_hits`, `llm_calls`, `judgements`, `run_events`, view `v_best_values`).

**Speed:** a full default run is up to 12 fields × 7 RAG configs × 2 calls. With native Ollama on the Apple GPU, a call takes
about 7–15 s. Ollama in Docker on macOS is CPU-only and takes about 90–150 s per call. Reuse of repeated evidence cuts the number
of calls a lot on short documents. Narrow runs with `--fields` / `--retrievals` while experimenting.

## Configuration

- **Pipeline configuration** (providers, models, prompts, RAG configs, fields) lives in **the database**. It is read through
  `ConfigRepo.resolve_pipeline()`.
- **Settings** hold only connection details and paths. They come from `config/`, where later files override earlier ones:
  `.env` → `.env.<APP_ENV>` → `.env.local` → `.env.<APP_ENV>.local` → real environment variables. Nested keys use `__`
  (e.g. `DATABASE__URL`).
- **Secrets** go in `config/.env.local` (gitignored; see `.env.local.example`) or the environment. A provider row names its key's
  variable (`llm_providers.api_key_env`, e.g. `OPENROUTER_API_KEY`).

## Layout

```
src/contract_extraction/
  core/          settings, logging, errors
  domain/        enums mirroring the schema's CHECK values; resolved pipeline config (frozen, snapshot())
  persistence/   db.py (engine, sessions), models.py (ORM mirroring docker/schema.sql), repositories/
  providers/     chat, embedding and vector-store clients: Ollama, OpenAI-compatible (OpenRouter), Qdrant, in-memory
  decomposition/ pdf-converter wrapper (pymupdf / ocr / hybrid), header/footer removal, decomposition stage
  indexing/      chunking (per page, exact offsets, overlap), indexer (embed, upsert, chunk rows)
  ingestion.py   register → decompose → index, reusing earlier work
  storage.py     local file storage (staging + hashing, per-document folders, path guards)
  secrets.py     API key lookup by the env var named in the database
  cli.py         contract-extraction check | ingest
```

## Tests

`uv run pytest` recreates the `contract_extraction_test` database from `docker/schema.sql` and `docker/seed.sql`, then rolls back
each test. Point it elsewhere with `TEST_DATABASE_URL` (the database name must end in `_test`). Without a reachable Postgres, the
database tests are skipped.

Markers:
- `ocr` tests need Tesseract.
- `live` tests are deselected by default. Run them against real Ollama and Qdrant with `CE_LIVE=1 uv run pytest -m live`.

`tests/test_schema_matches_orm.py` compares `persistence/models.py` with the live schema (tables, columns, types, nullability, keys).
Run it after editing `schema.sql`.
