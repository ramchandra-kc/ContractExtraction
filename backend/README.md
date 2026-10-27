# backend

The Python package `contract_extraction`: the REST API, the pipeline worker and the `contract-extraction` CLI, over shared
settings, domain models, persistence, providers and file storage. See [architecture §4–§8](../docs/architecture.md).
To run the whole stack, use `scripts/dev.sh` from the repository root (see the [README](../README.md)); the commands
below run single parts.

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

OCR and hybrid decomposition (`decomposition_configs` rows `ocr` and `hybrid`) and image documents need Tesseract (`brew install tesseract`).

Supported source formats come from the converter registry in `decomposition/converters/` (`GET /config/formats` lists them).
The format is detected from the file's content (and, for text formats, its extension), not from the upload's content type.
To add a format, write a converter module with a `SPEC` and add it to `REGISTRY`.

### HTTP API

```bash
uv run contract-extraction api       # 127.0.0.1:8000 (API__HOST / API__PORT); docs at /api/v1/docs
uv run contract-extraction openapi   # the OpenAPI document on stdout (-o FILE to write it); needs no database
uv run contract-extraction worker    # executes the runs the API queues
```

```bash
B=http://localhost:8000/api/v1
curl -F file=@contract.pdf $B/documents                                   # 201 new / 200 already stored
curl -X POST $B/documents/<id>/runs -H 'content-type: application/json' \
     -d '{"fields":["parties"],"retrievals":["RAG02"]}'                     # 202, Location: /api/v1/runs/<run id>
curl $B/runs/<run id>                                                      # poll state and progress
curl $B/runs/<run id>/results                                              # best values (with ground truth) + every outcome
curl -X PUT $B/documents/<id>/ground-truth/<field id> -H 'content-type: application/json' \
     -d '{"expected_value": "Acme Pty Ltd"}'                                # label a field ("" = not in this contract)
curl $B/config/catalog                                                     # every config row, for editing
curl -X PATCH $B/config/retrievals/RAG01 -H 'content-type: application/json' -d '{"top_k": 5}'   # affects runs queued afterwards
```

See [architecture §8](../docs/architecture.md) for all endpoints. Errors are RFC 9457 problem details.
The API has no CORS or auth of its own; it sits behind the gateway.

### Worker, status and cancel

```bash
uv run contract-extraction worker                       # executes queued runs (start more processes to scale)
uv run contract-extraction run contract.pdf --queue     # only queue; prints the run id
uv run contract-extraction status                       # recent runs: state, stage, progress, duration, error
uv run contract-extraction status RUN_ID                # one run: timeline (run_events) and best values
uv run contract-extraction cancel RUN_ID                # queued → cancelled now; running → stops within seconds
```

- **Heartbeat:** while a run executes (in a worker or inline), its `heartbeat_at` is updated every `WORKER__HEARTBEAT_SECONDS` (15 s).
- **Dead runs:** workers mark a running run without a heartbeat for `WORKER__STALE_AFTER_SECONDS` (120 s) as failed
  ("worker stopped responding"). There are no automatic retries; run it again.
- **Stopping a worker:** Ctrl-C (or SIGTERM) once cancels the current run and exits. Twice exits at once.
- **Cancelling:** a running run stops before its next field, or during a model call: answers are streamed and the call is
  aborted (the connection closed, so the model stops generating) within about 2 s of the model's next token. A model
  still reading a long prompt can't be interrupted until its first token.
- **Model limits:** set `max_tokens` on every model profile. In JSON mode a local model sometimes generates without end,
  and Ollama keeps going past its context window, so only `timeout_seconds` would stop it. An answer cut off at
  `max_tokens` is recorded as an error for that field.

### LLM providers

```bash
uv run contract-extraction providers                                                    # list providers, URLs, models
uv run contract-extraction providers set ollama-local --base-url http://localhost:11435   # Docker Ollama
uv run contract-extraction providers set ollama-local --base-url http://localhost:11434   # native Ollama (default)
uv run contract-extraction providers set openrouter --enable                              # needs OPENROUTER_API_KEY
```

`docker/seed_presets.sql` adds low-cost OpenRouter models and the `or-*` pipelines (plus `local-fast` and `local-hybrid`).
It skips rows that already exist, so `../scripts/dev.sh presets` applies it to the running database without a reset.

### Extraction runs

```bash
uv run contract-extraction run contract.pdf                                    # detect the type, then its fields x every RAG config
uv run contract-extraction run contract.pdf --contract-types msa,sow           # skip detection: these types' fields
uv run contract-extraction run contract.pdf --fields parties,payment_terms --retrievals RAG02
uv run contract-extraction run contract.pdf --no-judge --no-reuse --pipeline my-pipeline
```

`run` registers the file and queues a run. The run's snapshot holds the pipeline narrowed by your options. `run` then executes it
inline and prints the best value per field. Ctrl-C marks the run cancelled. Every call, its evidence and the verdicts are in the
database (`field_results`, `retrieval_hits`, `llm_calls`, `judgements`, `run_events`, view `v_best_values`).

**Which fields:** `--fields` extracts exactly those. Otherwise the run first **classifies** the document (one LLM call on its
first pages, stage `classifying`) and extracts the union of the detected types' fields, most important (P1) first. A type is
used when its confidence reaches the pipeline's `classification_min_confidence` (0.5); with none, or when classification is
off, the fallback type **Other** is used (44 fields: Core, Commercial, Risk & Liability). `--contract-types` skips detection.
The pipeline's `min_priority` (P3 = all) can limit runs to P1 or P1–P2 fields. What was decided is in `run_classifications`
and the run's events. Answers that do not fit the field's type (wrong JSON type, value outside an enum) are recorded as
`error` results; enum spellings such as "One Way" are normalised to `one_way` first.

