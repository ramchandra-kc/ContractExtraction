# frontend

React single-page app (Vite, TypeScript). See [project plan](../docs/project-plan.md) (Phase 7).

**Owns:** the UI for uploading PDFs, listing documents, following run progress, viewing results (best values, all outcomes,
evidence, judge verdicts) and browsing decomposed pages.

**Talks to:** the [gateway](../gateway/) only, through relative `/api/...` URLs. In development, Vite proxies `/api` to the gateway
(`VITE_GATEWAY_URL`, default `http://127.0.0.1:8080`).

**Must not:** know the backend's address, hold business rules, or receive secrets (only `VITE_*` variables reach the browser).

Port: **5173**.

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 (needs the gateway, API and a worker running)
npm test             # Vitest + Testing Library; the API is mocked with MSW
npm run typecheck    # tsc -b
npm run lint         # ESLint
npm run build        # production build in dist/
npm run gen:api      # after an API change: openapi.json + src/api/schema.d.ts
```

## Screens

| Route | Shows |
|---|---|
| `/` | Upload (drop or pick a PDF; the same file again opens the existing document) and the document list with each latest run |
| `/documents/:id` | Document details, its runs and decompositions, **New run** (pipeline, kind, fields, RAG configs, judge, reuse, redecompose) |
| `/runs/:id` | State, stage and progress, cancel, and tabs: best values, all outcomes (fields × RAG configs), timeline. `?result=<id>` opens a result's evidence, judgements and LLM calls |
| `/documents/:id/pages` | Decomposed page text (what the LLM saw) next to the original PDF at the same page. `?page=N&decomposition=<id>` |

## How it works

- **API types** come from the contract. `npm run gen:api` runs `contract-extraction openapi` in the backend, which needs no database.
  It writes `openapi.json`, and `openapi-typescript` generates `src/api/schema.d.ts`. Both files are committed.
  The backend test `test_openapi_matches_frontend.py` fails when `openapi.json` is stale.
- **Calls** go through `openapi-fetch` (`src/api/client.ts`). Any non-2xx answer, or a network failure, becomes a `ProblemError`:
  RFC 9457 fields plus the `X-Request-ID`. `ProblemAlert` shows it.
- **Progress is polled** (`src/api/hooks.ts`, TanStack Query):
  - An active run is polled every `VITE_POLL_MS` (2000 ms), together with its partial results.
  - Events are fetched incrementally with `?after=<last id>`.
  - Polling stops when the run finishes, and its events, results and document are fetched once more.
  - The document list polls only while a listed run is active. Health (`/api/v1/health/ready`) is checked every 30 s.
- **No business rules:** the best value per field comes from the API (`best`). The "New run" button is disabled while a run is
  active, but the API's 409 stays the authority.
- **Page viewer:** Markdown pages are rendered with `react-markdown`, and raw HTML in them is not interpreted. The PDF is
  the browser's own viewer in an iframe (`/api/v1/documents/{id}/file#page=N`).

## Configuration

`.env` (committed defaults) → `.env.local` (gitignored overrides). Only `VITE_*` variables are read:

| Variable | Default | Used by |
|---|---|---|
| `VITE_GATEWAY_URL` | `http://127.0.0.1:8080` | the dev-server proxy only (`vite.config.ts`), never the app |
| `VITE_POLL_MS` | `2000` | run polling interval |

## Layout

```
src/
  api/          client.ts (openapi-fetch, ProblemError), hooks.ts (queries, mutations, polling), schema.d.ts (generated)
  components/   Layout, badges, ProblemAlert, JsonValue, HealthIndicator, Pager; ui/ holds shadcn/ui components
  features/     UploadDropzone, NewRunDialog, ResultsTable, OutcomesMatrix, FieldResultSheet, EventsTimeline
  pages/        DocumentsPage, DocumentPage, RunPage, PagesPage
  lib/          config, formatting, query client, cn()
  test/         MSW server, typed fixtures, render helper
```

UI components come from [shadcn/ui](https://ui.shadcn.com) (Tailwind v4, Radix). Add more with `npx shadcn@latest add <name>`.
