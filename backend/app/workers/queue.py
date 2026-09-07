"""arq queue client for enqueueing jobs from the API (docs/ARCHITECTURE.md §22)."""

from __future__ import annotations

import structlog
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import Settings, WorkerMode
from app.core.errors import DependencyUnavailableError

_log = structlog.get_logger("app.workers.queue")

_pool: ArqRedis | None = None


def _redis_settings(settings: Settings) -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_dsn)


async def get_queue(settings: Settings) -> ArqRedis:
    global _pool
    if _pool is None:
        try:
            _pool = await create_pool(_redis_settings(settings))
        except Exception as exc:
            raise DependencyUnavailableError("job queue is unavailable") from exc
    return _pool


async def enqueue(settings: Settings, task: str, *args: object) -> str:
    """Dispatch ``task`` — enqueued to arq (default), or run inline when
    WORKER_MODE=inline (no standing worker; see docs/DEPLOYMENT.md). Inline mode
    calls the exact same task function used by the arq worker, synchronously, so
    the job runs exactly once and its outcome lands in the same durable Postgres
    status fields either way. Exceptions are swallowed here (logged) because
    arq callers never see task exceptions either — they're recorded via the
    task's own failure handling, not surfaced to whoever enqueued the job.
    """
    if settings.worker_mode is WorkerMode.INLINE:
        from app.workers import tasks as task_module

        fn = getattr(task_module, task)
        try:
            result = await fn({}, *args)
            return f"inline:{result}"
        except Exception:
            _log.exception("inline_worker.task_failed", task=task)
            return "inline:failed"

    pool = await get_queue(settings)
    job = await pool.enqueue_job(task, *args)
    return job.job_id if job is not None else ""


async def close_queue() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
    _pool = None
