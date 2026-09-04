"""Idempotent Qdrant collection provisioning (docs/ARCHITECTURE.md §20).

Run from ``rag bootstrap`` and lazily by the ingestion pipeline. A Postgres advisory
lock serialises concurrent creates so ``api`` and ``worker`` never race.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.qdrant.store import QdrantVectorStore

_LOCK_KEY = 918273645  # arbitrary, stable


async def ensure_collection(
    session: AsyncSession, store: QdrantVectorStore, *, name: str, dense_dim: int
) -> None:
    await session.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _LOCK_KEY})
    try:
        await store.ensure_collection(name, dense_dim=dense_dim)
    finally:
        await session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
