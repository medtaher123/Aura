"""Database engine and session management.

Provides the async SQLAlchemy engine, a session factory, and the ``get_db``
FastAPI dependency that yields a session and closes it gracefully.

The connection string is read from the ``DATABASE_URL`` environment variable
(via :class:`AgentServerConfig`). Both the ``postgresql://`` and
``postgresql+asyncpg://`` forms are accepted; the former is normalized to the
async driver so the same value works for Aurora and local Postgres.
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.db import BaseModel

from ..config import get_config
from ..core.logger import get_logger

logger = get_logger("db")


def normalize_async_url(url: str) -> str:
    """Coerce a Postgres URL to the asyncpg driver form.

    Aurora/Secrets Manager often expose a plain ``postgresql://`` URL; the async
    engine requires an explicit ``+asyncpg`` driver.
    """
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


_config = get_config()
DATABASE_URL = normalize_async_url(_config.database_url)

engine = create_async_engine(
    DATABASE_URL,
    echo=_config.database_echo,
    pool_pre_ping=True,
    pool_size=_config.database_pool_size,
    max_overflow=_config.database_max_overflow,
)

async def init_db():
    """Initialize the database and create tables."""
    from src.db.base import BaseModel
    import src.db.models  # noqa: F401  — register mapped tables on metadata

    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session and closes it.

    The session is committed by the caller (endpoint/CRUD) explicitly; on an
    unhandled exception the session is rolled back before being closed.
    """
    session = AsyncSessionLocal()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
