"""LangGraph checkpointer factory and lifecycle."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from src.config import get_config
from src.core.logger import get_logger

logger = get_logger("graph_checkpointer")

_checkpointer: BaseCheckpointSaver | None = None
_checkpointer_cm: Any | None = None


def postgres_conn_string(database_url: str) -> str:
    """Convert SQLAlchemy async URL to psycopg-compatible form."""
    url = database_url.strip()
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def resolve_checkpointer_backend(database_url: str, override: str | None = None) -> str:
    if override and override.strip():
        return override.strip().lower()
    if database_url.startswith("postgresql") or database_url.startswith("postgres"):
        return "postgres"
    return "memory"


async def init_checkpointer() -> BaseCheckpointSaver:
    """Initialize and store the process-wide graph checkpointer."""
    global _checkpointer, _checkpointer_cm

    if _checkpointer is not None:
        return _checkpointer

    config = get_config()
    backend = resolve_checkpointer_backend(
        config.database_url, config.checkpointer_backend
    )

    if backend == "postgres":
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        conn = postgres_conn_string(config.database_url)
        _checkpointer_cm = AsyncPostgresSaver.from_conn_string(conn)
        _checkpointer = await _checkpointer_cm.__aenter__()
        await _checkpointer.setup()
        logger.info("LangGraph checkpointer initialized (postgres)")
        return _checkpointer

    _checkpointer = MemorySaver()
    logger.info("LangGraph checkpointer initialized (memory)")
    return _checkpointer


async def shutdown_checkpointer() -> None:
    """Release checkpointer resources on app shutdown."""
    global _checkpointer, _checkpointer_cm

    if _checkpointer_cm is not None:
        await _checkpointer_cm.__aexit__(None, None, None)
        _checkpointer_cm = None
    _checkpointer = None


def get_checkpointer() -> BaseCheckpointSaver:
    if _checkpointer is None:
        raise RuntimeError("Graph checkpointer is not initialized")
    return _checkpointer


@asynccontextmanager
async def checkpointer_lifecycle() -> AsyncIterator[BaseCheckpointSaver]:
    try:
        yield await init_checkpointer()
    finally:
        await shutdown_checkpointer()
