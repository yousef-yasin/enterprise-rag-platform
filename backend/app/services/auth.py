"""Authentication & authorization service (docs/ARCHITECTURE.md §25)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AuthMode, Settings
from app.core.enums import ActorType, ApiKeyScope, AuditAction, KBRole
from app.core.errors import AuthError, ForbiddenError, NotFoundError, ValidationError
from app.core.principal import Principal
from app.core.security import (
    TokenError,
    create_jwt,
    decode_jwt,
    hash_password,
    password_needs_rehash,
    verify_api_key,
    verify_password,
)
from app.infra.db.models import KnowledgeBase, User
from app.infra.db.repositories.api_keys import ApiKeyRepository
from app.infra.db.repositories.audit import AuditRepository
from app.infra.db.repositories.knowledge_bases import KnowledgeBaseRepository
from app.infra.db.repositories.users import UserRepository

SINGLE_USER_EMAIL = "local@localhost"


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._users = UserRepository(session)
        self._keys = ApiKeyRepository(session)
        self._kbs = KnowledgeBaseRepository(session)
        self._audit = AuditRepository(session)

    # ── registration / login ───────────────────────────────────────────────
    async def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
        actor: Principal | None = None,
        make_admin: bool = False,
    ) -> User:
        if self._settings.auth_mode is AuthMode.SINGLE_USER:
            raise ForbiddenError("registration is disabled in single-user mode")
        if len(password) < 8:
            raise ValidationError("password must be at least 8 characters")

        existing_count = await self._users.count()
        acting_admin = actor is not None and actor.is_admin
        if existing_count > 0 and not self._settings.allow_open_registration and not acting_admin:
            raise ForbiddenError(
                "open registration is disabled; an administrator must create your account"
            )
        if await self._users.get_by_email(email) is not None:
            raise ValidationError("an account with that email already exists")

        # The very first user is the administrator.
        is_admin = existing_count == 0 or (acting_admin and make_admin)
        user = self._users.add(
            email=email,
            password_hash=hash_password(password),
            display_name=display_name or email.split("@")[0],
            is_admin=is_admin,
        )
        await self._session.flush()
        self._audit.record(
            actor_type=ActorType.SYSTEM if is_admin else ActorType.USER,
            actor_id=user.id,
            action=AuditAction.USER_CREATE,
            target_type="user",
            target_id=user.id,
            meta={"is_admin": is_admin, "self_registered": True},
        )
        return user

    async def authenticate(self, *, email: str, password: str, request_id: str | None) -> User:
        user = await self._users.get_by_email(email)
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            self._audit.record(
                actor_type=ActorType.SYSTEM,
                actor_id=user.id if user else None,
                action=AuditAction.AUTH_LOGIN_FAILED,
                meta={"email": email.strip().lower()},
                request_id=request_id,
            )
            raise AuthError("invalid email or password")
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        return user

    def issue_tokens(self, user: User) -> TokenPair:
        secret = self._settings.jwt_secret.get_secret_value()
        access = create_jwt(
            str(user.id),
            token_type="access",
            secret=secret,
            ttl_seconds=self._settings.jwt_access_ttl_min * 60,
            extra={"admin": user.is_admin},
        )
        refresh = create_jwt(
            str(user.id),
            token_type="refresh",
            secret=secret,
            ttl_seconds=self._settings.jwt_refresh_ttl_days * 86400,
        )
        return TokenPair(access_token=access, refresh_token=refresh)

    async def refresh(self, refresh_token: str) -> TokenPair:
        secret = self._settings.jwt_secret.get_secret_value()
        try:
            payload = decode_jwt(refresh_token, secret=secret, expected_type="refresh")
        except TokenError as exc:
            raise AuthError(str(exc)) from exc
        user = await self._users.get(uuid.UUID(payload["sub"]))
        if user is None or not user.is_active:
            raise AuthError("account not found or disabled")
        return self.issue_tokens(user)

    # ── principal resolution ───────────────────────────────────────────────
    async def principal_from_access_token(self, token: str) -> Principal:
        secret = self._settings.jwt_secret.get_secret_value()
        try:
            payload = decode_jwt(token, secret=secret, expected_type="access")
        except TokenError as exc:
            raise AuthError(str(exc)) from exc
        user = await self._users.get(uuid.UUID(payload["sub"]))
        if user is None or not user.is_active:
            raise AuthError("account not found or disabled")
        return Principal(user_id=user.id, is_admin=user.is_admin, actor_type=ActorType.USER)

    async def principal_from_api_key(self, token: str) -> Principal:
        if len(token) < 12:
            raise AuthError("invalid API key")
        key = await self._keys.get_by_prefix(token[:12])
        if key is None or key.revoked_at is not None or not verify_api_key(token, key.key_hash):
            raise AuthError("invalid API key")
        user = await self._users.get(key.user_id)
        if user is None or not user.is_active:
            raise AuthError("account not found or disabled")
        await self._keys.touch(key)
        return Principal(
            user_id=user.id,
            is_admin=user.is_admin,
            actor_type=ActorType.API_KEY,
            api_key_id=key.id,
            api_key_scopes=frozenset(ApiKeyScope(s) for s in key.scopes),
            api_key_kb_id=key.knowledge_base_id,
        )

    async def single_user_principal(self) -> Principal:
        """Resolve (creating on first use) the implicit local user for single-user mode."""

        user = await self._users.get_by_email(SINGLE_USER_EMAIL)
        if user is None:
            user = self._users.add(
                email=SINGLE_USER_EMAIL,
                password_hash=hash_password(uuid.uuid4().hex),
                display_name="Local User",
                is_admin=True,
            )
            await self._session.flush()
        return Principal(user_id=user.id, is_admin=True, actor_type=ActorType.USER)

    # ── authorization ──────────────────────────────────────────────────────
    async def require_kb(
        self,
        kb_id: uuid.UUID,
        principal: Principal,
        *,
        role: KBRole,
        scope: ApiKeyScope,
    ) -> KnowledgeBase:
        """Return the KB if the principal has at least ``role`` on it, else 404.

        A missing KB and an unauthorized KB both return 404 to avoid enumeration.
        """

        kb = await self._kbs.get(kb_id)
        if kb is None:
            raise NotFoundError("knowledge base not found")
        if not principal.has_scope(scope) or not principal.key_allows_kb(kb_id):
            raise NotFoundError("knowledge base not found")

        if principal.is_admin:
            return kb
        if kb.owner_id == principal.user_id:
            return kb
        membership = await self._kbs.get_membership(kb_id, principal.user_id)
        if membership is None or not membership.role.allows(role):
            raise NotFoundError("knowledge base not found")
        return kb

    async def effective_role(self, kb: KnowledgeBase, principal: Principal) -> KBRole | None:
        if principal.is_admin or kb.owner_id == principal.user_id:
            return KBRole.OWNER
        membership = await self._kbs.get_membership(kb.id, principal.user_id)
        return membership.role if membership else None
