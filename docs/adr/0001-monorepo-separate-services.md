# ADR 0001: Monorepo with separate services

- Status: accepted
- Date: 2026-10-14

## Context

The prototype grew as one Python package (pipeline, API, worker, CLI, migrations) with a frontend and Docker setup added
around it. The boundaries between parts weren't explicit. We want a clear architecture where the **frontend, API gateway,
backend and database are separate**, while one researcher can still work on the project easily.

## Decision

One git repository with one top-level folder per part: `frontend/`, `gateway/`, `backend/`, `docker/`. Each part:

- has its own dependencies, config folder, tests and run command
- talks to the others only through a documented interface (HTTP for frontend → gateway → backend, and SQL for the database, whose schema is `docker/schema.sql`)
- doesn't import code from another part

The project is a rewrite from scratch. The prototype (`DocumentExtraction`) is kept read-only as a reference.

## Consequences

- One clone, one history, and changes that span parts land in one commit.
- Each part could be split into its own repo later, because nothing imports across folders.
- Shared conventions (env layering, ports, error shape) must be documented, since no code enforces them. See [architecture.md](../architecture.md).
