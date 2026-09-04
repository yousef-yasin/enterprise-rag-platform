"""Offline evaluation orchestration (docs/ARCHITECTURE.md §33).

Runs a JSONL dataset through the *real* retrieval + generation pipeline
(``ChatService``), scores every sample with judge-independent metrics plus an
optional LLM judge, aggregates with bootstrap 95% CIs, and persists an
``eval_runs`` row with its ``eval_samples``.
"""

from __future__ import annotations

import json
import math
import subprocess
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from app.config import Settings
from app.core.eval import metrics as evalm
from app.core.eval.bootstrap import bootstrap_mean_ci
from app.core.eval.judge import family_separation_warning, judge_answer
from app.core.security import hash_password
from app.infra.db.models import EvalRun, EvalSample, KnowledgeBase, RetrievalTrace
from app.infra.db.repositories.users import UserRepository
from app.infra.db.session import session_scope
from app.providers.registry import build_eval_judge
from app.services.chat import ChatService

_log = structlog.get_logger("app.eval")

EVAL_USER_EMAIL = "eval@localhost"


def _default_dataset_root() -> Path:
    """eval/ is a repo-root directory (sibling of backend/). Fall back to a
    backend-local copy when running from a packaged image."""
    repo_root = Path(__file__).resolve().parents[3] / "eval" / "datasets"
    if repo_root.exists():
        return repo_root
    return Path(__file__).resolve().parents[2] / "eval" / "datasets"


@dataclass(frozen=True, slots=True)
class EvalCase:
    question: str
    answer: str | None = None
    relevant_chunk_ids: list[str] = field(default_factory=list)
    relevant_doc_ids: list[str] = field(default_factory=list)
    relevant_doc_names: list[str] = field(default_factory=list)
    supporting_chunk_ids: list[str] = field(default_factory=list)
    should_abstain: bool = False

    @classmethod
    def from_json(cls, obj: dict[str, Any]) -> EvalCase:
        return cls(
            question=str(obj["question"]).strip(),
            answer=(obj.get("answer") or obj.get("expected_answer") or None),
            relevant_chunk_ids=[str(x) for x in obj.get("relevant_chunk_ids", [])],
            relevant_doc_ids=[str(x) for x in obj.get("relevant_doc_ids", [])],
            relevant_doc_names=[str(x) for x in obj.get("relevant_doc_names", [])],
            supporting_chunk_ids=[str(x) for x in obj.get("supporting_chunk_ids", [])],
            should_abstain=bool(obj.get("should_abstain", False)),
        )


@dataclass(slots=True)
class SampleResult:
    case: EvalCase
    generated_answer: str
    retrieved_chunk_ids: list[str]
    context_chunk_ids: list[str]
    cited_chunk_ids: list[str]
    abstained: bool
    latency_ms: dict[str, float]
    token_usage: dict[str, int]
    cost_usd: float
    scores: dict[str, float]


