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

### Experiments

```bash
uv run contract-extraction documents tag exp-set-1 DOC001 DOC002 ../test_data/nda/x.pdf   # codes or files (--remove)
uv run contract-extraction documents list --tag exp-set-1                                # labels and contract types

uv run contract-extraction experiment create rag-1 --tag p1-drafts --pipelines default,local-hybrid --repeats 3 \
    --hypothesis "Hybrid retrieval beats dense-only"
uv run contract-extraction experiment run rag-1      # queues the runs; workers execute them (dev.sh up --workers N)
uv run contract-extraction experiment show rag-1     # progress and a summary per pipeline
uv run contract-extraction experiment export rag-1   # CSVs in ../experiments/rag-1/ (git-ignored)
```

`create` fixes the design in `experiments.design`: the pipelines, repeats, run options and the documents (from `--tag`
and/or `--documents`) with the fields each one extracts. Every pipeline extracts the same fields of a document:
`--fields labelled` (default: the document's labelled fields), `types` (its labelled contract types' fields, down to
`--min-priority`), a comma-separated list, or `detect` (each pipeline detects the type itself, so fields may differ).
`--retrievals` and `--no-judge` apply to every run.

`run` queues a document's next run when its previous one has finished (one active run per document), keeps at most
`--max-queued` runs queued and rotates the pipelines per document and repeat. Ctrl-C cancels the queued runs; running ones
finish. Running it again resumes: a document and pipeline are done after `--repeats` succeeded runs, and failed runs are
retried `--retries` times per invocation.

`export` writes:

| File | One row per | Holds |
|---|---|---|
| `results.csv` | run × field | best value, label, status, exact match, partial score, verdict |
| `runs.csv` | run | state, repeat, seconds, LLM calls, tokens, cost, contract types, snapshot fingerprint, code version |
| `fields.csv` | pipeline × field | the quality columns below |
| `summary.csv` | pipeline | quality, ± SD of the score across repeats, judge agreement, calls / tokens / cost / seconds per run |
| `outcomes.csv` | run × RAG config × field | every outcome, not just the best value: the columns of `results.csv` |
| `retrievals.csv` | pipeline × RAG config | the quality columns and ± SD per RAG config: each config of a pipeline answered the same fields, so they compare pairwise |
| `experiment.json` | | name, hypothesis and the design |

### Retrieval-only evaluation

```bash
uv run contract-extraction experiment retrieval-eval rag-sweep --tag dev                       # the pipeline's RAG configs
uv run contract-extraction experiment retrieval-eval k-sweep --tag dev --retrievals RAG02,RAG07 \
    --top-k 3,5,10,20 --threshold 0,0.5                                                       # one variant per k × threshold
uv run contract-extraction experiment retrieval-eval rerank --tag dev --retrievals RAG07 --top-k 5 --per-query-top 20 \
    --rerank none,BAAI/bge-reranker-v2-m3-int8 --candidates 20,40                             # reranker on / off
```

`retrieval-eval` retrieves every labelled field that has an evidence quote under each RAG config (variant), exactly as
a run would, and scores the evidence recall, with no LLM calls (only query embeddings). The decomposition and index of
`--pipeline` (default: the default pipeline) are reused or built. It writes `retrieval_hits.csv` (document × field ×
config: hits, evidence rank, whether it is indexed, the evidence chunk's score), `retrieval_summary.csv` (per config:
recall, recall of all passages, recall@1/3/5/10/20, MRR, not indexed, mean hits) and `retrieval_by_type.csv` (the
same per config and value type) to `experiments/NAME/`.

**Reranking.** A RAG config with `rerank_model` (a fastembed cross-encoder name, e.g. `BAAI/bge-reranker-v2-m3-int8`)
scores its best `rerank_candidates` fused hits against the field's label and description and keeps the best `top_k`
(`extraction/retrieval.py`, `providers/rerank.py`; anchors are added after, as without it). The models run locally on
CPU (about 0.1 s per candidate on an M4), download once to `~/.cache/fastembed` and load once per process; the score
is stored in `retrieval_hits.rerank_score`. Candidates are capped by `per_query_top` × queries, so raise
`per_query_top` with it. A database created before the reranker needs
`ALTER TABLE retrieval_configs ADD COLUMN rerank_model text, ADD COLUMN rerank_candidates integer NOT NULL DEFAULT 30;`
and `ALTER TABLE retrieval_hits ADD COLUMN rerank_score double precision;`.

### Comparing arms

