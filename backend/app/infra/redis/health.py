"""Redis reachability probe (docs/ARCHITECTURE.md §28.2)."""

from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from app.config import Settings
from app.core.health import DependencyState, DependencyStatus
from app.infra._probe import Stopwatch, describe_error

_NAME = "redis"


async def probe_redis(settings: Settings) -> DependencyStatus:
    watch = Stopwatch()
    client: Redis = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password.get_secret_value(),
        db=settings.redis_db,
        socket_timeout=settings.redis_timeout_s,
        socket_connect_timeout=settings.redis_timeout_s,
    )
    try:
        await asyncio.wait_for(client.ping(), timeout=settings.readiness_timeout_s)
    except Exception as exc:
        return DependencyStatus(_NAME, DependencyState.FAIL, watch.elapsed_ms, describe_error(exc))
    finally:
        await client.aclose()
    return DependencyStatus(_NAME, DependencyState.OK, watch.elapsed_ms)
