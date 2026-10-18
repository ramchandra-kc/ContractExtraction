# Project plan

Every phase follows the same loop:

1. **Plan**: write a short plan for the phase (scope, files, decisions, how to verify). The plan is reviewed and approved.
2. **Implement**: only what the approved plan covers.
3. **Verify**: run the phase's checks. Update this file and [architecture.md](architecture.md) if anything changed.

One phase is one commit or PR. A phase isn't started before the previous one is verified.

## Roadmap

| # | Phase | Scope | Done when | Status |
|---|---|---|---|---|
| 0 | **Architecture** | Repo, README, architecture, project plan, ADRs, placeholder folders | Docs reviewed | ✅ done |
| 1 | **Docker services & database schema** | `docker/docker-compose.yml` (Postgres, Qdrant, optional Ollama); `docker/Dockerfile`; `schema.sql` (26 tables, 2 views: model and RAG config, documents, runs, results, LLM calls, judgements, evaluation); `seed.sql` (default providers, models, prompts, RAG01–07, 12 contract fields, default pipeline) | Services healthy; schema and seed apply on an empty volume; constraint checks pass | ✅ done |
| 2 | **Backend core** | uv project, layered settings, logging, domain models, SQLAlchemy models matching `schema.sql`, repositories (including reading config from the DB), file storage | Unit and repository tests pass against a test database | ✅ done |
| 3a | **Ingestion** | Provider interfaces with Ollama, OpenAI-compatible (OpenRouter), Qdrant and in-memory versions; decomposition through pdf-converter (pymupdf, OCR, hybrid); header/footer removal; chunking with exact offsets; indexing with chunk rows as the record; `ingest` CLI | Unit, DB and OCR tests pass; `sample.pdf` ingests against real Ollama and Qdrant, and a second run reuses everything | ✅ done |
| 3b | **Extraction** | Retrieval (query expansion, thresholds, merge), extraction LLM, judge (optionally parallel), LLM-call logging, field results and evidence, run orchestration with events and progress, `run` CLI | Offline end-to-end test with fakes passes; `sample.pdf` runs end to end against real services | ✅ done |
| 4 | **Backend worker** | Claim loop (`SKIP LOCKED`), heartbeats, cancellation, stale-run cleanup (no automatic retries), `worker` / `status` / `cancel` / `run --queue` CLI | Concurrency and recovery tests pass; two workers never take the same run; a killed worker's run ends as failed | ✅ done |
| 5 | **Backend API** | FastAPI over the existing repositories: health (liveness/readiness), config (read-only), documents (upload, file, pages, images), runs (queue, cancel, events, results, evidence); RFC 9457 errors; request ids; stable operationIds | API tests pass; upload → run → results works over HTTP with a worker | ✅ done |
| 6 | **Gateway** | Starlette + httpx streaming proxy for `/api/v1/*`: request ids, edge-set forwarding headers, upload limit (413), 502/504 problems, CORS, aggregated health, nosniff | Gateway tests pass; upload → run → results works through :8080; 413 never reaches the API; API down → 503/502 | ✅ done |
| 7 | **Frontend** | Vite + React + TS app, types generated from OpenAPI, upload, document list, run progress, results (best values, all outcomes, evidence, verdicts), page viewer | Vitest and `tsc` pass; a PDF uploaded in the UI reaches `succeeded` and results show up | ✅ done |
| 7b | **Ground truth & evaluation** | Ground-truth API and UI (document page, and labeling from a run); expected value, match and counts in run results; `v_best_values` ranks by the run's snapshot; `exact_match` false for error outcomes | API, view and UI tests pass; labels made in the UI show as ✓ / ✗ next to a run's best values | ✅ done |
| 7c | **Config editing** | Write endpoints and UI for pipelines (compose, RAG order, judge, default), RAG configs, model profiles, fields and expansion queries, prompts (saving creates a new version; pipelines stay pinned), provider URL / enable and models. Decomposition and index configs are create-only (ingestion reuses their outputs by id). Names and keys can't change; deleting a row runs reference → 409 | API and UI tests pass; an edited config is used by the next run and past runs are unchanged | ✅ done |
| 8 | **Dev experience** | `scripts/dev.sh` (`up`, `status`, `smoke`, `test`, `down`, `reset`): Docker services, dependencies, check, then API, workers, gateway and frontend in one terminal with prefixed logs, fail-fast and graceful Ctrl-C; end-to-end smoke test through the gateway; docs refresh | One command brings up the full stack; the smoke test passes | ✅ done |
| 9 | **Authentication** | Auth in the gateway, frontend login, backend trusts the gateway | Unauthenticated requests are rejected at the gateway | ⬜ planned |
| 10a | **Formats 1: registry** | Converter registry and format detection; PDF converter behind it (no behaviour change); `documents.format`, `decompositions.converter`; `GET /config/formats`; frontend format awareness (accept list, viewer by format, format badge) | Existing tests pass; `sample.pdf` gives the same pages; the UI accepts only `.pdf` | ✅ done |
| 10b | **Formats 2: text and HTML** | txt and html converters, page markers (EDGAR `<PAGE>`, `\f`, CSS page breaks) or pages by length, EDGAR wrapper removal | Unit tests pass; every `test_data` `.txt`/`.htm` decomposes; one of each runs end to end in the UI | ✅ done (end to end through the gateway; not clicked through in a browser) |
| 10c | **Formats 3: images and DOCX** | images (pymupdf → PDF → OCR), docx (mammoth → html converter) | Unit and `ocr` tests pass; every `test_data` `.docx` decomposes | ⬜ planned |
| 10d | **Formats 4: email** | eml body plus supported attachments as one document, `source_part` per page | Unit tests pass; an eml with a PDF attachment runs end to end with its parts shown | ⬜ planned |

