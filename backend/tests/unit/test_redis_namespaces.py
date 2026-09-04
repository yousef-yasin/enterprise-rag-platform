"""Redis key-namespace conventions (docs/ARCHITECTURE.md §21.2)."""

from __future__ import annotations

import pytest

from app.infra.redis import namespaces


@pytest.mark.parametrize(
    "key",
    [
        "arq:queue",
        "jobstream:doc-1",
        "cache:emb:q:abc",
        "cache:ret:xyz",
        "rl:user:1:60",
        "lock:doc:1",
        "idem:user:key",
    ],
)
def test_approved_keys_pass(key: str) -> None:
    namespaces.validate_key(key)


@pytest.mark.parametrize("key", ["random:x", "documents", "flushme", "session:1"])
def test_unapproved_keys_are_rejected(key: str) -> None:
    with pytest.raises(ValueError, match="approved namespace"):
        namespaces.validate_key(key)


def test_cache_keys_are_recognised() -> None:
    assert namespaces.is_cache_key("cache:llm:hash")
    assert not namespaces.is_cache_key("arq:queue")
