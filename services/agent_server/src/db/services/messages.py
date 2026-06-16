"""Message service."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Message, User
from ..repositories import MessageRepository
from .sessions import SessionService


class MessageService:
    """Business operations for messages."""

    def __init__(self, db: AsyncSession):
        self.messages = MessageRepository(db)
        self.sessions = SessionService(db)

    async def create_message(
        self,
        user: User,
        session_id: uuid.UUID,
        data: dict,
        *,
        commit: bool = True,
    ) -> Optional[Message]:
        """Create a message if the session belongs to ``user``."""
        session = await self.sessions.get_session(user, session_id)
        if session is None:
            return None
        return await self.messages.create_for_session(
            session_id, data, commit=commit
        )

    async def list_messages(
        self,
        user: User,
        session_id: uuid.UUID,
    ) -> Optional[list[Message]]:
        """List messages if the session belongs to ``user``."""
        session = await self.sessions.get_session(user, session_id)
        if session is None:
            return None
        return await self.messages.list_for_session(session_id)
