"""User persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.email == email.strip().lower())
        )
        return result.scalar_one_or_none()

    async def count(self) -> int:
        result = await self._session.execute(select(User))
        return len(result.scalars().all())

    def add(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str,
        is_admin: bool = False,
    ) -> User:
        user = User(
            email=email.strip().lower(),
            password_hash=password_hash,
            display_name=display_name,
            is_admin=is_admin,
            is_active=True,
        )
        self._session.add(user)
        return user
