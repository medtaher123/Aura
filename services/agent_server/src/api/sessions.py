"""Chat session and message HTTP endpoints.

Every query is scoped to the authenticated user (``users.id``) to prevent
cross-user data access. The authenticated user is upserted Just-In-Time via
:func:`get_current_db_user`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import User, get_db
from ..db.services import MessageService, SessionService
from ..schemas import (
    MessageCreate,
    MessageRead,
    SessionCreate,
    SessionRead,
    SessionWithMessages,
)
from .deps import get_current_user

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionRead:
    """Initialize a new chat session for the authenticated user."""
    session = await SessionService(db).create_session(
        user,
        payload.model_dump(exclude_none=True),
    )
    return SessionRead.from_model(session)


@router.get("", response_model=list[SessionRead])
async def list_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SessionRead]:
    """List the authenticated user's sessions (newest first)."""
    sessions = await SessionService(db).list_sessions(user)
    return [SessionRead.from_model(session) for session in sessions]


@router.get("/{session_id}", response_model=SessionWithMessages)
async def get_session(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionWithMessages:
    """Fetch a single session (with messages), scoped to the current user."""
    result = await SessionService(db).get_session_with_messages(user, session_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    return SessionWithMessages.from_domain(result)


@router.post(
    "/{session_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_message(
    session_id: uuid.UUID,
    payload: MessageCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageRead:
    """Save a chat message. Verifies session ownership before writing.

    ``payload.metadata`` may be an arbitrary nested dictionary (e.g.
    ``{"tool_name": "calculator", "output": {"result": 42}}``) and is persisted
    to the JSONB ``metadata`` column.
    """
    message = await MessageService(db).create_message(
        user,
        session_id,
        payload.model_dump(),
    )
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    return MessageRead.from_model(message)


@router.get("/{session_id}/messages", response_model=list[MessageRead])
async def list_messages(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MessageRead]:
    """List messages in a session, scoped to the current user."""
    messages = await MessageService(db).list_messages(user, session_id)
    if messages is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    return [MessageRead.from_model(message) for message in messages]
