# backend

The Python package `contract_extraction`. It will contain the REST API (Phase 5) and the pipeline worker (Phases 3–4).
It currently provides the core they build on: settings, domain models, persistence and file storage.
See [architecture §4–§8](../docs/architecture.md).

## Setup

```bash
cd backend
uv sync
docker compose -f ../docker/docker-compose.yml up -d --build --wait   # Postgres + Qdrant
uv run contract-extraction check                                      # settings, DB, schema, default pipeline
uv run pytest
```

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
  storage.py     local file storage (staging + hashing, per-document folders, path guards)
  secrets.py     API key lookup by the env var named in the database
  cli.py         contract-extraction check
```

## Tests

`uv run pytest` recreates the `contract_extraction_test` database from `docker/schema.sql` and `docker/seed.sql`, then rolls back
each test. Point it elsewhere with `TEST_DATABASE_URL` (the database name must end in `_test`). Without a reachable Postgres, the
database tests are skipped.

`tests/test_schema_matches_orm.py` compares `persistence/models.py` with the live schema (tables, columns, types, nullability, keys).
Run it after editing `schema.sql`.
