"""RAG chat orchestration (docs/ARCHITECTURE.md sections 4-7, 15-18, 28)."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, cast

import structlog

from app.config import Settings
from app.core import citations as cit
from app.core.contextualize import build_rewrite_messages, clean_rewrite
from app.core.enums import MessageRole, RetrievalMode
from app.core.errors import LLMStreamError
from app.core.interfaces.llm import LLMProvider
from app.core.models import ScoredChunk, TokenUsage
from app.core.prompts import _SYSTEM as _SYSTEM_PROMPT_TEXT
from app.core.prompts import EMPTY_KB_REFUSAL, PROMPT_VERSION, REFUSAL_TEXT, build_messages
from app.core.retrieval.budget import BudgetInputs, assemble_context, trim_history
from app.infra.db.models import Conversation, KnowledgeBase
from app.infra.db.repositories.conversations import (
    ConversationRepository,
    MessageRepository,
    TraceRepository,
)
from app.infra.db.session import session_scope
from app.obs.metrics import (
    ABSTENTION,
    INVALID_CITATIONS,
    LLM_COST_USD,
    LLM_TOKENS,
    WEAK_CITATIONS,
)
from app.providers.registry import build_llm_provider
from app.services.retrieval import RetrievalResult, RetrievalService

_log = structlog.get_logger("app.chat")


@dataclass(slots=True)
class ChatCitation:
    index: int
    chunk_id: str | None
    document_id: str | None
    filename: str
    page_no: int | None
    snippet: str
    was_cited: bool
    weak: bool
    score: float | None


@dataclass(slots=True)
class ChatResult:
    answer: str
    citations: list[ChatCitation] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=lambda: TokenUsage(0, 0))
    cost_usd: float = 0.0
    trace_id: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    abstained: bool = False
    low_confidence: bool = False
    degraded: dict[str, bool] = field(default_factory=dict)
    uncited_sentences: list[str] = field(default_factory=list)
    finish_reason: str = "stop"


class ChatService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._retrieval = RetrievalService(settings)

    async def _rewrite(
        self, llm: LLMProvider, message: str, history: list[tuple[str, str]]
    ) -> tuple[str, bool]:
        r = self._settings.retrieval
        if not r.query_rewrite_enabled or not history:
            return message, False
        try:
            msgs = build_rewrite_messages(message, history, max_turns=r.query_rewrite_history_turns)
            text, _usage = await asyncio.wait_for(
                llm.complete(msgs, temperature=0.0), timeout=r.query_rewrite_timeout_ms / 1000
            )
            rewritten = clean_rewrite(text, message)
            return rewritten, rewritten != message
        except Exception as exc:
            _log.warning("chat.rewrite_degraded", error=str(exc))
            return message, False

    async def _load_context(
        self, conversation_id: uuid.UUID | None, user_id: uuid.UUID
    ) -> tuple[Conversation | None, list[tuple[str, str]]]:
        if conversation_id is None:
            return None, []
        async with session_scope(self._settings) as session:
            repo = ConversationRepository(session)
            conv = await repo.get(conversation_id)
            if conv is None or conv.user_id != user_id:
                return None, []
            msgs = await repo.history(conversation_id)
        history = [
            (m.role.value, m.content)
            for m in msgs
            if m.role in (MessageRole.USER, MessageRole.ASSISTANT)
        ]
        return conv, history

    async def answer(
        self,
        kb: KnowledgeBase,
        *,
        user_id: uuid.UUID,
        message: str,
        conversation_id: uuid.UUID | None,
        mode: RetrievalMode = RetrievalMode.HYBRID,
        overrides: dict[str, object] | None = None,
    ) -> AsyncIterator[dict[str, object]]:
        """Yields SSE-style events: {'type': 'token'|'done'|'error', ...}. The final
        'done' event's payload is also everything needed to persist the turn."""

        started = time.perf_counter()
        timings: dict[str, float] = {}
        llm = build_llm_provider(self._settings)

        conv, history = await self._load_context(conversation_id, user_id)

        t = time.perf_counter()
        search_query, rewritten = await self._rewrite(llm, message, history)
        timings["rewrite"] = round((time.perf_counter() - t) * 1000, 1)

        result = await self._retrieval.retrieve(
            knowledge_base_id=kb.id,
            kb_active_profile=kb.active_embedding_profile_id,
            search_query=search_query,
            mode=mode,
            overrides=overrides,
        )
        timings.update(result.latency_ms)

        if result.abstention.abstain:
            ABSTENTION.labels(reason=result.abstention.reason or "unknown").inc()
            refusal = EMPTY_KB_REFUSAL if result.abstention.reason == "empty_kb" else REFUSAL_TEXT
            persisted = await self._persist(
                kb=kb,
                conv=conv,
                user_id=user_id,
                message=message,
                search_query=search_query,
                rewritten=rewritten,
                answer=refusal,
                context_chunks=[],
                citation_result=None,
                usage=TokenUsage(0, 0),
                cost=0.0,
                result=result,
                timings=timings,
                abstained=True,
                low_confidence=False,
                finish_reason="abstained",
            )
            yield {"type": "token", "text": refusal}
            yield {
                "type": "done",
                "answer": refusal,
                "citations": [],
                "abstained": True,
                "low_confidence": False,
                "degraded": result.degraded,
                "trace_id": persisted["trace_id"],
                "conversation_id": persisted["conversation_id"],
                "message_id": persisted["message_id"],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                "cost_usd": 0.0,
            }
            return

        context_chunks = await self._hydrate(result.candidates)
        assembled = assemble_context(
            context_chunks,
            inputs=self._budget_inputs(llm, message),
            count_tokens=llm.count_tokens,
            expand=lambda c: c.content,
        )
        history_trimmed = trim_history(
            history, budget=assembled.history_token_budget, count_tokens=llm.count_tokens
        )
        prompt = build_messages(
            question=message, context_blocks=assembled.blocks, history=history_trimmed
        )
        prompt_tokens = sum(llm.count_tokens(m.content) for m in prompt)

        # ── generation ─────────────────────────────────────────────────────
        answer_parts: list[str] = []
        finish_reason = "stop"
        first_token = False
        gen_start = time.perf_counter()
        try:
            async for delta in llm.generate(
                prompt,
                temperature=self._settings.llm_temperature,
                max_tokens=self._settings.llm_max_tokens,
            ):
                if delta.text:
                    if not first_token:
                        timings["ttft"] = round((time.perf_counter() - gen_start) * 1000, 1)
                        first_token = True
                    answer_parts.append(delta.text)
                    yield {"type": "token", "text": delta.text}
                if delta.finish_reason:
                    finish_reason = delta.finish_reason
        except LLMStreamError as exc:
            if not first_token and self._settings.llm_fallback_provider is not None:
                async for ev in self._fallback(
                    kb,
                    conv,
                    user_id,
                    message,
                    search_query,
                    rewritten,
                    result,
                    assembled,
                    history_trimmed,
                    timings,
                    context_chunks,
                ):
                    yield ev
                return
            yield {"type": "error", "code": "provider_error", "message": str(exc)}
            return
        except Exception as exc:
            _log.exception("chat.generation_failed")
            yield {"type": "error", "code": "internal", "message": "generation failed"}
            _ = exc
            return

        timings["generate"] = round((time.perf_counter() - gen_start) * 1000, 1)
        raw_answer = "".join(answer_parts)
        completion_tokens = llm.count_tokens(raw_answer)
        usage = TokenUsage(prompt_tokens, completion_tokens)
        cost = self._cost(llm, usage)

        weak = await self._weak_citations(raw_answer, assembled.citation_map, context_chunks)
        citation_result = cit.parse_and_validate(
            raw_answer, assembled.citation_map, weak_sentences=weak
        )
        timings["total"] = round((time.perf_counter() - started) * 1000, 1)

        LLM_TOKENS.labels(kind="prompt").inc(usage.prompt_tokens)
        LLM_TOKENS.labels(kind="completion").inc(usage.completion_tokens)
        if cost:
            LLM_COST_USD.inc(cost)
        if citation_result.invalid_markers:
            INVALID_CITATIONS.inc(citation_result.invalid_markers)
        if weak:
            WEAK_CITATIONS.inc(len(weak))

        persisted = await self._persist(
            kb=kb,
            conv=conv,
            user_id=user_id,
            message=message,
            search_query=search_query,
            rewritten=rewritten,
            answer=citation_result.text,
            context_chunks=context_chunks,
            citation_result=citation_result,
            usage=usage,
            cost=cost,
            result=result,
            timings=timings,
            abstained=False,
            low_confidence=result.abstention.low_confidence,
            finish_reason=finish_reason,
            citation_map=assembled.citation_map,
        )

        yield {
            "type": "done",
            "answer": citation_result.text,
            "citations": persisted["citations"],
            "abstained": False,
            "low_confidence": result.abstention.low_confidence,
            "degraded": result.degraded,
            "uncited_sentences": citation_result.uncited_sentences,
            "trace_id": persisted["trace_id"],
            "conversation_id": persisted["conversation_id"],
            "message_id": persisted["message_id"],
            "usage": {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
            },
            "cost_usd": cost,
        }

    async def collect(
        self,
        kb: KnowledgeBase,
        *,
        user_id: uuid.UUID,
        message: str,
        conversation_id: uuid.UUID | None,
        mode: RetrievalMode = RetrievalMode.HYBRID,
        overrides: dict[str, object] | None = None,
    ) -> ChatResult:
        result = ChatResult(answer="")
        async for event in self.answer(
            kb,
            user_id=user_id,
            message=message,
            conversation_id=conversation_id,
            mode=mode,
            overrides=overrides,
        ):
            if event["type"] == "error":
                raise LLMStreamError(str(event.get("message", "generation failed")))
            if event["type"] == "done":
                ev = cast("dict[str, Any]", event)
                result.answer = str(ev["answer"])
                result.abstained = bool(ev["abstained"])
                result.low_confidence = bool(ev["low_confidence"])
                result.degraded = dict(ev.get("degraded") or {})
                result.trace_id = ev.get("trace_id")
                result.conversation_id = ev.get("conversation_id")
                result.message_id = ev.get("message_id")
                u = ev.get("usage") or {}
                result.usage = TokenUsage(
                    int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))
                )
                result.cost_usd = float(ev.get("cost_usd", 0.0))
                result.uncited_sentences = list(ev.get("uncited_sentences") or [])
                result.citations = [ChatCitation(**c) for c in ev.get("citations") or []]
        return result

    # ── helpers ────────────────────────────────────────────────────────────
    def _budget_inputs(self, llm: LLMProvider, message: str) -> BudgetInputs:
        r = self._settings.retrieval
        return BudgetInputs(
            context_window=llm.caps.context_window,
            max_output_tokens=min(self._settings.llm_max_tokens, llm.caps.max_output_tokens),
            system_tokens=llm.count_tokens(_SYSTEM_PROMPT_TEXT),
            question_tokens=llm.count_tokens(message),
            safety_margin=r.token_safety_margin,
            response_headroom_tokens=r.response_headroom_tokens,
            context_budget_share=r.context_budget_share,
        )

    def _cost(self, llm: LLMProvider, usage: TokenUsage) -> float:
        ci = llm.caps.cost_per_1k_input_usd or 0.0
        co = llm.caps.cost_per_1k_output_usd or 0.0
        return round(usage.prompt_tokens / 1000 * ci + usage.completion_tokens / 1000 * co, 6)

    async def _hydrate(self, candidates: list[ScoredChunk]) -> list[ScoredChunk]:
        return candidates  # RetrievalService already hydrated content + filename

    async def _weak_citations(
        self,
        answer: str,
        citation_map: dict[int, tuple[str, str]],
        chunks: list[ScoredChunk],
    ) -> set[int]:
        threshold = self._settings.retrieval.citation_sim_warn
        by_id = {c.chunk_id: c for c in chunks}
        weak: set[int] = set()
        embedder = self._retrieval._embedder
        for sentence, markers in cit.sentences_with_markers(answer):
            if not sentence:
                continue
            try:
                svec = await embedder.embed_query(sentence)
            except Exception:
                return set()
            for n in markers:
                mapped = citation_map.get(n)
                if not mapped:
                    continue
                chunk = by_id.get(mapped[0])
                if chunk is None or not chunk.dense:
                    continue
                if _cos(svec, chunk.dense) < threshold:
                    weak.add(n)
        return weak

    async def _fallback(self, *args: object) -> AsyncIterator[dict[str, object]]:
        _log.info("chat.fallback_provider")
        yield {"type": "error", "code": "provider_error", "message": "primary provider failed"}

    async def _persist(
        self,
        *,
        kb: KnowledgeBase,
        conv: Conversation | None,
        user_id: uuid.UUID,
        message: str,
        search_query: str,
        rewritten: bool,
        answer: str,
        context_chunks: list[ScoredChunk],
        citation_result: cit.CitationResult | None,
        usage: TokenUsage,
        cost: float,
        result: RetrievalResult,
        timings: dict[str, float],
        abstained: bool,
        low_confidence: bool,
        finish_reason: str,
        citation_map: dict[int, tuple[str, str]] | None = None,
    ) -> dict[str, object]:
        llm = build_llm_provider(self._settings)
        async with session_scope(self._settings) as session:
            conv_repo = ConversationRepository(session)
            if conv is None:
                conv_model = conv_repo.add(
                    knowledge_base_id=kb.id, user_id=user_id, title=message[:80] or "Conversation"
                )
                await session.flush()
            else:
                loaded = await conv_repo.get(conv.id)
                assert loaded is not None
                conv_model = loaded

            mrepo = MessageRepository(session)
            mrepo.add(
                conversation_id=conv_model.id,
                role=MessageRole.USER,
                content=message,
                raw_query=message,
                search_query=search_query,
                was_rewritten=rewritten,
            )
            assistant = mrepo.add(
                conversation_id=conv_model.id,
                role=MessageRole.ASSISTANT,
                content=answer,
                model=llm.caps.model_id,
                prompt_version=PROMPT_VERSION,
                raw_query=message,
                search_query=search_query,
                was_rewritten=rewritten,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                estimated_cost_usd=cost,
                latency_ms=timings,
                finish_reason=finish_reason,
                abstained=abstained,
                low_confidence=low_confidence,
                degraded=result.degraded,
            )
            await session.flush()

            citations_payload: list[dict[str, object]] = []
            cited_ids: list[str] = []
            if citation_result is not None and citation_map is not None:
                by_id = {c.chunk_id: c for c in context_chunks}
                rec_by_idx = {rec.citation_index: rec for rec in citation_result.records}
                for idx, (chunk_id, doc_id) in citation_map.items():
                    chunk = by_id.get(chunk_id)
                    rec = rec_by_idx.get(idx)
                    mrepo.add_citation(
                        message_id=assistant.id,
                        citation_index=idx,
                        chunk_id=uuid.UUID(chunk_id),
                        document_id=uuid.UUID(doc_id),
                        score=chunk.score if chunk else None,
                        was_cited=rec.was_cited if rec else False,
                        weak=rec.weak if rec else False,
                        chunk_content_snapshot=(chunk.content[:2000] if chunk else None),
                        document_filename=chunk.filename if chunk else None,
                    )
                    if rec and rec.was_cited:
                        cited_ids.append(chunk_id)
                    citations_payload.append(
                        {
                            "index": idx,
                            "chunk_id": chunk_id,
                            "document_id": doc_id,
                            "filename": chunk.filename if chunk else "",
                            "page_no": chunk.page_no if chunk else None,
                            "snippet": (chunk.content[:300] if chunk else ""),
                            "was_cited": rec.was_cited if rec else False,
                            "weak": rec.weak if rec else False,
                            "score": chunk.score if chunk else None,
                        }
                    )

            trace = TraceRepository(session).add(
                message_id=assistant.id,
                raw_query=message,
                search_query=search_query,
                was_rewritten=rewritten,
                embedding_profile_id=result.embedding_profile_id,
                fusion_strategy=result.fusion_strategy,
                params={"mode": result.mode.value},
                dense_hits=result.dense_hits,
                sparse_hits=result.sparse_hits,
                fused=result.fused,
                reranked=result.reranked,
                context_chunk_ids=[c.chunk_id for c in context_chunks],
                cited_chunk_ids=cited_ids,
                abstained=abstained,
                low_confidence=low_confidence,
                degraded=result.degraded,
                latency_ms=timings,
                token_usage={
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                },
                estimated_cost_usd=cost,
            )
            await session.flush()

            conv_model.total_tokens += usage.total_tokens
            conv_model.total_cost_usd = round(float(conv_model.total_cost_usd) + cost, 6)

            return {
                "conversation_id": str(conv_model.id),
                "message_id": str(assistant.id),
                "trace_id": str(trace.id),
                "citations": citations_payload,
            }


def _cos(a: list[float], b: tuple[float, ...] | list[float]) -> float:
    import math

    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)