def load_dataset(dataset: str, split: str, *, root: Path | None = None) -> list[EvalCase]:
    base = root or _default_dataset_root()
    path = base / dataset / f"{split}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"dataset not found: {path}")
    cases: list[EvalCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            cases.append(EvalCase.from_json(json.loads(line)))
    if not cases:
        raise ValueError(f"dataset {path} has no samples")
    return cases


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=False
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


class EvaluationService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._k = settings.retrieval.rerank_output_k or 5
        self._dataset_root = (
            Path(settings.eval_dataset_root) if settings.eval_dataset_root else None
        )

    async def _chunks_to_doc_names(self, chunk_ids: list[str]) -> list[str]:
        """Preserve rank order while mapping chunk ids -> owning document filename."""
        if not chunk_ids:
            return []
        from sqlalchemy import select

        from app.infra.db.models import Chunk, Document

        ids = []
        for c in chunk_ids:
            try:
                ids.append(uuid.UUID(c))
            except ValueError:
                continue
        async with session_scope(self._settings) as session:
            rows = (
                await session.execute(
                    select(Chunk.id, Document.filename)
                    .join(Document, Document.id == Chunk.document_id)
                    .where(Chunk.id.in_(ids))
                )
            ).all()
        name_by_id = {str(cid): name for cid, name in rows}
        return [name_by_id[c] for c in chunk_ids if c in name_by_id]

    async def _eval_user_id(self) -> uuid.UUID:
        async with session_scope(self._settings) as session:
            repo = UserRepository(session)
            user = await repo.get_by_email(EVAL_USER_EMAIL)
            if user is None:
                user = repo.add(
                    email=EVAL_USER_EMAIL,
                    password_hash=hash_password(uuid.uuid4().hex),
                    display_name="Evaluation",
                    is_admin=False,
                )
                await session.flush()
            return user.id

    async def run(
        self,
        *,
        knowledge_base_id: uuid.UUID,
        dataset: str,
        split: str,
        config_label: str | None = None,
        judge_enabled: bool = True,
        limit: int | None = None,
        persist: bool = True,
    ) -> uuid.UUID:
        cases = load_dataset(dataset, split, root=self._dataset_root)
        if limit is not None:
            cases = cases[:limit]

        async with session_scope(self._settings) as session:
            kb = await session.get(KnowledgeBase, knowledge_base_id)
            if kb is None:
                raise ValueError(f"knowledge base {knowledge_base_id} not found")
            kb_active_profile = kb.active_embedding_profile_id
            kb_detached = KnowledgeBase(
                id=kb.id,
                owner_id=kb.owner_id,
                name=kb.name,
                slug=kb.slug,
                active_embedding_profile_id=kb_active_profile,
            )

        judge = None
        judge_model: str | None = None
        judge_warning: str | None = None
        if judge_enabled:
            try:
                judge = build_eval_judge(self._settings)
                judge_model = judge.caps.model_id
                judge_warning = family_separation_warning(self._settings.llm_model, judge_model)
                if judge_warning:
                    _log.warning("eval.judge_family_overlap", detail=judge_warning)
            except Exception as exc:
                _log.warning("eval.judge_unavailable", error=str(exc))
                judge = None

        user_id = await self._eval_user_id()
        chat = ChatService(self._settings)
        results: list[SampleResult] = []

        for i, case in enumerate(cases):
            _log.info("eval.sample", i=i, total=len(cases), q=case.question[:60])
            sr = await self._run_case(chat, kb_detached, user_id, case, judge)
            results.append(sr)

        metrics = self._aggregate(results, judge_used=judge is not None)
        if judge_warning:
            metrics["_judge_family_warning"] = judge_warning

        if not persist:
            _log.info("eval.done_no_persist", metrics=metrics)
            return uuid.uuid4()

        return await self._persist(
            knowledge_base_id=knowledge_base_id,
            dataset=dataset,
            split=split,
            config_label=config_label,
            judge_model=judge_model,
            metrics=metrics,
            results=results,
        )

    async def _run_case(
        self,
        chat: ChatService,
        kb: KnowledgeBase,
        user_id: uuid.UUID,
        case: EvalCase,
        judge: Any,
    ) -> SampleResult:
        result = await chat.collect(
            kb, user_id=user_id, message=case.question, conversation_id=None
        )

        retrieved: list[str] = []
        context_ids: list[str] = []
        cited_ids = [c.chunk_id for c in result.citations if c.chunk_id and c.was_cited]
        if result.trace_id:
            async with session_scope(self._settings) as session:
                trace = await session.get(RetrievalTrace, uuid.UUID(result.trace_id))
                if trace is not None:
                    retrieved = [str(h.get("id")) for h in trace.fused if h.get("id")]
                    context_ids = list(trace.context_chunk_ids)
                    cited_ids = list(trace.cited_chunk_ids) or cited_ids
        context_text = "\n\n".join(c.snippet for c in result.citations if c.snippet)

        scores: dict[str, float] = {}
        rel = case.relevant_chunk_ids or case.supporting_chunk_ids
        retrieved_key = retrieved
        if not rel and case.relevant_doc_names:
            rel = case.relevant_doc_names
            retrieved_key = await self._chunks_to_doc_names(retrieved)
        if rel:
            scores["recall_at_k"] = evalm.recall_at_k(retrieved_key, rel, self._k)
            scores["precision_at_k"] = evalm.precision_at_k(retrieved_key, rel, self._k)
            scores["mrr"] = evalm.reciprocal_rank(retrieved_key, rel)
            scores["ndcg_at_k"] = evalm.ndcg_at_k(retrieved_key, rel, self._k)
            scores["hit_at_k"] = evalm.hit_at_k(retrieved_key, rel, self._k)

        cit = evalm.citation_score(cited_ids, context_ids, case.supporting_chunk_ids or None)
        scores["citation_precision"] = cit.precision
        scores["citation_recall"] = cit.recall
        scores["citation_in_context"] = cit.cited_in_context

        ab = evalm.abstention_outcome(
            should_abstain=case.should_abstain, did_abstain=result.abstained
        )
        scores["_ab_tp"] = float(ab.tp)
        scores["_ab_fp"] = float(ab.fp)
        scores["_ab_fn"] = float(ab.fn)
        scores["_ab_tn"] = float(ab.tn)

        if case.answer and not result.abstained:
            scores["answer_token_f1"] = evalm.token_f1(result.answer, case.answer)

        if judge is not None and not (case.should_abstain and result.abstained):
            verdict, _usage = await judge_answer(
                judge,
                question=case.question,
                reference=case.answer,
                context=context_text,
                answer=result.answer,
            )
            if verdict.ok:
                scores["judge_correct"] = verdict.correct
                scores["judge_faithful"] = verdict.faithful
                scores["judge_relevant"] = verdict.relevant

        return SampleResult(
            case=case,
            generated_answer=result.answer,
            retrieved_chunk_ids=retrieved,
            context_chunk_ids=context_ids,
            cited_chunk_ids=cited_ids,
            abstained=result.abstained,
            latency_ms={},
            token_usage={
                "prompt_tokens": result.usage.prompt_tokens,
                "completion_tokens": result.usage.completion_tokens,
            },
            cost_usd=result.cost_usd,
            scores=scores,
        )

    def _aggregate(self, results: Sequence[SampleResult], *, judge_used: bool) -> dict[str, Any]:
        n = self._settings.eval_bootstrap_n
        collected: dict[str, list[float]] = {}
        ab = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
        for sr in results:
            for key, value in sr.scores.items():
                if key.startswith("_ab_"):
                    ab[key[4:]] += int(value)
                    continue
                collected.setdefault(key, []).append(value)

        out: dict[str, Any] = {}
        for key, values in collected.items():
            out[key] = bootstrap_mean_ci(values, n_resamples=n).as_dict()

        ap, ar, af1 = evalm.precision_recall_f1(ab["tp"], ab["fp"], ab["fn"])
        out["abstention_precision"] = {"value": _nan_round(ap), "n": ab["tp"] + ab["fp"]}
        out["abstention_recall"] = {"value": _nan_round(ar), "n": ab["tp"] + ab["fn"]}
        out["abstention_f1"] = {"value": _nan_round(af1), "n": len(results)}

        costs = [sr.cost_usd for sr in results]
        prompt_toks = [float(sr.token_usage["prompt_tokens"]) for sr in results]
        compl_toks = [float(sr.token_usage["completion_tokens"]) for sr in results]
        out["cost_usd_total"] = {"value": round(sum(costs), 6), "n": len(results)}
        out["prompt_tokens_mean"] = bootstrap_mean_ci(prompt_toks, n_resamples=n).as_dict()
        out["completion_tokens_mean"] = bootstrap_mean_ci(compl_toks, n_resamples=n).as_dict()
        out["n_samples"] = len(results)
        out["judge_used"] = judge_used
        safe: dict[str, Any] = _json_safe(out)
        return safe

    async def _persist(
        self,
        *,
        knowledge_base_id: uuid.UUID,
        dataset: str,
        split: str,
        config_label: str | None,
        judge_model: str | None,
        metrics: dict[str, Any],
        results: Sequence[SampleResult],
    ) -> uuid.UUID:
        now = datetime.now(UTC)
        async with session_scope(self._settings) as session:
            run = EvalRun(
                name=config_label or f"{dataset}/{split}",
                dataset_name=dataset,
                dataset_split=split,
                git_sha=_git_sha(),
                config_snapshot=self._settings.redacted_config(),
                judge_model=judge_model,
                metrics=metrics,
                created_at=now,
            )
            session.add(run)
            await session.flush()
            for sr in results:
                session.add(
                    EvalSample(
                        run_id=run.id,
                        question=sr.case.question,
                        expected_answer=sr.case.answer,
                        relevant_chunk_ids=sr.case.relevant_chunk_ids,
                        relevant_doc_ids=sr.case.relevant_doc_ids or sr.case.relevant_doc_names,
                        generated_answer=sr.generated_answer,
                        retrieved_chunk_ids=sr.retrieved_chunk_ids,
                        cited_chunk_ids=sr.cited_chunk_ids,
                        scores=_json_safe(
                            {k: v for k, v in sr.scores.items() if not k.startswith("_")}
                        ),
                        latency_ms=sr.latency_ms,
                        token_usage=sr.token_usage,
                        cost_usd=sr.cost_usd,
                    )
                )
            run_id = run.id
        _log.info("eval.run_persisted", run_id=str(run_id), metrics=metrics)
        return run_id


def _nan_round(x: float) -> float | None:
    return round(x, 4) if x == x else None


def _json_safe(obj: Any) -> Any:
    """Replace non-finite floats (NaN / inf) with None so the payload is valid JSONB."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_json_safe(v) for v in obj]
    return obj
