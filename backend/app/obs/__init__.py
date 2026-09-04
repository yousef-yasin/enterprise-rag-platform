"""Observability: Prometheus metrics (docs/ARCHITECTURE.md §28.4)."""

from app.obs.metrics import (
    ABSTENTION,
    DEGRADED,
    INGESTION_STAGE_SECONDS,
    INVALID_CITATIONS,
    LLM_COST_USD,
    LLM_TOKENS,
    RETRIEVAL_STAGE_SECONDS,
    WEAK_CITATIONS,
    record_ingestion_timings,
    record_retrieval_timings,
    render_latest,
)

__all__ = [
    "ABSTENTION",
    "DEGRADED",
    "INGESTION_STAGE_SECONDS",
    "INVALID_CITATIONS",
    "LLM_COST_USD",
    "LLM_TOKENS",
    "RETRIEVAL_STAGE_SECONDS",
    "WEAK_CITATIONS",
    "record_ingestion_timings",
    "record_retrieval_timings",
    "render_latest",
]
