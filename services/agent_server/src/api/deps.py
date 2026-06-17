"""Composed FastAPI dependencies for the HTTP API."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.provider import AuthContext

from ..auth import AuthenticatedUser, get_current_user_from_token
from ..db import User, get_db
from ..db.services import UserService


async def get_current_user(
    auth_context: AuthContext = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the authenticated user and guarantee a local DB row exists.

    Runs the Just-In-Time upsert so every downstream conversation/message write can
    safely reference ``users.id``.
    """
    return await UserService(db).sync_authenticated_user(auth_context)
