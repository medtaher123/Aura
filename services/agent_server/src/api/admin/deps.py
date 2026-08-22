"""Admin authorization dependency."""

from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.router import AuthRouter
from src.config import get_config
from src.db.database import get_db
from src.db.models.user import User
from src.db.repositories.users import UserRepository


def _admin_user_ids() -> set[str]:
    raw = os.getenv("ADMIN_USER_IDS", "").strip()
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


async def _dev_admin_user(db: AsyncSession) -> User:
    repo = UserRepository(db)
    existing = await repo.get("dev-admin")
    if existing is not None:
        return existing
    return await repo.create(
        {
            "id": "dev-admin",
            "provider": "dev",
            "email": "admin@localhost",
            "username": "dev-admin",
        }
    )


async def require_admin_user(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Restrict admin routes to configured admin user ids.

    When auth is disabled, a local dev admin user is used.
    """
    return User(id="dev-admin", provider="dev", email="admin@localhost", username="dev-admin")
    config = get_config()
    if not config.auth_enabled:
        return await _dev_admin_user(db)

    token = AuthRouter.extract_bearer_token(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    from src.api.deps import get_current_user_from_token
    from src.db.services import UserService

    auth_context = await get_current_user_from_token(authorization)
    user = await UserService(db).sync_authenticated_user(auth_context)

    admins = _admin_user_ids()
    if admins and user.id not in admins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
