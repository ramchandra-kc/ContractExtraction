# backend

Python package with two entry points: the **REST API** and the **pipeline worker**. Built in **Phases 2–5**.
See [architecture §4–§8](../docs/architecture.md).

**API** (port **8000**, bound to 127.0.0.1): documents, runs, results, pages and system endpoints under `/api/v1`. It only
records work and reads results. It is reached only through the [gateway](../gateway/).

**Worker** (no HTTP): claims queued runs from Postgres and runs the pipeline (decompose → index → retrieve → extract → judge).

**Talks to:** Postgres, file storage, and, from the worker only, Qdrant and Ollama.

**Must not:** let the API and the worker call each other. They share state only through Postgres ([ADR 0003](../docs/adr/0003-postgres-as-run-queue.md)).
