"""PostgreSQL reachability probe (docs/ARCHITECTURE.md §28.2).

Opens a short-lived connection and runs ``SELECT 1``. No pooling or ORM — those
belong to Phase 1.
"""

from __future__ import annotations

import asyncio

import asyncpg

from app.config import Settings
from app.core.health import DependencyState, DependencyStatus
from app.infra._probe import Stopwatch, describe_error

_NAME = "postgres"


async def probe_postgres(settings: Settings) -> DependencyStatus:
    watch = Stopwatch()
    try:
        conn: asyncpg.Connection[asyncpg.Record] = await asyncio.wait_for(
            asyncpg.connect(
                host=settings.postgres_host,
                port=settings.postgres_port,
                user=settings.postgres_user,
                password=settings.postgres_password.get_secret_value(),
                database=settings.postgres_db,
                timeout=settings.postgres_connect_timeout_s,
            ),
            timeout=settings.readiness_timeout_s,
        )
        try:
            await conn.execute("SELECT 1")
        finally:
            await conn.close()
    except Exception as exc:
        return DependencyStatus(_NAME, DependencyState.FAIL, watch.elapsed_ms, describe_error(exc))
    return DependencyStatus(_NAME, DependencyState.OK, watch.elapsed_ms)
