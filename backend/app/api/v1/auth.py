"""Authentication endpoints (docs/ARCHITECTURE.md §23.1, §24.2, §25).

Token model:
  * access token  — returned in the JSON body, held in memory by the client.
  * refresh token — set as an ``HttpOnly`` cookie scoped to ``/api/v1/auth``;
    never in the response body, never readable by JavaScript.
  * CSRF token    — a random value set as a non-``HttpOnly`` companion cookie;
    the client echoes it in the ``X-CSRF-Token`` header on the cookie-authenticated
    state-changing calls (``/auth/refresh``, ``/auth/logout``). Double-submit.
"""

from __future__ import annotations

import secrets
from typing import Literal, cast

from fastapi import APIRouter, Request, Response

from app.api.context import current_request_id
from app.api.deps import (
    AuthServiceDep,
    OptionalPrincipalDep,
    PrincipalDep,
    SessionDep,
    SettingsDep,
)
from app.config import AuthMode, Settings
from app.core.errors import ForbiddenError
from app.infra.db.repositories.users import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.services.auth import TokenPair

router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE_PATH = "/api/v1/auth"


def _set_session_cookies(response: Response, settings: Settings, pair: TokenPair) -> None:
    csrf = secrets.token_urlsafe(32)
    max_age = settings.jwt_refresh_ttl_days * 86400
    samesite = cast("Literal['lax', 'strict', 'none']", settings.session_cookie_samesite)
    response.set_cookie(
        settings.session_cookie_name,
        pair.refresh_token,
        max_age=max_age,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=samesite,
        domain=settings.session_cookie_domain,
        path=_REFRESH_COOKIE_PATH,
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf,
        max_age=max_age,
        httponly=False,  # the SPA must read this to echo it in the header
        secure=settings.session_cookie_secure,
        samesite=samesite,
        domain=settings.session_cookie_domain,
        path="/",
    )


def _clear_session_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.session_cookie_name,
        path=_REFRESH_COOKIE_PATH,
        domain=settings.session_cookie_domain,
    )
    response.delete_cookie(
        settings.csrf_cookie_name, path="/", domain=settings.session_cookie_domain
    )


def _require_csrf(request: Request, settings: Settings) -> None:
    cookie = request.cookies.get(settings.csrf_cookie_name)
    header = request.headers.get(settings.csrf_header_name)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise ForbiddenError("CSRF token missing or invalid")


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    body: RegisterRequest,
    auth: AuthServiceDep,
    settings: SettingsDep,
    actor: OptionalPrincipalDep,
) -> UserResponse:
    if settings.auth_mode is AuthMode.SINGLE_USER:
        raise ForbiddenError("registration is disabled in single-user mode")
    user = await auth.register(
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        actor=actor,
        make_admin=body.make_admin,
    )
    return UserResponse.from_model(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, response: Response, settings: SettingsDep, auth: AuthServiceDep
) -> TokenResponse:
    user = await auth.authenticate(
        email=body.email, password=body.password, request_id=current_request_id()
    )
    pair = auth.issue_tokens(user)
    _set_session_cookies(response, settings, pair)
    return TokenResponse(access_token=pair.access_token, token_type=pair.token_type)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request, response: Response, settings: SettingsDep, auth: AuthServiceDep
) -> TokenResponse:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise ForbiddenError("no session cookie")
    _require_csrf(request, settings)
    pair = await auth.refresh(token)
    _set_session_cookies(response, settings, pair)  # rotate refresh + CSRF
    return TokenResponse(access_token=pair.access_token, token_type=pair.token_type)


@router.post("/logout", status_code=204)
async def logout(request: Request, settings: SettingsDep) -> Response:
    # A missing/expired session is a successful logout; only reject a present
    # session cookie without a matching CSRF token (forged cross-site logout).
    if request.cookies.get(settings.session_cookie_name):
        _require_csrf(request, settings)
    resp = Response(status_code=204)
    _clear_session_cookies(resp, settings)
    return resp


@router.get("/me", response_model=UserResponse)
async def me(principal: PrincipalDep, session: SessionDep) -> UserResponse:
    user = await UserRepository(session).get(principal.user_id)
    assert user is not None
    return UserResponse.from_model(user)
