"""Integration test infrastructure.

Skipped unless ``RAG_INTEGRATION=1`` (set by ``make test-integration``, which also
starts ``compose.test.yml``). Provides a real Postgres session and an API client
wired to it, with per-test isolation via TRUNCATE.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.infra.db.base import Base
from tests.integration._helpers import PG_HOST as _PG_HOST
from tests.integration._helpers import TEST_DSN as _TEST_DSN

INTEGRATION_ENABLED = os.environ.get("RAG_INTEGRATION") == "1"

pytestmark = pytest.mark.skipif(
    not INTEGRATION_ENABLED, reason="integration tests disabled — run `make test-integration`"
)


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    if not INTEGRATION_ENABLED:
        yield
        return

    async def _reset() -> None:
        engine = create_async_engine(_TEST_DSN)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()
        # drop any leftover Qdrant collections from a previous run
        try:
            from qdrant_client import AsyncQdrantClient

            host = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
            client = AsyncQdrantClient(url=host, api_key="qdrant_local_dev")
            for coll in (await client.get_collections()).collections:
                if coll.name.startswith("kb_"):
                    await client.delete_collection(coll.name)
            await client.close()
        except Exception:
            pass

    asyncio.run(_reset())
    yield


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(_TEST_DSN)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        async with factory() as session:
            yield session
        async with factory() as cleanup:
            tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
            await cleanup.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
            await cleanup.commit()
    finally:
        await engine.dispose()


def _uploads_dir() -> str:
    import tempfile
    from pathlib import Path

    path = Path(tempfile.gettempdir()) / "rag-test-uploads"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


@pytest.fixture(autouse=True)
async def _app_singletons(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Point the app's own engine / redis / queue / qdrant at the local test stack,
    and tear them down after each test."""
    monkeypatch.setenv("APP_PROFILE", "ci")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("POSTGRES_HOST", _PG_HOST)
    monkeypatch.setenv("QDRANT_URL", os.environ.get("QDRANT_URL", "http://127.0.0.1:6333"))
    monkeypatch.setenv("REDIS_HOST", os.environ.get("REDIS_HOST", "127.0.0.1"))
    monkeypatch.setenv("STORAGE_LOCAL_PATH", _uploads_dir())
    # rate limiting is opt-in per test (test_hardening.py re-enables it) so a busy
    # test session's shared client IP does not trip a spurious 429.
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    yield
    from app.infra.db.session import dispose_engine
    from app.infra.redis.client import close_redis
    from app.workers.queue import close_queue

    await dispose_engine()
    await close_redis()
    await close_queue()
    get_settings.cache_clear()


@pytest.fixture
def app_for_tests(db_session: AsyncSession) -> Iterator[object]:
    get_settings.cache_clear()

    from app.api.deps import get_session
    from app.main import create_app

    app = create_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_session] = _override
    yield app
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
async def client(app_for_tests: object) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app_for_tests)  # type: ignore[arg-type]
    # dotted host so the cookie jar behaves normally (single-label hosts get a
    # surprising ".local" suffix from http.cookiejar)
    async with AsyncClient(transport=transport, base_url="http://api.test") as ac:
        yield ac
