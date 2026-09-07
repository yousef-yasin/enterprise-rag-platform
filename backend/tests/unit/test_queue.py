"""arq dispatch — queue vs inline worker mode (docs/DEPLOYMENT.md "background jobs")."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.workers import queue


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_profile": "local",
        "llm_provider": "openai",
        "llm_api_key": "k",
        "embedding_provider": "fastembed",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


async def test_inline_mode_calls_task_function_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[dict[str, object], tuple[object, ...]]] = []

    async def fake_task(ctx: dict[str, object], *args: object) -> str:
        calls.append((ctx, args))
        return "done"

    from app.workers import tasks

    monkeypatch.setattr(tasks, "ingest_document", fake_task)

    result = await queue.enqueue(_settings(worker_mode="inline"), "ingest_document", "doc-1")

    assert result == "inline:done"
    assert calls == [({}, ("doc-1",))]


async def test_inline_mode_swallows_task_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_task(_ctx: dict[str, object], *_args: object) -> str:
        raise RuntimeError("boom")

    from app.workers import tasks

    monkeypatch.setattr(tasks, "ingest_document", failing_task)

    result = await queue.enqueue(_settings(worker_mode="inline"), "ingest_document", "doc-1")

    assert result == "inline:failed"


async def test_queue_mode_never_calls_the_task_function_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression guard: queue mode must go through get_queue()/arq, never call the
    # task function in-process — doing so would run the job twice once an arq
    # worker also drains it from Redis.
    from app.workers import tasks

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("queue mode must not call the task function directly")

    monkeypatch.setattr(tasks, "ingest_document", fail_if_called)

    class _FakeJob:
        job_id = "job-123"

    class _FakePool:
        async def enqueue_job(self, *_args: object, **_kwargs: object) -> _FakeJob:
            return _FakeJob()

    async def fake_get_queue(_settings: Settings) -> _FakePool:
        return _FakePool()

    monkeypatch.setattr(queue, "get_queue", fake_get_queue)

    result = await queue.enqueue(_settings(worker_mode="queue"), "ingest_document", "doc-1")

    assert result == "job-123"
