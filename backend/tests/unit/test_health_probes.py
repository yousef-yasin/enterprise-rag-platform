"""Dependency probes degrade gracefully when infrastructure is absent (Phase 0 gate).

These run without any live services: each probe must return a ``FAIL`` status
rather than raising, so ``/health/ready`` can always answer.
"""

from __future__ import annotations

from app.config import Settings
from app.core.health import DependencyState
from app.infra.db.health import probe_postgres
from app.infra.qdrant.health import probe_qdrant
from app.infra.redis.health import probe_redis
from app.services.health import HealthService, build_default_probes


def _unreachable_settings() -> Settings:
    return Settings(
        app_profile="ci",
        llm_provider="fake",
        embedding_provider="fake",
        postgres_host="127.0.0.1",
        postgres_port=1,
        qdrant_url="http://127.0.0.1:1",
        redis_host="127.0.0.1",
        redis_port=1,
        postgres_connect_timeout_s=0.2,
        qdrant_timeout_s=0.2,
        redis_timeout_s=0.2,
        readiness_timeout_s=1.0,
    )


async def test_postgres_probe_fails_cleanly() -> None:
    status = await probe_postgres(_unreachable_settings())
    assert status.name == "postgres"
    assert status.state is DependencyState.FAIL
    assert status.detail


async def test_qdrant_probe_fails_cleanly() -> None:
    status = await probe_qdrant(_unreachable_settings())
    assert status.state is DependencyState.FAIL


async def test_redis_probe_fails_cleanly() -> None:
    status = await probe_redis(_unreachable_settings())
    assert status.state is DependencyState.FAIL


async def test_readiness_report_is_not_ready_without_infra() -> None:
    settings = _unreachable_settings()
    report = await HealthService(build_default_probes(settings)).readiness()
    assert report.ready is False
    assert {"postgres", "qdrant", "redis"} <= {d.name for d in report.dependencies}
