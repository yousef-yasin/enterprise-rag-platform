"""Job-status Redis Streams (docs/ARCHITECTURE.md §21.3).

The stream is an *accelerator* for live SSE updates. Postgres (``documents.status`` /
``ingestion_jobs``) is authoritative — the SSE endpoint reads it on connect and
polls it as a fallback.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from redis.asyncio import Redis

from app.infra.redis import namespaces

_MAXLEN = 200


def _key(document_id: str) -> str:
    return f"{namespaces.JOBSTREAM}{document_id}"


async def publish(redis: Redis, document_id: str, event: dict[str, object]) -> None:
    await redis.xadd(
        _key(document_id),
        {"data": json.dumps(event)},
        maxlen=_MAXLEN,
        approximate=True,
    )


async def follow(
    redis: Redis, document_id: str, *, last_id: str = "$", block_ms: int = 5000
) -> AsyncIterator[tuple[str, dict[str, object]]]:
    key = _key(document_id)
    cursor = last_id
    while True:
        entries = await redis.xread({key: cursor}, count=10, block=block_ms)
        if not entries:
            yield "", {}  # heartbeat tick so the caller can re-check Postgres
            continue
        for _stream, records in entries:
            for record_id, fields in records:
                cursor = record_id
                payload = json.loads(fields["data"])
                yield record_id, payload


async def reap(redis: Redis, older_than_days: int) -> int:
    """Trim job streams older than the retention window (hourly cron)."""

    removed = 0
    async for key in redis.scan_iter(match=f"{namespaces.JOBSTREAM}*", count=200):
        await redis.expire(key, older_than_days * 86400)
        removed += 1
    return removed
