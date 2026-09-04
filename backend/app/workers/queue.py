"""arq queue client for enqueueing jobs from the API (docs/ARCHITECTURE.md §22)."""

from __future__ import annotations

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import Settings
from app.core.errors import DependencyUnavailableError

_pool: ArqRedis | None = None


def _redis_settings(settings: Settings) -> RedisSettings:
    return RedisSettings(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password.get_secret_value(),
        database=settings.redis_db,
    )


async def get_queue(settings: Settings) -> ArqRedis:
    global _pool
    if _pool is None:
        try:
            _pool = await create_pool(_redis_settings(settings))
        except Exception as exc:
            raise DependencyUnavailableError("job queue is unavailable") from exc
    return _pool


async def enqueue(settings: Settings, task: str, *args: object) -> str:
    pool = await get_queue(settings)
    job = await pool.enqueue_job(task, *args)
    return job.job_id if job is not None else ""


async def close_queue() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
    _pool = None
