"""``rag eval`` and ``rag traces`` subcommands (docs/ARCHITECTURE.md §33.4).

Registered lazily by :func:`app.cli.main._register_eval_commands` so the base CLI
keeps working even if the module is trimmed.

    rag eval run <dataset> --kb <uuid> [--split test] [--label ...] [--no-judge] [--limit N]
    rag eval compare <run_id_a> <run_id_b>
    rag eval calibrate-reranker --kb <uuid> --dataset <name> [--split dev]
    rag traces export [--since ISO] [--kb <uuid>] [--limit N] [--out file.jsonl]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from app.config import Settings, get_settings

_THRESHOLDS_PATH = Path(__file__).resolve().parents[1] / "config" / "reranker_thresholds.json"


def register(evalp: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    run = evalp.add_parser("run", help="run a dataset through the pipeline")
    run.add_argument("dataset")
    run.add_argument("--kb", required=True, help="knowledge base UUID (already ingested)")
    run.add_argument("--split", default="test")
    run.add_argument("--label", default=None)
    run.add_argument("--no-judge", action="store_true")
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--no-persist", action="store_true")
    run.set_defaults(func=_cmd_run)

    compare = evalp.add_parser("compare", help="compare two runs with bootstrap diff CIs")
    compare.add_argument("run_a")
    compare.add_argument("run_b")
    compare.set_defaults(func=_cmd_compare)

    calib = evalp.add_parser("calibrate-reranker", help="pick an abstention threshold")
    calib.add_argument("--kb", required=True)
    calib.add_argument("--dataset", required=True)
    calib.add_argument("--split", default="dev")
    calib.add_argument("--target-precision", type=float, default=0.9)
    calib.set_defaults(func=_cmd_calibrate)


def register_traces(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    traces = sub.add_parser("traces").add_subparsers(dest="traces_command", required=True)
    export = traces.add_parser("export", help="export retrieval traces as JSONL")
    export.add_argument("--since", default=None, help="ISO timestamp lower bound")
    export.add_argument("--limit", type=int, default=1000)
    export.add_argument("--out", default=None, help="output file (default: stdout)")
    export.set_defaults(func=_cmd_traces_export)


def _settings() -> Settings:
    return get_settings()


# ── eval run ────────────────────────────────────────────────────────────────
def _cmd_run(args: argparse.Namespace) -> int:
    from app.services.evaluation import EvaluationService

    settings = _settings()
    run_id = asyncio.run(
        EvaluationService(settings).run(
            knowledge_base_id=uuid.UUID(args.kb),
            dataset=args.dataset,
            split=args.split,
            config_label=args.label,
            judge_enabled=not args.no_judge,
            limit=args.limit,
            persist=not args.no_persist,
        )
    )
    print(f"eval run {run_id}")
    if not args.no_persist:
        asyncio.run(_print_run(settings, run_id))
    return 0


async def _print_run(settings: Settings, run_id: uuid.UUID) -> None:
    from app.infra.db.models import EvalRun
    from app.infra.db.session import session_scope

    async with session_scope(settings) as session:
        run = await session.get(EvalRun, run_id)
        if run is None:
            return
        print(json.dumps(run.metrics, indent=2, default=str))


# ── eval compare ────────────────────────────────────────────────────────────
def _cmd_compare(args: argparse.Namespace) -> int:
    settings = _settings()
    asyncio.run(_compare(settings, uuid.UUID(args.run_a), uuid.UUID(args.run_b)))
    return 0


async def _compare(settings: Settings, a: uuid.UUID, b: uuid.UUID) -> None:
    from sqlalchemy import select

    from app.core.eval.bootstrap import diff_ci
    from app.infra.db.models import EvalRun, EvalSample
    from app.infra.db.session import session_scope

    async with session_scope(settings) as session:
        run_a = await session.get(EvalRun, a)
        run_b = await session.get(EvalRun, b)
        if run_a is None or run_b is None:
            raise SystemExit("one or both runs not found")
        samples_a = list(
            (await session.execute(select(EvalSample).where(EvalSample.run_id == a))).scalars()
        )
        samples_b = list(
            (await session.execute(select(EvalSample).where(EvalSample.run_id == b))).scalars()
        )

    keys = sorted(
        {k for s in samples_a for k in s.scores} & {k for s in samples_b for k in s.scores}
    )
    print(f"{run_a.name}  vs  {run_b.name}   (n={len(samples_a)} / {len(samples_b)})")
    print(f"{'metric':<24} {'A':>10} {'B':>10} {'Δ (95% CI)':>28}")
    n = settings.eval_bootstrap_n
    for key in keys:
        va = [s.scores[key] for s in samples_a if key in s.scores]
        vb = [s.scores[key] for s in samples_b if key in s.scores]
        d = diff_ci(va, vb, n_resamples=n)
        sig = "" if (d.ci_low <= 0 <= d.ci_high) else "  *"
        print(
            f"{key:<24} {_m(va):>10} {_m(vb):>10} "
            f"{d.value:+.3f} [{d.ci_low:+.3f}, {d.ci_high:+.3f}]{sig}"
        )


def _m(values: list[float]) -> str:
    clean = [v for v in values if v == v]
    return f"{sum(clean) / len(clean):.3f}" if clean else "n/a"


# ── calibrate reranker ──────────────────────────────────────────────────────
def _cmd_calibrate(args: argparse.Namespace) -> int:
    settings = _settings()
    asyncio.run(
        _calibrate(
            settings,
            kb=uuid.UUID(args.kb),
            dataset=args.dataset,
            split=args.split,
            target_precision=args.target_precision,
        )
    )
    return 0


async def _calibrate(
    settings: Settings,
    *,
    kb: uuid.UUID,
    dataset: str,
    split: str,
    target_precision: float,
) -> None:
    """Sweep the reranker top-score threshold on a labelled dev split and write the
    value that hits the target abstention precision to config/reranker_thresholds.json."""
    from app.core.enums import RetrievalMode
    from app.infra.db.models import KnowledgeBase
    from app.infra.db.session import session_scope
    from app.providers.registry import build_reranker
    from app.services.evaluation import load_dataset
    from app.services.retrieval import RetrievalService

    reranker = build_reranker(settings)
    if reranker is None:
        raise SystemExit("RERANKER=none — nothing to calibrate")

    root = Path(settings.eval_dataset_root) if settings.eval_dataset_root else None
    cases = load_dataset(dataset, split, root=root)
    service = RetrievalService(settings)
    async with session_scope(settings) as session:
        kb_row = await session.get(KnowledgeBase, kb)
        if kb_row is None:
            raise SystemExit("knowledge base not found")
        profile = kb_row.active_embedding_profile_id

    observations: list[tuple[float, bool]] = []  # (top reranker score, should_answer)
    for case in cases:
        result = await service.retrieve(
            knowledge_base_id=kb,
            kb_active_profile=profile,
            search_query=case.question,
            mode=RetrievalMode.HYBRID,
        )
        top = result.candidates[0].score if result.candidates else float("-inf")
        observations.append((top, not case.should_abstain))

    thresholds = sorted({round(s, 3) for s, _ in observations if s != float("-inf")})
    best: tuple[float, float, float] | None = None  # (threshold, precision, recall)
    for thr in thresholds:
        tp = sum(1 for s, ok in observations if s >= thr and ok)
        fp = sum(1 for s, ok in observations if s >= thr and not ok)
        fn = sum(1 for s, ok in observations if s < thr and ok)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        if precision >= target_precision and (best is None or recall > best[2]):
            best = (thr, precision, recall)

    if best is None:
        print("no threshold reached the target precision; leaving thresholds unchanged")
        return

    thr, precision, recall = best
    path = _THRESHOLDS_PATH
    entry = {
        "min_score": thr,
        "calibrated_precision": round(precision, 3),
        "calibrated_recall": round(recall, 3),
        "dataset": f"{dataset}/{split}",
        "n": len(observations),
    }
    await asyncio.to_thread(_write_threshold, path, reranker.model_id, entry)
    print(f"wrote {path}")
    print(
        f"  {reranker.model_id}: min_score={thr} (precision={precision:.3f}, recall={recall:.3f})"
    )


def _write_threshold(path: Path, model_id: str, entry: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    data[model_id] = entry
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ── traces export ───────────────────────────────────────────────────────────
def _cmd_traces_export(args: argparse.Namespace) -> int:
    settings = _settings()
    asyncio.run(_traces_export(settings, since=args.since, limit=args.limit, out=args.out))
    return 0


async def _traces_export(
    settings: Settings, *, since: str | None, limit: int, out: str | None
) -> None:
    from datetime import datetime

    from sqlalchemy import select

    from app.infra.db.models import RetrievalTrace
    from app.infra.db.session import session_scope

    stmt = select(RetrievalTrace).order_by(RetrievalTrace.created_at.desc()).limit(limit)
    if since:
        stmt = stmt.where(RetrievalTrace.created_at >= datetime.fromisoformat(since))

    async with session_scope(settings) as session:
        rows = list((await session.execute(stmt)).scalars())

    lines = [
        json.dumps(
            {
                "trace_id": str(r.id),
                "message_id": str(r.message_id),
                "created_at": r.created_at.isoformat(),
                "raw_query": r.raw_query,
                "search_query": r.search_query,
                "was_rewritten": r.was_rewritten,
                "embedding_profile_id": r.embedding_profile_id,
                "fusion_strategy": r.fusion_strategy,
                "params": r.params,
                "dense_hits": r.dense_hits,
                "sparse_hits": r.sparse_hits,
                "fused": r.fused,
                "reranked": r.reranked,
                "context_chunk_ids": r.context_chunk_ids,
                "cited_chunk_ids": r.cited_chunk_ids,
                "abstained": r.abstained,
                "low_confidence": r.low_confidence,
                "degraded": r.degraded,
                "latency_ms": r.latency_ms,
                "token_usage": r.token_usage,
                "estimated_cost_usd": float(r.estimated_cost_usd),
            },
            default=str,
        )
        for r in rows
    ]
    payload = "".join(f"{line}\n" for line in lines)
    if out:
        await asyncio.to_thread(Path(out).write_text, payload, "utf-8")
        print(f"exported {len(lines)} traces to {out}")
    else:
        sys.stdout.write(payload)