## Open questions (decided in the phase that needs them)

- Phase 3: which decomposition methods to support at first (pymupdf only, or OCR and hybrid too), and whether image captioning is in scope.
- Phase 3: is the external experiment-tracking API still needed?
- Phase 5: results export formats (JSON, CSV).
- Phase 7: polling or server-sent events for run progress. Decided: polling (SSE can come later through the gateway).

## Change log

- 2026-10-14: Phase 0 completed. Architecture, plan and ADRs 0001–0004 written.
- 2026-10-14: Phase 1 completed. The `database/` folder was replaced by `docker/` (one compose file; Qdrant and Ollama
  are no longer described as part of the database). Plain SQL schema without migrations. Pipeline configuration
  (providers, models, prompts, RAG configs, fields) moved into the database. LLM providers are pluggable (Ollama or OpenRouter).
- 2026-10-14: Phase 2 completed. Backend core: layered settings, the ORM mirroring `schema.sql` (guarded by a drift test),
  ConfigRepo / DocumentRepo / RunRepo, file storage, and the `contract-extraction check` command. Tests recreate
  `contract_extraction_test` from `docker/*.sql` and roll back each test.
- 2026-10-14: Phase 3 split into 3a (ingestion) and 3b (extraction). Phase 3a completed. The seed gained `ocr` and `hybrid`
  decomposition configs. `decompositions.created_at` now uses `clock_timestamp()`. Image captioning is deferred.
- 2026-10-14: Phase 3b completed. Retrieval, extraction and judge; runs execute from their snapshot; answers are reused when
  the evidence repeats; the parallel judge is optional (off by default); `run` CLI. Ollama in Docker now runs with
  `OLLAMA_NUM_PARALLEL=1` (otherwise llama3.1:8b needs ~11 GiB). Deferred: `results` / experiment CLI (comes with the API).
- 2026-10-14: Ollama is switchable (native :11434 or Docker :11435, via `providers set`). The judge temperature was lowered to 0.1.
- 2026-10-14: Phase 4 completed, kept simple on purpose. Polling worker with SKIP LOCKED claims, a heartbeat thread in the executor,
  and stale runs marked failed (no retries, so no resume logic). Cancel and a graceful worker stop, plus status/cancel/queue CLI.
- 2026-10-14: Phase 5 completed. One resource per call (upload, then queue a run), problem details, health split into liveness and readiness.
  Deferred to the frontend phase: config editing and ground-truth labeling over HTTP.
