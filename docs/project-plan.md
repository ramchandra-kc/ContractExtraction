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
| 7b | **Config editing & ground truth** | Backend write endpoints and UI for editing pipeline configuration and labeling ground truth per document and field | API and UI tests pass; an edited config is used by the next run; labels show next to best values | ⬜ planned |
| 8 | **Dev experience** | `scripts/dev.sh` to start everything, checks for each service, end-to-end smoke test, docs refresh | One command brings up the full stack; the smoke test passes | ⬜ planned |
| 9 | **Authentication** | Auth in the gateway, frontend login, backend trusts the gateway | Unauthenticated requests are rejected at the gateway | ⬜ planned |

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
