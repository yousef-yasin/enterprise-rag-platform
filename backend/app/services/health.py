"""Readiness orchestration (docs/ARCHITECTURE.md §28.2).

Runs the injected dependency probes concurrently and aggregates them. The set of
probes grows per phase (embedding-model-loaded in Phase 3, queue heartbeat in
Phase 2); the service itself does not change.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence

from app.config import Settings
from app.core.health import DependencyProbe, ReadinessReport
from app.infra.db.health import probe_postgres
from app.infra.qdrant.health import probe_qdrant
from app.infra.redis.health import probe_redis


class HealthService:
    def __init__(self, probes: Sequence[DependencyProbe]) -> None:
        self._probes = tuple(probes)

    async def readiness(self) -> ReadinessReport:
        statuses = await asyncio.gather(*(probe() for probe in self._probes))
        return ReadinessReport.from_statuses(list(statuses))

    async def wait_until_ready(
        self, *, timeout_s: float, interval_s: float = 2.0
    ) -> ReadinessReport:
        deadline = time.monotonic() + timeout_s
        report = await self.readiness()
        while not report.ready and time.monotonic() < deadline:
            await asyncio.sleep(interval_s)
            report = await self.readiness()
        return report


def build_default_probes(settings: Settings) -> list[DependencyProbe]:
    """The readiness dependency set (docs/ARCHITECTURE.md section 28.2)."""

    from app.infra.probes import probe_embedding_provider, probe_queue

    return [
        lambda: probe_postgres(settings),
        lambda: probe_qdrant(settings),
        lambda: probe_redis(settings),
        lambda: probe_queue(settings),
        lambda: probe_embedding_provider(settings),
    ]
