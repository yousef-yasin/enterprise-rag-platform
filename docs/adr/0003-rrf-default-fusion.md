# ADR 0003 — RRF as the default hybrid-fusion strategy

- Status: accepted
- Date: 2026-09-03

## Context

Hybrid retrieval merges a dense (cosine) ranked list and a sparse (BM25-style) ranked
list. Their score scales are not comparable, so fusion needs either rank-based
combination or per-list score normalization.

## Decision

Default fusion is **Reciprocal Rank Fusion (RRF)**:
`score(d) = Σ_i weight_i · 1 / (RRF_K + rank_i(d))`, `RRF_K` default 60, list weights
default 1.0. The fusion strategy is **configurable** (`RETRIEVAL__FUSION_STRATEGY ∈
{rrf, weighted_norm, dbsf}`) and `RRF_K` / weights are tunable. The evaluation harness
(§33) is the mechanism for choosing per-deployment.

## Consequences

Positive:
- No cross-scale score normalization; robust to one channel having pathological score
  distributions.
- Almost no tuning surface; sane out of the box.
- Matches Qdrant's built-in server-side fusion, so the default path is one round trip.

Negative / costs / mitigations:
- RRF discards score magnitude — a runaway top-1 in both lists is treated like a
  marginal top-1. Mitigation: `dbsf` (distribution-based score fusion) and
  `weighted_norm` are available and measured in `docs/RESULTS.md`; deployments with
  a strong dense model and clean corpora may prefer them.
- `RRF_K = 60` over short lists (20–40) compresses contributions. `RRF_K` is exposed;
  RESULTS.md reports a small sweep.
- The app-side RRF implementation (used for the `weighted_norm`/`dbsf` paths and for
  the pgvector-fallback thought experiment) must stay behaviourally identical to
  Qdrant's for `rrf`; this is covered by a unit test with fixed rank lists.

## Alternatives considered

- **Weighted normalized scores** (`weighted_norm`): min-max or z-score per list, then
  weighted sum. Kept as an option. Rejected as *default* because normalization is
  sensitive to outliers and query-dependent score ranges.
- **DBSF**: kept as an option (Qdrant supports it). Slightly better when score
  distributions are well-behaved; more fragile otherwise.
- **Learned fusion / a small LTR model**: out of scope for v1 — needs training data
  and adds a model to maintain. Revisit if RESULTS.md shows fusion is the bottleneck.
