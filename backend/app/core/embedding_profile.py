"""Embedding profile identity (docs/ARCHITECTURE.md §16.3).

``embedding_profile_id`` binds the embedding model *and* the chunk policy. It names
the KB's Qdrant collection and gates cross-profile reads/writes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.config import Settings
from app.core.interfaces.embeddings import EmbeddingProfile


@dataclass(frozen=True, slots=True)
class ChunkPolicy:
    target_fraction: float
    overlap_fraction: float
    target_tokens: int
    structure_aware: bool
    contextual_prefix_template: str

    @classmethod
    def from_settings(cls, settings: Settings) -> ChunkPolicy:
        return cls(
            target_fraction=settings.chunk_token_fraction,
            overlap_fraction=settings.chunk_overlap_fraction,
            target_tokens=settings.chunk_target_tokens,
            structure_aware=True,
            contextual_prefix_template=settings.contextual_prefix_template,
        )


def compute_embedding_profile_id(profile: EmbeddingProfile, policy: ChunkPolicy) -> str:
    payload = {
        "provider": profile.provider,
        "model_id": profile.model_id,
        "dimension": profile.dimension,
        "max_tokens": profile.max_tokens,
        "normalize": profile.normalize,
        "query_prefix": profile.query_prefix,
        "doc_prefix": profile.doc_prefix,
        "tokenizer_id": profile.tokenizer_id,
        "pooling": profile.pooling,
        "chunk_policy": {
            "target_fraction": policy.target_fraction,
            "overlap_fraction": policy.overlap_fraction,
            "target_tokens": policy.target_tokens,
            "structure_aware": policy.structure_aware,
        },
        "contextual_prefix_template": policy.contextual_prefix_template,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    # Not a security hash — a short, stable identity key for the embedding config.
    return hashlib.sha1(canonical.encode(), usedforsecurity=False).hexdigest()[:16]


def qdrant_collection_name(kb_id: str, embedding_profile_id: str) -> str:
    return f"kb_{kb_id.replace('-', '')}__{embedding_profile_id}"


def resolved_chunk_sizing(
    profile: EmbeddingProfile, policy: ChunkPolicy, prefix_tokens: int
) -> tuple[int, int]:
    """Return ``(chunk_target_tokens, chunk_overlap_tokens)`` (docs/ARCHITECTURE.md §11.1)."""

    usable = int(profile.max_tokens * policy.target_fraction)
    target = max(32, min(policy.target_tokens, usable - prefix_tokens))
    overlap = round(target * policy.overlap_fraction)
    return target, overlap