```bash
uv run contract-extraction experiment compare rag-1 --by pipeline --baseline default                     # score
uv run contract-extraction experiment compare rag-1 --by retrieval_config --baseline RAG02 --metric exact
uv run contract-extraction experiment compare rag-1 --by pipeline --baseline default --labels absent --metric invented
uv run contract-extraction experiment compare k-sweep --by retrieval_config --baseline "RAG02 k=5 t=0" \
    --where label_confidence=high                                                                     # evidence recall
```

`compare` (`compare.py`) reads an export folder (`outcomes.csv`, else `results.csv`, else `retrieval_hits.csv`) and
compares every arm with the baseline cell by cell (document × field, repeats averaged, cells both arms have). Fields of
one contract are correlated, so the 95% interval is a cluster bootstrap over documents and `p` a document-level
sign-flip permutation test, Holm-corrected over the arms (`p_holm`); for 0/1 metrics McNemar's test over cells is shown
too. Report an effect only when the interval excludes 0 and it holds with `--where label_confidence=high`.
`outcomes.csv` holds every RAG config's answer, so a multi-config pipeline's cell there is the average config; compare
whole pipelines (judge-selected best values) with `--file results.csv`.

### Semantic score

```bash
uv run contract-extraction experiment semantic e1-baseline --dry-run       # cells to grade and the estimated cost
uv run contract-extraction experiment semantic e1-baseline --sample 120    # grade, add `semantic`, write a hand-check sample
uv run contract-extraction experiment semantic e1-baseline --check ../experiments/e1-baseline/semantic_sample.csv
uv run contract-extraction experiment compare e1-baseline --file results.csv --baseline or-llama31-8b --metric semantic
```

The draft labels paraphrase ("material breach not remedied within 30 days") where extractions often quote the clause,
so exact, partial and even lenient scores count right answers as wrong. `semantic` (`semantic.py`) adds a `semantic`
column to `results.csv` and `outcomes.csv`: each labelled key of an object label (or the whole value) is settled
without an LLM when it can be (empty answer, lenient 1, booleans and numbers), and otherwise graded correct / partial
/ wrong (1 / 0.5 / 0) by a grader model (`--profile`, default `judge-or-gpt6-luna`, another family than the label
drafts). Grades are cached in `experiments/.semantic-cache.jsonl` by grader, prompt version, field, label and
answer, so re-running after `experiment export` (which rewrites the CSVs without the column) is free. Validate the
grader before using its numbers: fill `human_grade` in `semantic_sample.csv` and `--check` it (agreement, Cohen's
kappa, confusion).

**Evidence recall** (`evidence.py`): a draft label's evidence quote (kept in its notes) is split at "…" into
passages, and a passage counts as found in a chunk when 80% of its words appear there in order (Markdown, case and
small OCR noise ignored). `results.csv` and `outcomes.csv` get `evidence_any` (the model saw part of the evidence),
`evidence_all`, `evidence_rank` (first chunk holding it) and `evidence_indexed` (false: the evidence is in no chunk of
the index, so it was lost in decomposition or chunking, not retrieval). The summaries add `evidence_recall`,
`evidence_recall_all`, `evidence_mrr`, `evidence_not_indexed` and the mean score with and without the evidence.

Labels with a value and labels of `""` (not in this contract) are scored apart: `value_exact`, `value_score` and
`value_missed` (not found) over labels with a value; `absent_correct` and `invented` (a value where there is none) over
`""` labels. `judge_pass_correct` is the share of PASS verdicts on correct values. `value_lenient` (and the `lenient` column) scores like `value_score`
but compares numbers by value and text by token F1, ignoring case, punctuation and legal forms ("Acme Pty Ltd." = "ACME"),
so formatting differences are told apart from wrong answers. Only succeeded runs count. When a
pipeline was edited during an experiment, its runs have more than one snapshot fingerprint and `show` warns.
The executor records the code it runs (`git describe --always --dirty`) in each run's "Run started" event, so `show`
also warns when an experiment's runs come from more than one code version.

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
  experiments.py experiment design, runner (queueing, rotation, resume) and results / export
  storage.py     local file storage (staging + hashing, per-document folders, path guards)
  secrets.py     API key lookup by the env var named in the database
  health.py      liveness and readiness, shared by /health and `check`
  worker.py      claim loop (SKIP LOCKED), heartbeat, cancellation, stale-run cleanup
  catalogue.py   contract types and fields parsed from docs/contract_types_and_fields.md → docker/seed_catalogue.sql
  cli.py         contract-extraction check | ingest | run | worker | status | cancel | api | openapi | providers | gen-catalogue | labels | documents | experiment
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
