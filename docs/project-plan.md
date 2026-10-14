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
| 1 | **Database** | `database/docker-compose.yml` (Postgres, Qdrant, Ollama), env examples, init scripts (test DB), `scripts/infra-up.sh`, Alembic setup, first migration with the schema in architecture §7 | `infra-up.sh` brings everything up healthy; migration applies and rolls back cleanly | ⬜ planned |
| 2 | **Backend core** | uv project, layered settings, logging, domain models, SQLAlchemy models matching the migration, repositories, file storage | Unit and repository tests pass against the test DB | ⬜ planned |
| 3 | **Backend pipeline** | Provider interfaces (LLM, embedder, vector store) with Ollama, Qdrant and in-memory versions; decomposition; chunking and indexing; retrieval; extraction; judge; field templates and search configs as config; CLI to run one PDF end to end | Offline end-to-end test with fakes passes; `sample.pdf` runs end to end against real Ollama and Qdrant | ⬜ planned |
| 4 | **Backend worker** | Claim loop (`SKIP LOCKED`), heartbeats, cancellation, stale-run recovery, retry limit, per-run log file, settings snapshot | Concurrency and recovery tests pass; two workers never take the same run | ⬜ planned |
| 5 | **Backend API** | FastAPI app, routes from architecture §8, error mapping, upload limit, OpenAPI | API integration tests pass; OpenAPI published | ⬜ planned |
| 6 | **Gateway** | uv project, streaming proxy, request IDs, access log, timeouts, upload limit, CORS, aggregated health | Gateway tests with a fake upstream pass; frontend-style requests reach the backend through :8080 | ⬜ planned |
| 7 | **Frontend** | Vite + React + TS app, types generated from OpenAPI, upload, document list, run progress, results (best values, all outcomes, evidence, verdicts), page viewer | Vitest and `tsc` pass; a PDF uploaded in the UI reaches `succeeded` and results show up | ⬜ planned |
| 8 | **Dev experience** | `scripts/dev.sh` to start everything, checks for each service, end-to-end smoke test, docs refresh | One command brings up the full stack; the smoke test passes | ⬜ planned |
| 9 | **Authentication** | Auth in the gateway, frontend login, backend trusts the gateway | Unauthenticated requests are rejected at the gateway | ⬜ planned |

## Open questions (decided in the phase that needs them)

- Phase 1: which init steps belong in the Postgres container and which in migrations.
- Phase 3: which decomposition methods to support at first (pymupdf only, or OCR and hybrid too), and whether image captioning is in scope.
- Phase 3: is the external experiment-tracking API still needed?
- Phase 5: results export formats (JSON, CSV).
- Phase 7: polling or server-sent events for run progress.

## Change log

- 2026-10-14: Phase 0 completed. Architecture, plan and ADRs 0001–0004 written.
