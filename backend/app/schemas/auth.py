"""Auth DTOs (docs/ARCHITECTURE.md §23.1, §25)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.infra.db.models import User


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default="", max_length=120)
    make_admin: bool = False  # honoured only when an admin creates the account


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    """Access token only. The refresh token is delivered as an HttpOnly cookie
    with a CSRF double-submit companion cookie (docs/ARCHITECTURE.md §24.2)."""

    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    is_admin: bool
    is_active: bool
    created_at: datetime

    @classmethod
    def from_model(cls, user: User) -> UserResponse:
        return cls(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            is_admin=user.is_admin,
            is_active=user.is_active,
            created_at=user.created_at,
        )
