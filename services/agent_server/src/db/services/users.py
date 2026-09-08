"""User service."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_auth_provider
from src.auth.provider import AuthContext
from src.auth.router import AuthRouter

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
        auth_context: AuthContext,
        *,
        commit: bool = True,
    ) -> User:
        """Just-In-Time upsert for the authenticated identity."""
        
        existing_user = await self.users.get(auth_context.user.user_id)
        
        if existing_user:
            return existing_user

        user_info = await auth_context.provider.fetch_user_info(auth_context.user.access_token)
        
        data = {
            "id": auth_context.user.user_id,
            "provider": auth_context.provider.name,
            "email": user_info.email,
            "username": user_info.username,
        }
        
        return await self.users.upsert_from_identity(data, commit=commit)
