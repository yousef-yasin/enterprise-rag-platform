"""End-to-end readiness against the ephemeral stack (docs/ARCHITECTURE.md §28.2).

Exercises the real probe functions against real Postgres / Qdrant / Redis started by
``compose.test.yml``. ``make test-integration`` points the connection settings at
``127.0.0.1`` and sets ``RAG_INTEGRATION=1``.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.services.health import HealthService, build_default_probes

pytestmark = pytest.mark.integration


async def test_all_dependencies_report_ready() -> None:
    settings = get_settings()
    report = await HealthService(build_default_probes(settings)).wait_until_ready(
        timeout_s=30, interval_s=1.0
    )
    failed = [d for d in report.dependencies if d.state.value != "ok"]
    assert report.ready, f"not ready: {[(d.name, d.detail) for d in failed]}"
