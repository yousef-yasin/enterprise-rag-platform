"""Prometheus metric definitions and helpers (docs/ARCHITECTURE.md §28.4).

Uses ``prometheus_client`` directly (no extra instrumentator dependency). All
metrics share the ``rag_`` prefix. ``/metrics`` is served by
:mod:`app.api.metrics`; the HTTP request metrics are recorded by
:class:`app.api.metrics.MetricsMiddleware`.
"""

from __future__ import annotations

from collections.abc import Mapping

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

_STAGE_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
_HTTP_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

HTTP_REQUESTS = Counter(
    "rag_http_requests_total",
    "HTTP requests by method, path template and status class.",
    ["method", "path", "status"],
)
HTTP_DURATION = Histogram(
    "rag_http_request_duration_seconds",
    "HTTP request latency.",
    ["method", "path"],
    buckets=_HTTP_BUCKETS,
)

INGESTION_STAGE_SECONDS = Histogram(
    "rag_ingestion_stage_seconds",
    "Per-stage ingestion latency.",
    ["stage"],
    buckets=_STAGE_BUCKETS,
)
RETRIEVAL_STAGE_SECONDS = Histogram(
    "rag_retrieval_stage_seconds",
    "Per-stage retrieval latency.",
    ["stage"],
    buckets=_STAGE_BUCKETS,
)

DEGRADED = Counter("rag_degraded_total", "Pipeline degradations by component.", ["component"])
ABSTENTION = Counter("rag_abstention_total", "Chat abstentions by reason.", ["reason"])
LLM_TOKENS = Counter("rag_llm_tokens_total", "LLM tokens consumed.", ["kind"])
LLM_COST_USD = Counter("rag_llm_cost_usd_total", "Estimated LLM spend in USD.")
INVALID_CITATIONS = Counter(
    "rag_invalid_citation_total", "Out-of-range citation markers stripped from answers."
)
WEAK_CITATIONS = Counter(
    "rag_weak_citation_total", "Citations flagged weak by the groundedness heuristic."
)
INGESTION_FAILURES = Counter(
    "rag_ingestion_failures_total", "Terminal ingestion failures by reason.", ["reason"]
)


def record_retrieval_timings(timings: Mapping[str, float]) -> None:
    for stage, ms in timings.items():
        RETRIEVAL_STAGE_SECONDS.labels(stage=stage).observe(max(ms, 0.0) / 1000.0)


def record_ingestion_timings(timings: Mapping[str, float]) -> None:
    for stage, ms in timings.items():
        INGESTION_STAGE_SECONDS.labels(stage=stage).observe(max(ms, 0.0) / 1000.0)


def render_latest() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
