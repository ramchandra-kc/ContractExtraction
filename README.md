# ContractExtraction

A research project that extracts structured data points from contract PDFs, such as customer name, payment terms, project
dates, penalties and force majeure provisions. It combines PDF decomposition, retrieval-augmented generation with a local LLM,
and an LLM judge that grades every answer.

```
PDF ─► decompose ─► chunk + embed ─► vector index ─► retrieve ─► extract (LLM) ─► judge (LLM) ─► results
```

## Parts

The project is a monorepo with four separate parts. Each part has its own folder, config and run command.

| Folder | Part | Runs as | Port |
|---|---|---|---|
| [`frontend/`](frontend/) | React single-page app | local process (Vite) | 5173 |
| [`gateway/`](gateway/) | API gateway: the single entry point for the frontend | local process | 8080 |
| [`backend/`](backend/) | REST API and pipeline worker | local processes | 8000 (API) |
| [`database/`](database/) | Postgres, Qdrant and Ollama, plus schema migrations | Docker | 5432 / 6333 / 11434 |

## Documentation

- [Architecture](docs/architecture.md): components, boundaries, data flow and conventions
- [Project plan](docs/project-plan.md): roadmap and status of each phase
- [Architecture decision records](docs/adr/)

## Status

Phase 0 (architecture) is done. Each later phase gets its own plan, which is approved before implementation.
See the [project plan](docs/project-plan.md).
