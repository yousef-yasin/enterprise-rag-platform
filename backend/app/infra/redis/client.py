"""Shared async Redis client (docs/ARCHITECTURE.md §21)."""

from __future__ import annotations

from redis.asyncio import Redis

from app.config import Settings

_client: Redis | None = None


def get_redis(settings: Settings) -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(
            settings.redis_dsn,
            socket_timeout=settings.redis_timeout_s,
            socket_connect_timeout=settings.redis_timeout_s,
            decode_responses=True,
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None
