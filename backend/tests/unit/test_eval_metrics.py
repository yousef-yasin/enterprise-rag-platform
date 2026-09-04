"""Evaluation metric math + bootstrap CIs (docs/ARCHITECTURE.md §33.2)."""

from __future__ import annotations

import math

from app.core.eval.bootstrap import bootstrap_mean_ci, diff_ci
from app.core.eval.judge import family_separation_warning, model_family
from app.core.eval.metrics import (
    abstention_outcome,
    citation_score,
    ndcg_at_k,
    precision_at_k,
    precision_recall_f1,
    recall_at_k,
    reciprocal_rank,
    token_f1,
)


# ── retrieval ───────────────────────────────────────────────────────────────
def test_recall_and_precision_at_k() -> None:
    retrieved = ["a", "b", "c", "d"]
    relevant = ["b", "d", "z"]
    assert recall_at_k(retrieved, relevant, 4) == 2 / 3
    assert recall_at_k(retrieved, relevant, 1) == 0.0
    assert precision_at_k(retrieved, relevant, 4) == 0.5
    assert precision_at_k(retrieved, relevant, 2) == 0.5


def test_recall_is_nan_without_gold() -> None:
    assert math.isnan(recall_at_k(["a"], [], 5))


def test_reciprocal_rank_and_ndcg() -> None:
    assert reciprocal_rank(["x", "y", "gold"], ["gold"]) == 1 / 3
    assert reciprocal_rank(["gold"], ["gold"]) == 1.0
    assert reciprocal_rank(["a"], ["gold"]) == 0.0
    # perfect ranking -> nDCG 1.0
    assert ndcg_at_k(["g1", "g2"], ["g1", "g2"], 2) == 1.0
    # reversed vs ideal still < 1
    assert ndcg_at_k(["x", "g1"], ["g1"], 2) < 1.0


def test_dedupe_preserves_first_rank() -> None:
    assert reciprocal_rank(["a", "a", "gold"], ["gold"]) == 0.5


# ── citations ───────────────────────────────────────────────────────────────
def test_citation_in_context_hard_gate() -> None:
    ok = citation_score(cited_chunk_ids=["c1"], context_chunk_ids=["c1", "c2"])
    assert ok.cited_in_context == 1.0
    bad = citation_score(cited_chunk_ids=["c9"], context_chunk_ids=["c1", "c2"])
    assert bad.cited_in_context == 0.0


def test_citation_precision_recall_against_support() -> None:
    s = citation_score(
        cited_chunk_ids=["c1", "c2"],
        context_chunk_ids=["c1", "c2", "c3"],
        supporting_chunk_ids=["c1", "c3"],
    )
    assert s.precision == 0.5  # c1 of {c1,c2}
    assert s.recall == 0.5  # c1 of {c1,c3}


# ── abstention ──────────────────────────────────────────────────────────────
def test_abstention_confusion_and_prf() -> None:
    outcomes = [
        abstention_outcome(should_abstain=True, did_abstain=True),  # tp
        abstention_outcome(should_abstain=True, did_abstain=False),  # fn
        abstention_outcome(should_abstain=False, did_abstain=True),  # fp
        abstention_outcome(should_abstain=False, did_abstain=False),  # tn
    ]
    tp = sum(o.tp for o in outcomes)
    fp = sum(o.fp for o in outcomes)
    fn = sum(o.fn for o in outcomes)
    assert (tp, fp, fn) == (1, 1, 1)
    p, r, f1 = precision_recall_f1(tp, fp, fn)
    assert p == 0.5 and r == 0.5 and f1 == 0.5


# ── answer text ─────────────────────────────────────────────────────────────
def test_token_f1() -> None:
    assert token_f1("25 days of paid leave", "25 days paid leave") == 1.0
    assert token_f1("completely different", "25 days paid leave") == 0.0
    assert 0.0 < token_f1("25 days annual leave", "25 paid leave per year") < 1.0


# ── bootstrap ───────────────────────────────────────────────────────────────
def test_bootstrap_ci_contains_mean_and_narrows_with_n() -> None:
    values = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0]
    agg = bootstrap_mean_ci(values, n_resamples=2000, seed=1)
    assert agg.n == 10
    assert agg.ci_low <= agg.value <= agg.ci_high
    assert agg.ci_low >= 0.0 and agg.ci_high <= 1.0


def test_bootstrap_drops_nan() -> None:
    agg = bootstrap_mean_ci([1.0, math.nan, 1.0, math.nan], n_resamples=500)
    assert agg.n == 2
    assert agg.value == 1.0


def test_bootstrap_empty_is_nan() -> None:
    agg = bootstrap_mean_ci([], n_resamples=100)
    assert agg.n == 0
    assert math.isnan(agg.value)


def test_diff_ci_sign() -> None:
    better = [1.0] * 20
    worse = [0.0] * 20
    d = diff_ci(better, worse, n_resamples=500)
    assert d.value == 1.0
    assert d.ci_low > 0.0  # significantly different from zero


def test_bootstrap_deterministic_under_seed() -> None:
    v = [0.3, 0.7, 0.1, 0.9, 0.5]
    a = bootstrap_mean_ci(v, n_resamples=777, seed=42)
    b = bootstrap_mean_ci(v, n_resamples=777, seed=42)
    assert a.as_dict() == b.as_dict()


# ── judge family separation ─────────────────────────────────────────────────
def test_model_family_and_warning() -> None:
    assert model_family("gpt-4o-mini") == "openai"
    assert model_family("claude-sonnet-5") == "anthropic"
    assert model_family("some-unknown-model") == "unknown"
    assert family_separation_warning("gpt-4o-mini", "gpt-4o") is not None
    assert family_separation_warning("gpt-4o-mini", "claude-sonnet-5") is None
    assert family_separation_warning("mystery-a", "mystery-b") is None
