"""Password hashing, JWT, API-key primitives (docs/ARCHITECTURE.md §25, §29)."""

from __future__ import annotations

import time

import pytest

from app.core.security import (
    API_KEY_PREFIX,
    TokenError,
    create_jwt,
    decode_jwt,
    generate_api_key,
    hash_password,
    verify_api_key,
    verify_password,
)

_SECRET = "unit-test-secret-value-at-least-32-characters"


def test_password_hash_roundtrip() -> None:
    h = hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong", h)


def test_verify_password_tolerates_garbage_hash() -> None:
    assert verify_password("x", "not-a-real-hash") is False


def test_api_key_generation_and_verification() -> None:
    generated = generate_api_key()
    assert generated.token.startswith(API_KEY_PREFIX)
    assert generated.prefix == generated.token[:12]
    assert verify_api_key(generated.token, generated.key_hash)
    assert not verify_api_key(generated.token + "x", generated.key_hash)


def test_jwt_roundtrip_and_type_check() -> None:
    token = create_jwt("user-1", token_type="access", secret=_SECRET, ttl_seconds=60)
    payload = decode_jwt(token, secret=_SECRET, expected_type="access")
    assert payload["sub"] == "user-1"

    with pytest.raises(TokenError, match="expected a refresh token"):
        decode_jwt(token, secret=_SECRET, expected_type="refresh")


def test_jwt_expiry() -> None:
    token = create_jwt("user-1", token_type="access", secret=_SECRET, ttl_seconds=-1)
    time.sleep(0.01)
    with pytest.raises(TokenError, match="expired"):
        decode_jwt(token, secret=_SECRET, expected_type="access")


def test_jwt_rejects_wrong_secret() -> None:
    token = create_jwt("user-1", token_type="access", secret=_SECRET, ttl_seconds=60)
    other = "a-different-secret-value-thirty-two-chars"
    with pytest.raises(TokenError):
        decode_jwt(token, secret=other, expected_type="access")
