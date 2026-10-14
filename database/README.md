# database

Infrastructure and schema. Built in **Phase 1**. See [ADR 0004](../docs/adr/0004-local-processes-docker-infra.md).

**Owns:**
- `docker-compose.yml` for **Postgres** (5432), **Qdrant** (6333) and **Ollama** (11434)
- env examples (`*.env.example`). Real `*.env` files are never committed
- init scripts (e.g. creating the test database)
- schema **migrations** (Alembic), the single source of truth for the relational schema
- seed and backup scripts

**Must not:** contain application code.
