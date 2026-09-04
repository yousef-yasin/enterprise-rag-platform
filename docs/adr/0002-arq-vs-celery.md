# ADR 0002 — arq for background jobs (not Celery / RQ)

- Status: accepted
- Date: 2026-09-03

## Context

Document ingestion (parse → chunk → embed → index) is too slow for a request cycle
and must be retryable. We also need a small number of periodic jobs (reconciliation,
trace cleanup). The application is async (FastAPI + async SQLAlchemy + async provider
clients). Redis is already in the stack.

## Decision

Use **arq** as the task queue and scheduler. Run one `worker` process by default,
sharing the API image with a different entrypoint.

## Consequences

Positive:
- Async-native: tasks `await` the same provider/DB clients the API uses; no
  sync/async bridge.
- Tiny surface: one dependency, Redis-only, ~an afternoon to understand end to end.
- Built-in cron for the reconciliation / cleanup jobs — no extra scheduler.
- Job state is inspectable in Redis; easy to test with a real Redis in CI.

Negative / costs / mitigations:
- arq is lower-activity than Celery and has a smaller ecosystem. Accepted because the
  feature set we use (enqueue, retry with backoff, cron, concurrency limit) is small,
  stable, and easy to replace behind our `JobQueue` wrapper if needed.
- Redis-as-broker durability must be configured deliberately: `appendonly yes`,
  `maxmemory-policy noeviction` (ARCHITECTURE.md §21), plus a **stuck-job sweeper**
  (§22) because no broker fully removes the need to detect jobs that died between
  states.
- No distributed result backend beyond Redis; we treat Postgres (`ingestion_jobs`,
  `documents.status`) as the source of truth for job outcome, with Redis as an
  accelerator.

## Alternatives considered

- **Celery**: industry standard, mature, huge feature set (routing, chords, multiple
  brokers). Rejected for v1 as more machinery than a single-worker ingestion pipeline
  needs; its sync-first model fights the async codebase; onboarding cost is higher.
  A `JobQueue` interface keeps the door open.
- **RQ**: simple, but sync-only and Redis-only with weaker scheduling; the async
  mismatch is the dealbreaker.
- **Dramatiq**: also reasonable (more active than arq, good retry story). Close call;
  arq wins on async-nativeness and built-in cron for our exact needs.
- **FastAPI `BackgroundTasks` / a thread pool**: not durable, not retryable, dies
  with the process. Unsuitable for ingestion.
