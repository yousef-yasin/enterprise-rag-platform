"""Retrieval-only + exact-match endpoints (docs/ARCHITECTURE.md section 23.1)."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import AuthServiceDep, KBViewerDep, PrincipalDep, SessionDep, SettingsDep
from app.core.enums import ApiKeyScope, KBRole
from app.infra.db.models import Chunk
from app.schemas.search import SearchHit, SearchRequest, SearchResponse
from app.services.retrieval import RetrievalService

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(
    body: SearchRequest,
    settings: SettingsDep,
    principal: PrincipalDep,
    auth: AuthServiceDep,
) -> SearchResponse:
    kb = await auth.require_kb(
        body.knowledge_base_id, principal, role=KBRole.VIEWER, scope=ApiKeyScope.KB_READ
    )
    service = RetrievalService(settings)
    result = await service.retrieve(
        knowledge_base_id=kb.id,
        kb_active_profile=kb.active_embedding_profile_id,
        search_query=body.query,
        mode=body.params.mode,
    )
    hits = [
        SearchHit(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            score=c.score,
            filename=c.filename,
            page_no=c.page_no,
            snippet=c.content[:400],
            section_path=list(c.section_path),
        )
        for c in result.candidates
    ]
    trace = None
    if body.include_trace:
        trace = {
            "dense_hits": result.dense_hits,
            "sparse_hits": result.sparse_hits,
            "fused": result.fused,
            "reranked": result.reranked,
            "latency_ms": result.latency_ms,
            "embedding_profile_id": result.embedding_profile_id,
        }
    return SearchResponse(
        search_query=result.search_query,
        mode=result.mode,
        hits=hits,
        abstained=result.abstention.abstain,
        low_confidence=result.abstention.low_confidence,
        degraded=result.degraded,
        fusion_strategy=result.fusion_strategy,
        trace=trace,
    )


@router.get("/knowledge-bases/{kb_id}/search/exact")
async def exact_search(
    ctx: KBViewerDep,
    session: SessionDep,
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    stmt = (
        select(Chunk.id, Chunk.document_id, Chunk.content, Chunk.page_no)
        .where(
            Chunk.knowledge_base_id == ctx.kb.id,
            Chunk.content_tsv.op("@@")(func.websearch_to_tsquery("english", q)),
        )
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return {
        "query": q,
        "hits": [
            {
                "chunk_id": str(cid),
                "document_id": str(did),
                "page_no": page,
                "snippet": content[:400],
            }
            for cid, did, content, page in rows
        ],
    }
