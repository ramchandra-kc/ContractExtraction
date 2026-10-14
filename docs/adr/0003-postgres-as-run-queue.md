# ADR 0003: Postgres as the run queue

- Status: accepted
- Date: 2026-10-14

## Context

Processing one contract takes minutes: decomposition, embedding, then many LLM calls (fields × search configs, each with a
judge call). This can't happen inside an HTTP request. We need background execution with progress, cancellation and recovery
when a worker dies.

## Decision

The `runs` table in Postgres **is** the queue:

- The API inserts a run with `state = 'queued'` and returns `202`.
- Workers claim the oldest queued run with `SELECT … FOR UPDATE SKIP LOCKED`, so a run goes to exactly one worker.
- The worker updates `stage`, `progress_done/total` and `heartbeat_at` as it goes. It checks `cancel_requested` between fields.
- Runs whose heartbeat goes stale are requeued or failed, depending on `attempts`.
- A partial unique index allows at most one queued or running run per document.

The API and the worker never call each other.

## Consequences

- No extra infrastructure such as Redis, RabbitMQ or Celery. The queue lives in the same transactions as the results.
- Polling adds a small delay (a poll interval of about 2 s), which is fine at research scale.
- To scale, start more worker processes.
- If throughput or fan-out needs grow, a dedicated broker can replace the queue behind the same repository interface.
