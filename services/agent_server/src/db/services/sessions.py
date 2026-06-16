"""Chat session service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Message, Session, User
from ..repositories import MessageRepository, SessionRepository


@dataclass(frozen=True)
class SessionWithMessagesResult:
    """Domain result for a session and its ordered messages."""

    session: Session
    messages: list[Message]


class SessionService:
    """Business operations for chat sessions."""

    def __init__(self, db: AsyncSession):
        self.sessions = SessionRepository(db)
        self.messages = MessageRepository(db)

    async def create_session(
        self,
        user: User,
        data: dict,
        *,
        commit: bool = True,
    ) -> Session:
        return await self.sessions.create_for_owner(
            self._owner_id(user), data, commit=commit
        )

    async def list_sessions(self, user: User) -> list[Session]:
        return await self.sessions.list_for_owner(self._owner_id(user))

    async def get_session(
        self,
        user: User,
        session_id: uuid.UUID,
    ) -> Optional[Session]:
        return await self.sessions.get_for_owner(session_id, self._owner_id(user))

    async def get_session_with_messages(
        self,
        user: User,
        session_id: uuid.UUID,
    ) -> Optional[SessionWithMessagesResult]:
        session = await self.get_session(user, session_id)
        if session is None:
            return None
        messages = await self.messages.list_for_session(session_id)
        return SessionWithMessagesResult(session=session, messages=messages)

    @staticmethod
    def _owner_id(user: User) -> str:
        """Concentrate access to the user primary key in one place."""
        return user.id
