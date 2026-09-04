"""Worker wiring (docs/ARCHITECTURE.md section 22)."""

from __future__ import annotations

from app.workers.worker import WorkerSettings


def test_worker_settings_shape() -> None:
    names = {getattr(fn, "__name__", str(fn)) for fn in WorkerSettings.functions}
    assert "ingest_document" in names
    assert "reprocess_document" in names
    assert len(WorkerSettings.cron_jobs) >= 1
    assert WorkerSettings.health_check_interval > 0
    assert WorkerSettings.redis_settings.host


async def test_startup_hook_does_not_raise() -> None:
    from app.workers import worker

    await worker.on_startup({})
