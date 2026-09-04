"""API key endpoints (docs/ARCHITECTURE.md §23.1)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.context import current_request_id
from app.api.deps import PrincipalDep, SessionDep, SettingsDep
from app.schemas.api_keys import ApiKeyCreate, ApiKeyCreatedResponse, ApiKeyResponse
from app.services.api_keys import ApiKeyService

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> list[ApiKeyResponse]:
    service = ApiKeyService(session, settings)
    return [ApiKeyResponse.from_model(k) for k in await service.list_for(principal)]


@router.post("", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_api_key(
    body: ApiKeyCreate, principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> ApiKeyCreatedResponse:
    service = ApiKeyService(session, settings)
    created = await service.create(
        principal,
        name=body.name,
        scopes=body.scopes,
        knowledge_base_id=body.knowledge_base_id,
        request_id=current_request_id(),
    )
    base = ApiKeyResponse.from_model(created.key)
    return ApiKeyCreatedResponse(**base.model_dump(), token=created.token)


@router.delete("/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> None:
    service = ApiKeyService(session, settings)
    await service.revoke(principal, key_id, request_id=current_request_id())
