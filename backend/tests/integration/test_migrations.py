"""Alembic upgrade / downgrade / upgrade on a populated database (Phase 1 gate)."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration._helpers import PG_HOST as _PG_HOST
from tests.integration._helpers import TEST_DSN as _TEST_DSN

pytestmark = pytest.mark.integration

_ENV = {
    **os.environ,
    "APP_PROFILE": "ci",
    "LLM_PROVIDER": "fake",
    "EMBEDDING_PROVIDER": "fake",
    "POSTGRES_HOST": _PG_HOST,
}


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        env=_ENV,
        check=False,
    )


async def _drop_schema() -> None:
    engine = create_async_engine(_TEST_DSN)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


async def _seed_row() -> None:
    engine = create_async_engine(_TEST_DSN)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name, is_active,"
                " is_admin, created_at, updated_at)"
                " VALUES (:id, 'm@x.io', 'x', 'M', true, true, now(), now())"
            ),
            {"id": uuid.uuid4()},
        )
    await engine.dispose()


async def _table_count() -> int:
    engine = create_async_engine(_TEST_DSN)
    async with engine.connect() as conn:
        result = await conn.execute(
            text("select count(*) from information_schema.tables where table_schema = 'public'")
        )
        count = int(result.scalar_one())
    await engine.dispose()
    return count


async def test_upgrade_downgrade_upgrade_on_populated_db() -> None:
    await _drop_schema()

    assert _alembic("upgrade", "head").returncode == 0
    await _seed_row()
    populated = await _table_count()
    assert populated > 10

    assert _alembic("downgrade", "base").returncode == 0
    assert await _table_count() == 1  # only alembic_version remains

    assert _alembic("upgrade", "head").returncode == 0
    assert await _table_count() == populated

    check = _alembic("check")
    assert check.returncode == 0, check.stdout + check.stderr

    # restore schema for the rest of the session
    await _drop_schema()
    assert _alembic("upgrade", "head").returncode == 0