**Calls per field or per group:** a pipeline's `extraction_granularity` is `field` (one retrieval and call per field) or
`group`: one call per field group (Core, Commercial, …, or the type's own fields, split at `group_max_fields`), with
evidence retrieved by all the group's queries. Each field still gets its own result and verdict, so the two modes compare
directly in experiments. Group calls use the generic prompt built from descriptions (hand-written field prompts apply only
in `field` mode); the call is linked to its results through `llm_call_field_results`.

**Speed:** a default run is one classification call plus up to 70 fields × 7 RAG configs × 2 calls (an MSA has 66 fields).
With native Ollama on the Apple GPU, a call takes
about 7–15 s. Ollama in Docker on macOS is CPU-only and takes about 90–150 s per call. Reuse of repeated evidence cuts the number
of calls a lot on short documents. Narrow runs with `--fields` / `--retrievals` while experimenting.

### Draft ground truth

```bash
uv run contract-extraction labels import ../test_data/labels --dry-run         # validate and report, change nothing
uv run contract-extraction labels import ../test_data/labels --tag p1-drafts   # register the contracts, set the labels
```

`labels import` reads one JSON file per contract (format in `labels.py`; drafted e.g. by Claude Cowork with
[`docs/labelling/cowork-labelling-prompt.md`](../docs/labelling/cowork-labelling-prompt.md)). Paths in the files are
relative to the repository root. Each contract is registered like an upload (not decomposed), its contract types are set,
and each value is validated like a label set in the UI. Values that don't fit are listed and skipped. Labels are stored
as drafts: `ground_truth.created_by` is the file's `labelled_by`, and the notes hold the evidence quote, location and
confidence. Editing a label in the UI clears `created_by`, so importing again keeps your edits (and labelled contract
types) unless `--overwrite`.

## Configuration

- **Pipeline configuration** (providers, models, prompts, RAG configs, fields) lives in **the database**. It is read through
  `ConfigRepo.resolve_pipeline()`.
- **Fields and contract types** come from [`docs/contract_types_and_fields.md`](../docs/contract_types_and_fields.md):
  18 contract types plus the fallback **Other**, 286 fields, each with a type, a priority (P1–P3) and a description. After
  editing the document, regenerate the seed and recreate the database:

  ```bash
  uv run contract-extraction gen-catalogue                  # writes docker/seed_catalogue.sql (checks the document first)
  uv run contract-extraction gen-catalogue --with-queries   # also asks the default extraction model for search queries
  ../scripts/dev.sh reset                                   # wipes the dev database and loads the new seed
  ```

  Generated search queries are kept in `docs/contract_field_queries.json` (review and edit freely; fields without any use
  their label and description). Catalogue fields have no hand-written prompt: the extraction prompt is built from the
  field's description and value type (`extraction/prompts.py`); a `user_prompt` set in the UI overrides it.
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
  decomposition/ converters/ (format registry, detection; pdf-converter wrapper for pymupdf / ocr / hybrid), header/footer removal, decomposition stage
  indexing/      chunking (per page, exact offsets, overlap), indexer (embed, upsert, chunk rows)
  extraction/    retrieval (query expansion, thresholds, merge), prompts, answer parsing, judge
  pipeline/      run options and the executor (stages, progress, events, reuse of repeated evidence)
  api/           FastAPI app, routes/, schemas, problem details, dependencies (session per request)
  ingestion.py   register → decompose → index, reusing earlier work
  labels.py      import of draft ground truth from label files
  storage.py     local file storage (staging + hashing, per-document folders, path guards)
  secrets.py     API key lookup by the env var named in the database
  health.py      liveness and readiness, shared by /health and `check`
  worker.py      claim loop (SKIP LOCKED), heartbeat, cancellation, stale-run cleanup
  catalogue.py   contract types and fields parsed from docs/contract_types_and_fields.md → docker/seed_catalogue.sql
  cli.py         contract-extraction check | ingest | run | worker | status | cancel | api | openapi | providers | gen-catalogue | labels
```

## Tests

`uv run pytest` recreates the `contract_extraction_test` database from `docker/schema.sql`, `seed.sql`, `seed_catalogue.sql` and `seed_presets.sql`, then rolls back
each test. Point it elsewhere with `TEST_DATABASE_URL` (the database name must end in `_test`). Without a reachable Postgres, the
database tests are skipped.

Markers:
- `ocr` tests need Tesseract.
- `live` tests are deselected by default. Run them against real Ollama and Qdrant with `CE_LIVE=1 uv run pytest -m live`.
- `smoke` (`tests/test_smoke.py`) is deselected by default. It runs end to end over HTTP against the running dev stack
  (frontend proxy → gateway → API → worker → models): `scripts/dev.sh smoke`. It uses no test database. It uploads one fixed
  PDF (cached in `.dev/smoke.pdf`) and queues a one-field run, which stays in the dev database.

`tests/test_schema_matches_orm.py` compares `persistence/models.py` with the live schema (tables, columns, types, nullability, keys).
Run it after editing `schema.sql`.

`tests/test_openapi_matches_frontend.py` compares the API's OpenAPI document with `frontend/openapi.json`, which the frontend's
types are generated from. After changing the API, run `npm run gen:api` in `frontend/`.

`tests/test_catalogue.py` checks that `docker/seed_catalogue.sql` matches what `gen-catalogue` produces from the document.
