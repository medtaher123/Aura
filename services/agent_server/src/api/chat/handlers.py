"""New chat and resume chat share one ``ChatTurn.run()``.

``ChatTurn`` — run the graph, then pause or send the final answer.
``NewChat``  — client sent a new message.
``ResumeChat`` — client answered a question the agent asked.
"""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from src.api.chat.language import to_english
from src.api.chat.pause_state import ConversationPauseState
from src.api.chat.stream_bridge import stream_bridge
from src.api.websocket_connection import WebSocketConnection
from src.core.logger import get_logger
from src.db import ConversationService, User
from src.db.models.message import (
    AssistantMessage,
    InputResponseMessage,
    Message,
    UserMessage,
)
from src.schemas.websocket import AgentStage
from src.services.graph_runner import GraphTurnResult, get_graph_runner_service
from src.services.graph_runner.models import (
    GraphResumeRequest,
    GraphRunnerRequest,
    GraphTurnRequest,
)
from src.services.graph_runner.service import GraphRunnerService
from src.services.translate_service import translate_from_english
from src.user_inputs import UserInputRouter

logger = get_logger("chat_turn")


class ChatTurn(ABC):
    """One graph run for a conversation. Subclasses only differ in ``start()``."""

    kind: ClassVar[str] = "chat"

    def __init__(
        self,
        conn: WebSocketConnection,
        user: User,
        conversations: ConversationService,
        *,
        graph_runner: GraphRunnerService | None = None,
    ) -> None:
        self.conn = conn
        self.user = user
        self.conversations = conversations
        self.graph_runner = graph_runner or get_graph_runner_service()

        self.conversation_id: uuid.UUID | None = None
        self.graph_request: GraphRunnerRequest | None = None
        self.language = "en"
        self.status_text = "Processing your request..."
        self.user_query = ""
        self.needs_title = False
        self.messages_to_save: list[Message] = []
        self.clear_pause_when_done = False
        self.user_message_already_saved = False

    async def run(self) -> None:
        try:
            if not await self.start():
                return
            result = await self.run_graph()
            await self.after_graph(result)
        except Exception as exc:
            logger.exception("Error running %s", self.kind)
            await self.conn.send_error(str(exc), recoverable=True)

    @abstractmethod
    async def start(self) -> bool:
        """Fill conversation_id and graph_request. Return False after sending an error."""

    async def run_graph(self) -> GraphTurnResult:
        assert self.graph_request is not None
        await self.conn.send_status(AgentStage.PLANNING, self.status_text)
        self.conn.begin_streaming_response()
        with stream_bridge(self.conn) as emitter:
            request = self.graph_request.with_stream_emitter(emitter)
            # Must await on the FastAPI loop — AsyncPostgresSaver locks are
            # bound to the loop that called init_checkpointer().
            return await self.graph_runner.execute(request)

    async def after_graph(self, result: GraphTurnResult) -> None:
        if self.conn.is_closed or self.conversation_id is None:
            return
        if self.conn.is_cancelled():
            await self.conn.send_complete(
                response="Request cancelled.",
                conversation_id=self.conversation_id,
                error=False,
            )
            return
        if result.pending_input_requests():
            await self.ask_user_for_input(result)
            return
        await self.send_final_answer(result)

    async def ask_user_for_input(self, result: GraphTurnResult) -> None:
        assert self.conversation_id is not None
        pause = ConversationPauseState.from_turn(
            result,
            conversation_id=str(self.conversation_id),
            detected_lang=self.language,
            title_user_message=self.user_query,
            conversation_title_pending=self.needs_title,
            user_message_persisted=self.user_message_already_saved,
            needs_input=UserInputRouter.requests_to_dict(result.pending_input_requests()),
        )
        history = list(self.messages_to_save)
        if history:
            pause.user_message_persisted = True
        pending = result.pending_input_requests()
        if pending:
            history.append(UserInputRouter.to_request_message(pending))
        if history:
            await self.conversations.append_messages(
                self.user, self.conversation_id, history, commit=False
            )
        logger.info("User input required - kinds=%s", list(pause.needs_input.keys()))
        await self.conversations.set_pause_state(
            self.user, self.conversation_id, pause.to_storage()
        )
        await self.conn.send_user_input_request(
            pause.needs_input,
            {"conversation_id": str(self.conversation_id)},
        )

    async def send_final_answer(self, result: GraphTurnResult) -> None:
        assert self.conversation_id is not None
        response = await asyncio.to_thread(
            translate_from_english, result.message, self.language
        )
        if self.clear_pause_when_done:
            await self.conversations.clear_pause_state(self.user, self.conversation_id)
        await self.conversations.append_messages(
            self.user,
            self.conversation_id,
            [
                *self.messages_to_save,
                *result.tool_messages,
                AssistantMessage.create(
                    result.message, metadata=result.assistant_metadata()
                ),
            ],
        )
        if self.needs_title:
            await self.send_title(result)
        logger.info(
            "Chat turn completed - error=%s maps=%d urls=%d",
            result.error,
            len(result.artifacts.maps),
            len(result.artifacts.urls),
        )
        await self.conn.send_complete(
            response=response,
            conversation_id=self.conversation_id,
            artifacts=result.artifacts,
            error=result.error,
        )

    async def send_title(self, result: GraphTurnResult) -> None:
        assert self.conversation_id is not None
        try:
            title = await asyncio.to_thread(
                self.conversations.generate_title, self.user_query, result.message
            )
            conversation = await self.conversations.update_title(
                self.user, self.conversation_id, title
            )
            if conversation is None:
                logger.warning(
                    "Skipped title event; conversation not found: %s",
                    self.conversation_id,
                )
                return
            await self.conn.send_conversation_title(conversation.id, conversation.title)
        except Exception as exc:
            logger.warning(
                "Conversation title generation failed for %s: %s: %s",
                self.conversation_id,
                type(exc).__name__,
                exc,
            )


