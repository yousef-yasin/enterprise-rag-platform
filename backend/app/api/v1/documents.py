"""Document upload / status / reprocess / delete (docs/ARCHITECTURE.md §23.1)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import structlog
from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api.context import current_request_id
from app.api.deps import (
    DocEditorDep,
    DocViewerDep,
    KBEditorDep,
    KBViewerDep,
    SessionDep,
    SettingsDep,
)
from app.core.enums import DocumentStatus
from app.core.errors import PayloadTooLargeError
from app.infra.db.models import Document
from app.infra.db.repositories.documents import DocumentRepository
from app.schemas.common import Page
from app.schemas.documents import DocumentResponse
from app.services.ingestion import IngestionService

router = APIRouter(tags=["documents"])
_log = structlog.get_logger("app.api.documents")

_TERMINAL = {DocumentStatus.READY, DocumentStatus.PARTIALLY_INDEXED, DocumentStatus.FAILED}


@router.post(
    "/knowledge-bases/{kb_id}/documents",
    response_model=DocumentResponse,
    status_code=202,
)
async def upload_document(
    ctx: KBEditorDep,
    settings: SettingsDep,
    session: SessionDep,
    request: Request,
    file: UploadFile = File(...),
) -> DocumentResponse:
    max_bytes = settings.max_upload_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise PayloadTooLargeError(f"file exceeds the {settings.max_upload_mb} MB limit")

    service = IngestionService(session, settings)
    result = await service.upload(
        ctx.kb,
        ctx.principal,
        filename=file.filename or "upload",
        data=data,
        request_id=current_request_id(),
    )
    return DocumentResponse.from_model(result.document)


@router.get(
    "/knowledge-bases/{kb_id}/documents",
    response_model=Page[DocumentResponse],
)
async def list_documents(
    ctx: KBViewerDep,
    session: SessionDep,
    status: DocumentStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[DocumentResponse]:
    docs = await DocumentRepository(session).list_for_kb(
        ctx.kb.id, status=status, limit=limit + 1, offset=offset
    )
    has_more = len(docs) > limit
    return Page(
        items=[DocumentResponse.from_model(d) for d in docs[:limit]],
        limit=limit,
        offset=offset,
        has_more=has_more,
    )


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(ctx: DocViewerDep) -> DocumentResponse:
    return DocumentResponse.from_model(_doc(ctx.document))


@router.post("/documents/{document_id}/reprocess", status_code=202, response_model=DocumentResponse)
async def reprocess_document(
    ctx: DocEditorDep, session: SessionDep, settings: SettingsDep
) -> DocumentResponse:
    service = IngestionService(session, settings)
    doc = _doc(ctx.document)
    await service.reprocess(doc, ctx.principal, request_id=current_request_id())
    return DocumentResponse.from_model(doc)


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(ctx: DocEditorDep, session: SessionDep, settings: SettingsDep) -> None:
    service = IngestionService(session, settings)
    await service.soft_delete(_doc(ctx.document), ctx.principal, request_id=current_request_id())


@router.get("/documents/{document_id}/status/stream")
async def stream_status(ctx: DocViewerDep, settings: SettingsDep) -> StreamingResponse:
    document = _doc(ctx.document)

    async def events() -> AsyncIterator[bytes]:
        from app.infra.db.session import session_scope
        from app.infra.redis import jobstream
        from app.infra.redis.client import get_redis

        def sse(payload: dict[str, object]) -> bytes:
            return f"data: {json.dumps(payload)}\n\n".encode()

        # 1. current status from Postgres (authoritative)
        async with session_scope(settings) as s:
            fresh = await DocumentRepository(s).get(document.id)
        assert fresh is not None
        yield sse({"status": fresh.status.value, "stage": fresh.failed_stage, "source": "db"})
        if fresh.status in _TERMINAL:
            yield sse({"event": "done"})
            return

        # 2. follow the Redis stream, re-checking Postgres on each heartbeat
        try:
            redis = get_redis(settings)
            async for _rid, payload in jobstream.follow(redis, str(document.id), block_ms=3000):
                if payload:
                    yield sse(payload)
                    if payload.get("status") in {s.value for s in _TERMINAL}:
                        yield sse({"event": "done"})
                        return
                else:
                    async with session_scope(settings) as s:
                        current = await DocumentRepository(s).get(document.id)
                    if current is not None:
                        yield sse({"status": current.status.value, "source": "db"})
                        if current.status in _TERMINAL:
                            yield sse({"event": "done"})
                            return
        except Exception:
            while True:
                await asyncio.sleep(settings.status_poll_interval_s)
                async with session_scope(settings) as s:
                    current = await DocumentRepository(s).get(document.id)
                if current is None:
                    return
                yield sse({"status": current.status.value, "source": "db-poll"})
                if current.status in _TERMINAL:
                    yield sse({"event": "done"})
                    return

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _doc(obj: object) -> Document:
    assert isinstance(obj, Document)
    return obj
