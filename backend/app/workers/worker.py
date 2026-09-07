"""arq worker entrypoint (docs/ARCHITECTURE.md §22).

Run:    arq app.workers.worker.WorkerSettings
Health: arq --check app.workers.worker.WorkerSettings
"""

from __future__ import annotations

from typing import Any, ClassVar

import structlog
from arq import cron
from arq.connections import RedisSettings

from app.config import get_settings
from app.core.logging import configure_logging
from app.workers import tasks

_log = structlog.get_logger("app.workers")


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_dsn)


async def on_startup(_ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(level=settings.app_log_level, json_output=settings.app_log_json)
    _log.info("worker.started", profile=settings.app_profile.value)


async def on_shutdown(_ctx: dict[str, Any]) -> None:
    from app.infra.db.session import dispose_engine
    from app.infra.redis.client import close_redis
    from app.workers.queue import close_queue

    await dispose_engine()
    await close_redis()
    await close_queue()
    _log.info("worker.stopped")


def _reconcile_minutes() -> set[int]:
    interval = max(1, get_settings().reconcile_interval_s // 60)
    return set(range(0, 60, min(30, interval)))


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        tasks.ingest_document,
        tasks.reprocess_document,
        tasks.delete_stale_points,
        tasks.purge_document,
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(tasks.reconcile_cron, minute=_reconcile_minutes(), run_at_startup=False),  # type: ignore[arg-type]
        cron(tasks.trace_gc_cron, hour={3}, minute={17}, run_at_startup=False),  # type: ignore[arg-type]
        cron(tasks.jobstream_reaper_cron, minute={7}, run_at_startup=False),  # type: ignore[arg-type]
    ]
    redis_settings = _redis_settings()
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_jobs = get_settings().worker_max_jobs
    job_timeout = get_settings().parse_timeout_s + 600
    health_check_interval = 15
    handle_signals = True