- 2026-10-14: Phase 6 completed. Review fixes: edge-set forwarding headers, validated request ids, closed streams, raw path forwarding,
  full timeouts, Starlette instead of FastAPI.
- 2026-10-14: Phase 7 completed. React 19 + Vite + TypeScript, Tailwind v4 + shadcn/ui, TanStack Query, React Router.
  - Types are generated from `frontend/openapi.json`. It's written by the new `contract-extraction openapi` command, which needs no database, and a backend test guards it against drift.
  - Run progress is polled.
  - The page viewer shows decomposed text next to the browser's PDF viewer, with no pdf.js.
  - Evidence links to its page but isn't highlighted, because chunks can span pages.
  - TypeScript is pinned to 5.9, since typescript-eslint and openapi-typescript don't support 6+ yet.
  - Config editing and ground-truth labeling need backend write endpoints, so they moved to Phase 7b.
- 2026-10-14: Phase 7b split: ground truth & evaluation (7b, completed) and config editing (7c, planned).
  - Fixed `v_best_values`, which ranked RAG configs by the pipeline's current RAG configs; it now uses the run's snapshot.
  - Fixed `v_run_evaluation`: an `error` outcome never matches. Before, an empty label would have matched a failed call.
  - Labels are any JSON value except null, because extracted values aren't typed by `value_type`; `""` means "not in this contract".
  - Run results gained `field_id`, `value_type`, `expected_value` and `exact_match` per best value, and `evaluation` counts.
  - The dev database got the two views with `CREATE OR REPLACE VIEW` instead of being recreated, to keep its data. That is safe
    because their columns are unchanged; recreating the database (`down -v`) gives the same result.
- 2026-10-14: Phase 7c completed. Config editing through `/config/*` and the UI's Configuration page; the rules are in
  [architecture §7.1](architecture.md).
  - Fixed a Phase 5 bug: the request's session committed **after** the response was sent, so a failed commit still reached
    the client as a success (verified: 201 for a write that was rolled back). The session dependency now uses FastAPI's
    `scope="function"`, and a regression test fails without it.
  - Database constraint errors are mapped to problem responses by SQLSTATE (409 / 422) instead of ending as 500.
  - Creates answer 201 with the row and no `Location`, because rows are read back through `GET /config/catalog`
    (there is no per-row GET).
  - Not verified in a browser against the real stack: the dev database was reset during the phase and the browser check
    was skipped. API, invariant (real executor, scripted models) and UI tests cover the behaviour.
