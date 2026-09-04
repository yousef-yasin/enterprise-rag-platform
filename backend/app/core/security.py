"""Password hashing, JWT, API-key primitives (docs/ARCHITECTURE.md §25, §29).

Pure functions over the standard library + argon2 + PyJWT. No DB, no settings import
beyond the values passed in.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()

API_KEY_PREFIX = "rag_"
_JWT_ALG = "HS256"


class TokenError(Exception):
    """A JWT is missing, malformed, expired or has the wrong type."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:  # malformed hash
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@dataclass(frozen=True, slots=True)
class GeneratedApiKey:
    """A freshly minted API key. ``token`` is shown to the user exactly once."""

    token: str
    prefix: str
    key_hash: str


def generate_api_key() -> GeneratedApiKey:
    body = secrets.token_urlsafe(32)
    token = f"{API_KEY_PREFIX}{body}"
    prefix = token[:12]
    return GeneratedApiKey(token=token, prefix=prefix, key_hash=hash_api_key(token))


def hash_api_key(token: str) -> str:
    """SHA-256 of the token. API keys are high-entropy, so a fast hash + constant-time
    compare is appropriate (and lets us look up by prefix, then verify)."""

    return hashlib.sha256(token.encode()).hexdigest()


def verify_api_key(token: str, key_hash: str) -> bool:
    return secrets.compare_digest(hash_api_key(token), key_hash)


TokenType = Literal["access", "refresh"]


def create_jwt(
    subject: str,
    *,
    token_type: TokenType,
    secret: str,
    ttl_seconds: int,
    extra: dict[str, Any] | None = None,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret, algorithm=_JWT_ALG)


def decode_jwt(token: str, *, secret: str, expected_type: TokenType) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(token, secret, algorithms=[_JWT_ALG])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("invalid token") from exc
    if payload.get("type") != expected_type:
        raise TokenError(f"expected a {expected_type} token")
    if "sub" not in payload:
        raise TokenError("token missing subject")
    return payload
