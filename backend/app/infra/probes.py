"""Additional readiness probes added in later phases (docs/ARCHITECTURE.md section 28.2)."""

from __future__ import annotations

from app.config import Settings
from app.core.health import DependencyState, DependencyStatus
from app.infra._probe import Stopwatch, describe_error


async def probe_embedding_provider(settings: Settings) -> DependencyStatus:
    watch = Stopwatch()
    try:
        from app.providers.registry import build_embedding_provider

        provider = build_embedding_provider(settings)
        _ = provider.profile.dimension
    except Exception as exc:
        return DependencyStatus(
            "embedding_provider", DependencyState.FAIL, watch.elapsed_ms, describe_error(exc)
        )
    return DependencyStatus("embedding_provider", DependencyState.OK, watch.elapsed_ms)


async def probe_queue(settings: Settings) -> DependencyStatus:
    watch = Stopwatch()
    try:
        from app.infra.redis.client import get_redis

        redis = get_redis(settings)
        await redis.ping()
    except Exception as exc:
        return DependencyStatus(
            "queue", DependencyState.FAIL, watch.elapsed_ms, describe_error(exc)
        )
    return DependencyStatus("queue", DependencyState.OK, watch.elapsed_ms)