- 2026-10-14: Phase 8 completed. `scripts/dev.sh` and `backend/tests/test_smoke.py` (marker `smoke`, `CE_SMOKE=1`); the rest is in the
  [README](../README.md) and [architecture §11](architecture.md).
  - The first draft was revised before implementation. Ctrl-C reaches every process in the terminal's group, and the
    script's own SIGTERM (doubled again by `uv run` / `npm run` forwarding) would have been the worker's second signal,
    which means "exit now". The script now runs the installed entry points in their own process groups and sends one SIGTERM.
    It is written for macOS's bash 3.2.
  - `status` reuses `contract-extraction check` instead of probing Postgres, Qdrant and Ollama again in bash.
  - `reset` also empties the storage folder, because document codes restart at DOC001 with a new database and the old
    folders would be left as orphans. It keeps Docker Ollama's volume (the pulled models).
  - The smoke PDF is generated once and cached in `.dev/smoke.pdf`, because pymupdf writes a new trailer id on every save and the same
    bytes are needed for "already stored" (200).
  - Dropped: hot reload for the API and gateway (needs an app factory import string, and the reload subprocess would lose
    the logging setup), and a 413 check in the smoke test (covered by the gateway's tests).
  - Verified: `up` against the real stack with native Ollama; `status`; `smoke` twice (17 s, then 6 s; customer_name =
    "Acme Pty Ltd", PASS); Ctrl-C during a run (a single signal, the run ended `cancelled`, no processes left); a killed
    gateway stops the stack with exit 1; a busy port fails before anything starts; an unreachable model warns and still starts;
    `test` (backend 163, gateway 18, frontend 38, typecheck and lint). Shellcheck is clean.
  - Not verified: `reset --yes` (the destructive path was not run during the phase; declining the prompt changes nothing) and
    a browser walkthrough of the UI.
- 2026-10-14: `scripts/dev.sh` made portable to Linux and Git Bash on Windows (WSL2 counts as Linux):
  - Ports are probed with curl instead of `lsof`, which only names the owner when it's installed.
  - `status` counts workers from `.dev/pids` when there is no `pgrep`.
  - The Windows virtualenv layout (`.venv/Scripts/*.exe`) is detected.
  - Vite runs as `node node_modules/vite/bin/vite.js`.
  - On Windows, processes are stopped with `taskkill /T /F`, because Windows programs get no SIGTERM, so a run in progress
    ends failed (stale heartbeat) instead of cancelled.
  - Verified on macOS end to end again. On Debian (bash 5, no `lsof` or `pgrep`) only the script's own logic was checked.
    Git Bash on Windows is not tested.
- 2026-10-18: Phase 10 (multi-format ingestion) planned as 10a–10d.
  - Text formats are parsed natively rather than rendered to PDF, which avoids a layout round trip and LibreOffice.
  - Images go through PDF and OCR.
  - An email is one document: its body, then its supported attachments.
  - Out of scope: `.msg`, `.rtf`, `.odt`, `.doc` (one converter each, later), and fetching remote resources from HTML or email.
- 2026-10-18: Phase 10a completed.
  - `decomposition/converters/` replaces `decomposition/converter.py`. `REGISTRY` is the single list of formats.
  - `detect` replaces the upload route's `%PDF-` check and is also used by the CLI, which now takes `<file>` instead of `<pdf>`.
  - `ingest(source_path=…)` replaces `pdf_path`.
  - Schema:
    - `documents.format` (CHECK lists every planned format, so 10b–10d need no schema change)
    - `decompositions.converter`
  - API:
    - `DecompositionOut.method` now shows the converter (`pdf:pymupdf`).
    - Upload errors say "Unsupported file type; accepted: …" or "The file is empty".
    - `GET /documents/{id}/file` sends HTML and email originals as an attachment with `Content-Security-Policy: sandbox`.
    - `PageOut.source_part` is new (set from 10d).
  - Existing dev databases need `scripts/dev.sh reset` (or the two `ALTER TABLE … ADD COLUMN`s), because the schema has no migrations.
- 2026-10-19: Phase 10b completed. `converters/text.py` (txt plus shared helpers: decoding, EDGAR unwrap, markers, pages by length)
  and `converters/html.py`.
  - lxml was added. It's a C extension, which the plan didn't foresee. Python's `html.parser` nests EDGAR's unclosed `<P>`s
    (800+ in one filing) until recursion fails, and lxml closes them the way browsers do. It's also about 2× faster on 2–3 MB filings.
  - Added, unplanned, after looking at real output:
    - Layout tables (at most one filled cell per row) become paragraphs.
    - Empty table rows are dropped.
    - Web-page `nav` / `aside` and page-level `header` / `footer` are removed.
  - Page ranges (`start_page` / `end_page`) now apply to every format (`select_pages`).
  - Verified with a batch run (converters only, no database) over `test_data/`:
    - 220 `.htm` and 45 `.txt` all convert, with no empty pages.
    - 245 split at page markers and 20 by length.
    - The slowest file takes 1.8 s.
  - Numbered-clause tables (`(e) | Construction. …`) are flattened too. Markdown table lines across the 220 HTML files
    drop from 134k to 49k; real two-column tables stay tables.
  - Verified end to end after `scripts/dev.sh reset`:
    - The PDF smoke test passes.
    - Through the gateway, an EDGAR `.htm` (10 pages, converter `html`) and `.txt` (6 pages, `txt`) upload and run.
    - The txt NDA's `parties` came out right with RAG07. RAG01 (dense, top 3) found no preamble chunk.
    - The HTML letter NDA got `not_found` from llama3.1:8b even with the preamble retrieved: one party is "you".
      That is a model limit, not the converter.
    - The HTML original is served as a sandboxed attachment.
    - `/config/formats` and the documents list work through the Vite proxy.
    - Not verified: clicking through the UI in a browser (the browser extension wasn't connected).
