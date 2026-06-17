"""Chat conversation and message HTTP endpoints.

Every query is scoped to the authenticated user (``users.id``) to prevent
cross-user data access. The authenticated user is upserted Just-In-Time via
:func:`get_current_db_user`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import User, get_db
from ..db.services import MessageService, ConversationService
from ..schemas import (
    MessageCreate,
    MessageRead,
    ConversationCreate,
    ConversationRead,
    ConversationWithMessages,
)
from .deps import get_current_user

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationRead:
    """Initialize a new chat Conversation for the authenticated user."""
    conversation = await ConversationService(db).create_conversation(
        user,
        payload.model_dump(exclude_none=True),
    )
    return ConversationRead.from_model(conversation)


@router.get("", response_model=list[ConversationRead])
async def list_conversations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationRead]:
    """List the authenticated user's conversations (newest first)."""
    conversations = await ConversationService(db).list_conversations(user)
    return [ConversationRead.from_model(conversation) for conversation in conversations]


@router.get("/{conversation_id}", response_model=ConversationWithMessages)
async def get_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationWithMessages:
    """Fetch a single conversation (with messages), scoped to the current user."""
    result = await ConversationService(db).get_conversation_with_messages(user, conversation_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    return ConversationWithMessages.from_domain(result)


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_message(
    conversation_id: uuid.UUID,
    payload: MessageCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageRead:
    """Save a chat message. Verifies conversation ownership before writing.

    ``payload.metadata`` may be an arbitrary nested dictionary (e.g.
    ``{"tool_name": "calculator", "output": {"result": 42}}``) and is persisted
    to the JSONB ``metadata`` column.
    """
    message = await MessageService(db).create_message(
        user,
        conversation_id,
        payload.model_dump(),
    )
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    return MessageRead.from_model(message)


@router.get("/{conversation_id}/messages", response_model=list[MessageRead])
async def list_messages(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MessageRead]:
    """List messages in a conversation, scoped to the current user."""
    messages = await MessageService(db).list_messages(user, conversation_id)
    if messages is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    return [MessageRead.from_model(message) for message in messages]