class NewChat(ChatTurn):
    """Client sent a new message (websocket type ``chat_request``)."""

    kind = "new chat"

    def __init__(
        self,
        conn: WebSocketConnection,
        user: User,
        conversations: ConversationService,
        user_message: UserMessage,
        *,
        conversation_id: uuid.UUID | None = None,
        language: str | None = None,
        graph_runner: GraphRunnerService | None = None,
    ) -> None:
        super().__init__(conn, user, conversations, graph_runner=graph_runner)
        self.user_message = user_message
        self.incoming_conversation_id = conversation_id
        self.incoming_language = language

    async def start(self) -> bool:
        context = await self.conversations.get_or_create_conversation_with_messages(
            self.user,
            self.incoming_conversation_id,
            visible_to_ui=None,
            visible_to_agent=True,
        )
        if context is None:
            await self.conn.send_error("Conversation not found", recoverable=True)
            return False

        self.conversation_id = context.conversation.id
        logger.info(
            "Chat request received - len=%d conversation_id=%s new=%s history=%d attachments=%s",
            len(self.user_message.content or ""),
            self.conversation_id,
            context.created,
            len(context.messages),
            [a.type for a in self.user_message.attachments],
        )
        english, language = await asyncio.to_thread(
            to_english, self.user_message.content, self.incoming_language
        )
        self.user_message.content = english
        self.language = language
        self.user_query = english
        self.needs_title = context.created
        self.messages_to_save = [self.user_message]
        self.status_text = "Processing your request..."
        turn_id = str(uuid.uuid4())
        thread_id = f"{self.conversation_id}:{turn_id}"
        self.graph_request = GraphTurnRequest(
            thread_id=thread_id,
            message=self.user_message,
            user_id=str(self.user.id),
            session_id=str(self.conversation_id),
            chat_history=list(context.messages),
        )
        return True


class ResumeChat(ChatTurn):
    """Client answered a question (websocket type ``chat_resume``)."""

    kind = "resume chat"

    def __init__(
        self,
        conn: WebSocketConnection,
        user: User,
        conversations: ConversationService,
        input_message: InputResponseMessage,
        *,
        conversation_id: uuid.UUID,
        graph_runner: GraphRunnerService | None = None,
    ) -> None:
        super().__init__(conn, user, conversations, graph_runner=graph_runner)
        self.input_message = input_message
        self.conversation_id = conversation_id
        self.clear_pause_when_done = True
        self.status_text = "Resuming with provided user input..."

    async def start(self) -> bool:
        logger.info(
            "Chat resume received - attachments=%s conversation_id=%s",
            [a.type for a in self.input_message.attachments],
            self.conversation_id,
        )
        found = await self.conversations.get_conversation_with_messages(
            self.user,
            self.conversation_id,
            visible_to_ui=None,
            visible_to_agent=True,
        )
        if found is None:
            await self.conn.send_error("Conversation not found", recoverable=True)
            return False
        pause = await self._pause_from_conversation(found.conversation.pause_state)
        if pause is None:
            return False
        leftover = pause.unpersisted_user_message()
        self.language = pause.detected_lang
        self.user_query = pause.title_user_message
        self.needs_title = pause.conversation_title_pending
        self.user_message_already_saved = pause.user_message_persisted
        self.messages_to_save = [leftover] if leftover else []
        self.messages_to_save.append(self.input_message)
        if not pause.checkpoint_thread_id:
            await self.conn.send_error(
                "No checkpoint thread to resume for this conversation.",
                recoverable=True,
            )
            return False
        self.graph_request = GraphResumeRequest(
            thread_id=pause.checkpoint_thread_id,
            message=self.input_message,
            chat_history=list(found.messages),
            hitl_blobs=dict(pause.hitl_blobs),
        )
        return True

    async def _pause_from_conversation(
        self, raw_pause: dict[str, Any] | None
    ) -> ConversationPauseState | None:
        pause = ConversationPauseState.from_storage(raw_pause)
        if pause is None:
            logger.warning(
                "Resume requested but no paused state for conversation %s",
                self.conversation_id,
            )
            await self.conn.send_error(
                "No paused request to resume for this conversation.",
                recoverable=True,
            )
            return None
        if not pause.checkpoint_thread_id:
            logger.warning(
                "Resume requested but no checkpoint_thread_id for conversation %s",
                self.conversation_id,
            )
            await self.conn.send_error(
                "No paused request to resume for this conversation.",
                recoverable=True,
            )
            return None
        return pause


async def handle_chat_request(
    conn: WebSocketConnection,
    user_message: UserMessage,
    user: User,
    conversations: ConversationService,
    *,
    conversation_id: uuid.UUID | None = None,
    language: str | None = None,
) -> None:
    await NewChat(
        conn,
        user,
        conversations,
        user_message,
        conversation_id=conversation_id,
        language=language,
    ).run()


async def handle_chat_resume(
    conn: WebSocketConnection,
    input_message: InputResponseMessage,
    user: User,
    conversations: ConversationService,
    *,
    conversation_id: uuid.UUID,
) -> None:
    await ResumeChat(
        conn,
        user,
        conversations,
        input_message,
        conversation_id=conversation_id,
    ).run()
