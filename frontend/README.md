# frontend

React single-page app (Vite, TypeScript). Built in **Phase 7**. See [project plan](../docs/project-plan.md).

**Owns:** the UI for uploading PDFs, listing documents, following run progress, viewing results (best values, all outcomes,
evidence, judge verdicts) and browsing decomposed pages.

**Talks to:** the [gateway](../gateway/) only, through relative `/api/...` URLs. In development, Vite proxies `/api` to `http://127.0.0.1:8080`.

**Must not:** know the backend's address, hold business rules, or receive secrets (only `VITE_*` variables reach the browser).

Port: **5173**.
