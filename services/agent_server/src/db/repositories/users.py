"""User repository."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..models import User
from .base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Repository for user persistence."""

    model = User

    async def upsert_from_identity(
        self,
        data: Mapping[str, Any],
        *,
        commit: bool = True,
    ) -> User:
        """Upsert a user from provider identity data.

        Expected keys are concentrated here instead of being spread across API
        handlers: ``id``, ``provider``, ``email``, ``username``.
        """
        insert_stmt = pg_insert(User).values(dict(data))
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[User.id],
            set_={
                "provider": insert_stmt.excluded.provider,
                "email": func.coalesce(insert_stmt.excluded.email, User.email),
                "username": func.coalesce(insert_stmt.excluded.username, User.username),
            },
        ).returning(User)

        result = await self.db.execute(stmt)
        if commit:
            await self.commit()
        else:
            await self.flush()
        return result.scalar_one()
