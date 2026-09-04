"""Qdrant reachability probe (docs/ARCHITECTURE.md §28.2).

Hits the unauthenticated ``/readyz`` endpoint over HTTP. No ``qdrant-client``
dependency in Phase 0 — that arrives with the vector-store adapter in Phase 3.
"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.core.health import DependencyState, DependencyStatus
from app.infra._probe import Stopwatch, describe_error

_NAME = "qdrant"


async def probe_qdrant(settings: Settings) -> DependencyStatus:
    watch = Stopwatch()
    url = f"{settings.qdrant_url.rstrip('/')}/readyz"
    try:
        async with httpx.AsyncClient(timeout=settings.qdrant_timeout_s) as client:
            response = await client.get(url)
        if response.status_code != httpx.codes.OK:
            return DependencyStatus(
                _NAME, DependencyState.FAIL, watch.elapsed_ms, f"HTTP {response.status_code}"
            )
    except Exception as exc:
        return DependencyStatus(_NAME, DependencyState.FAIL, watch.elapsed_ms, describe_error(exc))
    return DependencyStatus(_NAME, DependencyState.OK, watch.elapsed_ms)
