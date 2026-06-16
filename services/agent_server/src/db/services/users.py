"""User service."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...auth import AuthenticatedUser
from ...config import get_config
from ..models import User
from ..repositories import UserRepository


class UserService:
    """Business operations for users."""

    def __init__(self, db: AsyncSession):
        self.users = UserRepository(db)

    async def sync_authenticated_user(
        self,
        auth_user: AuthenticatedUser,
        *,
        commit: bool = True,
    ) -> User:
        """Just-In-Time upsert for the authenticated identity."""
        data = {
            "id": auth_user.user_id,
            "provider": get_config().auth_provider,
            "email": auth_user.email,
            "username": auth_user.username,
        }
        return await self.users.upsert_from_identity(data, commit=commit)
