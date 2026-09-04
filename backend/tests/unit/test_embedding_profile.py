"""Embedding profile identity (docs/ARCHITECTURE.md section 16.3)."""

from __future__ import annotations

from app.core.embedding_profile import (
    ChunkPolicy,
    compute_embedding_profile_id,
    qdrant_collection_name,
    resolved_chunk_sizing,
)
from app.providers.embeddings.fake import FAKE_PROFILE


def _policy(**kw: object) -> ChunkPolicy:
    base: dict[str, object] = {
        "target_fraction": 0.8,
        "overlap_fraction": 0.15,
        "target_tokens": 512,
        "structure_aware": True,
        "contextual_prefix_template": "{title}",
    }
    base.update(kw)
    return ChunkPolicy(**base)  # type: ignore[arg-type]


def test_profile_id_is_stable() -> None:
    a = compute_embedding_profile_id(FAKE_PROFILE, _policy())
    b = compute_embedding_profile_id(FAKE_PROFILE, _policy())
    assert a == b
    assert len(a) == 16


def test_profile_id_changes_with_chunk_policy() -> None:
    base = compute_embedding_profile_id(FAKE_PROFILE, _policy())
    changed = compute_embedding_profile_id(FAKE_PROFILE, _policy(overlap_fraction=0.3))
    assert base != changed


def test_collection_name_encodes_kb_and_profile() -> None:
    name = qdrant_collection_name("11111111-2222-3333-4444-555555555555", "abcd1234abcd1234")
    assert name == "kb_11111111222233334444555555555555__abcd1234abcd1234"


def test_chunk_sizing_respects_max_tokens() -> None:
    target, overlap = resolved_chunk_sizing(FAKE_PROFILE, _policy(), prefix_tokens=10)
    # bge-style 512 max, 0.8 fraction -> ~409 usable, minus prefix
    assert target <= int(FAKE_PROFILE.max_tokens * 0.8)
    assert 0 < overlap < target
