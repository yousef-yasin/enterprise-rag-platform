"""FastAPI dependency providers (docs/ARCHITECTURE.md §3.2, §4.1, §25)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AuthMode, Settings, get_settings
from app.core.enums import ApiKeyScope, KBRole
from app.core.errors import AuthError, ForbiddenError, NotFoundError
from app.core.principal import Principal
from app.core.security import API_KEY_PREFIX
from app.infra.db.models import KnowledgeBase
from app.infra.db.session import get_sessionmaker
from app.services.auth import AuthService
from app.services.health import HealthService, build_default_probes

SettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_session(settings: SettingsDep) -> AsyncIterator[AsyncSession]:
    factory = get_sessionmaker(settings)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_health_service(settings: SettingsDep) -> HealthService:
    return HealthService(build_default_probes(settings))


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]


def get_auth_service(session: SessionDep, settings: SettingsDep) -> AuthService:
    return AuthService(session, settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


async def get_current_principal(
    request: Request, settings: SettingsDep, auth: AuthServiceDep
) -> Principal:
    if settings.auth_mode is AuthMode.SINGLE_USER:
        expected = settings.app_token.get_secret_value() if settings.app_token else None
        supplied = _bearer_token(request) or request.headers.get("x-app-token")
        if not expected or supplied != expected:
            raise AuthError("APP_TOKEN required")
        return await auth.single_user_principal()

    token = _bearer_token(request)
    if not token:
        raise AuthError("missing bearer token")
    if token.startswith(API_KEY_PREFIX):
        return await auth.principal_from_api_key(token)
    return await auth.principal_from_access_token(token)


PrincipalDep = Annotated[Principal, Depends(get_current_principal)]


async def get_optional_principal(
    request: Request, settings: SettingsDep, auth: AuthServiceDep
) -> Principal | None:
    try:
        return await get_current_principal(request, settings, auth)
    except AuthError:
        return None


OptionalPrincipalDep = Annotated[Principal | None, Depends(get_optional_principal)]


async def require_admin(principal: PrincipalDep) -> Principal:
    if not principal.is_admin:
        raise ForbiddenError("administrator access required")
    return principal


AdminDep = Annotated[Principal, Depends(require_admin)]


@dataclass(frozen=True, slots=True)
class KBContext:
    kb: KnowledgeBase
    principal: Principal
    role: KBRole


class KBAccess:
    """Reusable dependency: ``Depends(KBAccess(KBRole.EDITOR, ApiKeyScope.KB_INGEST))``.

    Resolves the ``{kb_id}`` path parameter, enforces role + scope, and yields the KB
    plus the caller's effective role. Unknown/unauthorized KBs both raise 404.
    """

    def __init__(self, role: KBRole, scope: ApiKeyScope) -> None:
        self._role = role
        self._scope = scope

    async def __call__(
        self, kb_id: str, principal: PrincipalDep, auth: AuthServiceDep
    ) -> KBContext:
        try:
            parsed = uuid.UUID(kb_id)
        except ValueError as exc:
            raise NotFoundError("knowledge base not found") from exc
        kb = await auth.require_kb(parsed, principal, role=self._role, scope=self._scope)
        role = await auth.effective_role(kb, principal)
        assert role is not None
        return KBContext(kb=kb, principal=principal, role=role)


KBViewerDep = Annotated[KBContext, Depends(KBAccess(KBRole.VIEWER, ApiKeyScope.KB_READ))]
KBChatDep = Annotated[KBContext, Depends(KBAccess(KBRole.VIEWER, ApiKeyScope.CHAT))]
KBEditorDep = Annotated[KBContext, Depends(KBAccess(KBRole.EDITOR, ApiKeyScope.KB_INGEST))]
KBOwnerDep = Annotated[KBContext, Depends(KBAccess(KBRole.OWNER, ApiKeyScope.KB_MANAGE))]


@dataclass(frozen=True, slots=True)
class DocContext:
    document: object  # app.infra.db.models.Document
    kb: KnowledgeBase
    principal: Principal
    role: KBRole


class DocAccess:
    """Resolve the ``{document_id}`` path param -> its KB -> enforce role + scope."""

    def __init__(self, role: KBRole, scope: ApiKeyScope) -> None:
        self._role = role
        self._scope = scope

    async def __call__(
        self, document_id: str, principal: PrincipalDep, auth: AuthServiceDep, session: SessionDep
    ) -> DocContext:
        from app.infra.db.repositories.documents import DocumentRepository

        try:
            parsed = uuid.UUID(document_id)
        except ValueError as exc:
            raise NotFoundError("document not found") from exc
        doc = await DocumentRepository(session).get_active(parsed)
        if doc is None:
            raise NotFoundError("document not found")
        kb = await auth.require_kb(
            doc.knowledge_base_id, principal, role=self._role, scope=self._scope
        )
        role = await auth.effective_role(kb, principal)
        assert role is not None
        return DocContext(document=doc, kb=kb, principal=principal, role=role)


DocViewerDep = Annotated[DocContext, Depends(DocAccess(KBRole.VIEWER, ApiKeyScope.KB_READ))]
DocEditorDep = Annotated[DocContext, Depends(DocAccess(KBRole.EDITOR, ApiKeyScope.KB_INGEST))]
