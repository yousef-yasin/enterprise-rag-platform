"""Knowledge base + membership endpoints (docs/ARCHITECTURE.md §23.1)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.context import current_request_id
from app.api.deps import (
    AuthServiceDep,
    KBOwnerDep,
    KBViewerDep,
    PrincipalDep,
    SessionDep,
    SettingsDep,
)
from app.core.enums import KBRole
from app.schemas.common import Page
from app.schemas.knowledge_bases import (
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
    MemberAddRequest,
    MemberResponse,
)
from app.services.knowledge_bases import KnowledgeBaseService

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.post("", response_model=KnowledgeBaseResponse, status_code=201)
async def create_kb(
    body: KnowledgeBaseCreate, principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> KnowledgeBaseResponse:
    service = KnowledgeBaseService(session, settings)
    kb = await service.create(
        principal,
        name=body.name,
        slug=body.slug,
        description=body.description,
        request_id=current_request_id(),
    )
    return KnowledgeBaseResponse.from_model(kb, your_role=KBRole.OWNER)


@router.get("", response_model=Page[KnowledgeBaseResponse])
async def list_kbs(
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    auth: AuthServiceDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[KnowledgeBaseResponse]:
    service = KnowledgeBaseService(session, settings)
    kbs = await service.list_for(principal, limit=limit + 1, offset=offset)
    has_more = len(kbs) > limit
    kbs = kbs[:limit]
    items: list[KnowledgeBaseResponse] = []
    for kb in kbs:
        role = await auth.effective_role(kb, principal)
        items.append(KnowledgeBaseResponse.from_model(kb, your_role=role or KBRole.VIEWER))
    return Page(items=items, limit=limit, offset=offset, has_more=has_more)


@router.get("/{kb_id}", response_model=KnowledgeBaseResponse)
async def get_kb(ctx: KBViewerDep) -> KnowledgeBaseResponse:
    return KnowledgeBaseResponse.from_model(ctx.kb, your_role=ctx.role)


@router.patch("/{kb_id}", response_model=KnowledgeBaseResponse)
async def update_kb(
    body: KnowledgeBaseUpdate, ctx: KBOwnerDep, session: SessionDep, settings: SettingsDep
) -> KnowledgeBaseResponse:
    service = KnowledgeBaseService(session, settings)
    kb = await service.update(ctx.kb, name=body.name, description=body.description)
    return KnowledgeBaseResponse.from_model(kb, your_role=ctx.role)


@router.delete("/{kb_id}", status_code=204)
async def delete_kb(ctx: KBOwnerDep, session: SessionDep, settings: SettingsDep) -> None:
    service = KnowledgeBaseService(session, settings)
    await service.delete(ctx.kb, ctx.principal, request_id=current_request_id())


@router.get("/{kb_id}/members", response_model=list[MemberResponse])
async def list_members(
    ctx: KBOwnerDep, session: SessionDep, settings: SettingsDep
) -> list[MemberResponse]:
    service = KnowledgeBaseService(session, settings)
    return [
        MemberResponse.from_model(v.member, email=v.email, display_name=v.display_name)
        for v in await service.list_members(ctx.kb)
    ]


@router.post("/{kb_id}/members", response_model=MemberResponse, status_code=201)
async def add_member(
    body: MemberAddRequest, ctx: KBOwnerDep, session: SessionDep, settings: SettingsDep
) -> MemberResponse:
    service = KnowledgeBaseService(session, settings)
    view = await service.add_member(
        ctx.kb, ctx.principal, email=body.email, role=body.role, request_id=current_request_id()
    )
    return MemberResponse.from_model(view.member, email=view.email, display_name=view.display_name)


@router.delete("/{kb_id}/members/{user_id}", status_code=204)
async def remove_member(
    user_id: uuid.UUID, ctx: KBOwnerDep, session: SessionDep, settings: SettingsDep
) -> None:
    service = KnowledgeBaseService(session, settings)
    await service.remove_member(
        ctx.kb, ctx.principal, user_id=user_id, request_id=current_request_id()
    )
