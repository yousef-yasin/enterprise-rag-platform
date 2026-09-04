"""Redis key namespaces (docs/ARCHITECTURE.md §21.2).

Every key MUST start with one of these prefixes. Caches carry TTLs and are the only
keys safe to bulk-delete — via ``SCAN`` over :data:`CACHE`, never ``FLUSHDB`` (which
would also destroy the arq queue and the job streams).
"""

from __future__ import annotations

from typing import Final

# durable — never evicted, never bulk-deleted
ARQ: Final = "arq:"
JOBSTREAM: Final = "jobstream:"
RATELIMIT: Final = "rl:"
LOCK: Final = "lock:"
IDEMPOTENCY: Final = "idem:"

# caches — TTL'd, safe to SCAN + UNLINK under the CACHE prefix
CACHE: Final = "cache:"
CACHE_EMBED_QUERY: Final = "cache:emb:q:"
CACHE_EMBED_DOC: Final = "cache:emb:d:"
CACHE_RETRIEVAL: Final = "cache:ret:"
CACHE_LLM: Final = "cache:llm:"

APPROVED_PREFIXES: Final = (ARQ, JOBSTREAM, RATELIMIT, LOCK, IDEMPOTENCY, CACHE)


def validate_key(key: str) -> None:
    """Raise ``ValueError`` if ``key`` is not in an approved namespace."""

    if not key.startswith(APPROVED_PREFIXES):
        raise ValueError(f"Redis key {key!r} is not in an approved namespace {APPROVED_PREFIXES}")


def is_cache_key(key: str) -> bool:
    return key.startswith(CACHE)
