"""Chat turn handlers: new request and resume-after-user-input."""

from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from src.api.chat.language import to_english
from src.api.chat.pause_state import ConversationPauseState
from src.api.chat.stream_bridge import stream_bridge
from src.api.websocket_connection import WebSocketConnection
from src.db import ConversationService, User
from src.db.models.message import AssistantMessage, Message, UserMessage
from src.user_inputs import UserInputRouter
from src.schemas.websocket import AgentStage, ChatRequestMessage, ChatResumeMessage
from src.services import graph_runner
from src.services.graph_runner import GraphTurnResult
from src.services.translate_service import translate_from_english
from src.core.logger import get_logger

logger = get_logger("chat_turn")


def _assistant_metadata(turn: GraphTurnResult) -> dict[str, Any]:
    return {
        "artifacts": turn.artifacts.model_dump(mode="json"),
        "error": bool(turn.error),
    }


async def _run_graph_in_thread(fn: Callable[[], GraphTurnResult]) -> GraphTurnResult:
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return await loop.run_in_executor(pool, fn)


async def _generate_and_send_title(
    *,
    conn: WebSocketConnection,
    conversations: ConversationService,
    user: User,
    conversation_id: uuid.UUID,
    user_message: str,
    assistant_message: str,
) -> None:
    try:
        title = await asyncio.to_thread(
            conversations.generate_title, user_message, assistant_message
        )
        conversation = await conversations.update_title(user, conversation_id, title)
        if conversation is None:
            logger.warning(
                "Skipped title event; conversation not found: %s", conversation_id
            )
            return
        await conn.send_conversation_title(conversation.id, conversation.title)
    except Exception as exc:
        logger.warning(
            "Conversation title generation failed for %s: %s: %s",
            conversation_id,
            type(exc).__name__,
            exc,
        )


async def _send_user_input_pause(
    *,
    conn: WebSocketConnection,
    conversations: ConversationService,
    user: User,
    conversation_id: uuid.UUID,
    turn: GraphTurnResult,
    detected_lang: str,
    title_user_message: str,
    conversation_title_pending: bool = False,
    user_message_persisted: bool = False,
) -> None:
    pending = turn.pending_input_requests()
    needs_input = UserInputRouter.requests_to_dict(pending)
    pause = ConversationPauseState.from_turn(
        turn,
        conversation_id=str(conversation_id),
        detected_lang=detected_lang,
        title_user_message=title_user_message,
        conversation_title_pending=conversation_title_pending,
        user_message_persisted=user_message_persisted,
        needs_input=needs_input,
    )

    history_messages: list[Message] = []
    if not pause.user_message_persisted and title_user_message:
        history_messages.append(UserMessage.create(title_user_message))
        pause.user_message_persisted = True
    if pending:
        history_messages.append(UserInputRouter.to_request_message(pending))
    if history_messages:
        await conversations.append_messages(
            user, conversation_id, history_messages, commit=False
        )

    logger.info("User input required - kinds=%s", list(needs_input.keys()))
    await conversations.set_pause_state(user, conversation_id, pause.to_storage())
    # Wire field is still named pause_state; payload is only a conversation ref.
    await conn.send_user_input_request(
        needs_input,
        {"conversation_id": str(conversation_id)},
    )


async def _finalize_completed_turn(
    *,
    conn: WebSocketConnection,
    conversations: ConversationService,
    user: User,
    conversation_id: uuid.UUID,
    turn: GraphTurnResult,
    detected_lang: str,
    title_user_message: str,
    conversation_title_pending: bool,
    history_messages: list[Message],
    clear_pause: bool,
) -> None:
    """Shared completion path for a finished (non-paused) graph turn."""
    response_message = await asyncio.to_thread(
        translate_from_english, turn.message, detected_lang
    )

    if clear_pause:
        await conversations.clear_pause_state(user, conversation_id)

    if history_messages:
        await conversations.append_messages(user, conversation_id, history_messages)

    if conversation_title_pending:
        await _generate_and_send_title(
            conn=conn,
            conversations=conversations,
            user=user,
            conversation_id=conversation_id,
            user_message=title_user_message,
            assistant_message=turn.message,
        )

    logger.info(
        "Chat turn completed - error=%s maps=%d urls=%d",
        turn.error,
        len(turn.artifacts.maps),
        len(turn.artifacts.urls),
    )
    await conn.send_complete(
        response=response_message,
        conversation_id=conversation_id,
        artifacts=turn.artifacts,
        error=turn.error,
    )


async def handle_chat_request(
    conn: WebSocketConnection,
    message: ChatRequestMessage,
    user: User,
    conversations: ConversationService,
) -> None:
    """Handle a new chat_request from the client."""
    try:
        context = await conversations.get_or_create_conversation_with_messages(
            user, message.conversation_id
        )
        if context is None:
            await conn.send_error("Conversation not found", recoverable=True)
            return

        conversation_id = context.conversation.id
        logger.info(
            "Chat request received - len=%d conversation_id=%s new=%s history=%d user_inputs=%s",
            len(message.message),
            conversation_id,
            context.created,
            len(context.messages),
            list((message.user_inputs or {}).keys()),
        )

        await conn.send_status(AgentStage.PLANNING, "Processing your request...")
        conn.begin_streaming_response()

        english_message, detected_lang = await asyncio.to_thread(
            to_english, message.message, message.language
        )
        user_turn_message = UserMessage.create(
            english_message,
            user_inputs=dict(message.user_inputs or {}) or None,
        )
        english_query = user_turn_message.rendered_content
        chat_history = [m for m in context.messages if m.has_content]

        with stream_bridge(conn) as stream_emitter:
            def run_turn(emitter=stream_emitter) -> GraphTurnResult:
                return graph_runner.run_graph_turn(
                    message=user_turn_message,
                    user_id=str(user.id),
                    session_id=str(conversation_id),
                    chat_history=chat_history,
                    stream_emitter=emitter,
                )

            turn = await _run_graph_in_thread(run_turn)

        if conn.is_closed:
            return

        if conn.is_cancelled():
            await conn.send_complete(
                response="Request cancelled.",
                conversation_id=conversation_id,
                error=False,
            )
            return

        if turn.pending_input_requests():
            await conversations.append_messages(
                user,
                conversation_id,
                [user_turn_message],
                commit=False,
            )
            await _send_user_input_pause(
                conn=conn,
                conversations=conversations,
                user=user,
                conversation_id=conversation_id,
                turn=turn,
                detected_lang=detected_lang,
                title_user_message=english_query,
                conversation_title_pending=context.created,
                user_message_persisted=True,
            )
            return

        await _finalize_completed_turn(
            conn=conn,
            conversations=conversations,
            user=user,
            conversation_id=conversation_id,
            turn=turn,
            detected_lang=detected_lang,
            title_user_message=english_query,
            conversation_title_pending=context.created,
            history_messages=[
                user_turn_message,
                AssistantMessage.create(
                    turn.message, metadata=_assistant_metadata(turn)
                ),
            ],
            clear_pause=False,
        )

    except Exception as exc:
        logger.exception("Error handling chat request")
        await conn.send_error(str(exc), recoverable=True)


async def handle_chat_resume(
    conn: WebSocketConnection,
    message: ChatResumeMessage,
    user: User,
    conversations: ConversationService,
) -> None:
    """Handle chat_resume after the client answered required user inputs."""
    try:
        parsed_inputs = UserInputRouter.results_from_dict(message.user_inputs)
        conversation_id = message.conversation_id
        logger.info(
            "Chat resume received - kinds=%s conversation_id=%s",
            list(parsed_inputs.keys()),
            conversation_id,
        )

        conversation = await conversations.get_conversation(user, conversation_id)
        if conversation is None:
            await conn.send_error("Conversation not found", recoverable=True)
            return

        pause = ConversationPauseState.from_storage(conversation.pause_state)
        if pause is None:
            logger.warning(
                "Resume requested but no paused state for conversation %s",
                conversation_id,
            )
            await conn.send_error(
                "No paused request to resume for this conversation.",
                recoverable=True,
            )
            return

        if not pause.graph_state:
            logger.warning(
                "Resume requested but no graph_state for conversation %s",
                conversation_id,
            )
            await conn.send_error(
                "No paused graph state to resume for this conversation.",
                recoverable=True,
            )
            return

        if parsed_inputs:
            await conversations.append_messages(
                user,
                conversation_id,
                [UserInputRouter.to_response_message(parsed_inputs)],
            )

        await conn.send_status(
            AgentStage.PLANNING, "Resuming with provided user input..."
        )
        conn.begin_streaming_response()

        user_inputs_payload = {
            kind: model.model_dump(mode="python") for kind, model in parsed_inputs.items()
        }
        graph_state = pause.graph_state

        with stream_bridge(conn) as stream_emitter:
            def run_resume(emitter=stream_emitter) -> GraphTurnResult:
                return graph_runner.resume_graph_turn(
                    graph_state=graph_state,
                    user_inputs=user_inputs_payload,
                    stream_emitter=emitter,
                )

            turn = await _run_graph_in_thread(run_resume)

        if conn.is_closed:
            return

        if conn.is_cancelled():
            await conn.send_complete(
                response="Request cancelled.",
                conversation_id=conversation_id,
                error=False,
            )
            return

        if turn.pending_input_requests():
            await _send_user_input_pause(
                conn=conn,
                conversations=conversations,
                user=user,
                conversation_id=conversation_id,
                turn=turn,
                detected_lang=pause.detected_lang,
                title_user_message=pause.title_user_message,
                conversation_title_pending=pause.conversation_title_pending,
                user_message_persisted=pause.user_message_persisted,
            )
            return

        history_messages: list[Message] = []
        if not pause.user_message_persisted and pause.resume_user_text:
            history_messages.append(UserMessage.create(pause.resume_user_text))
        history_messages.append(
            AssistantMessage.create(turn.message, metadata=_assistant_metadata(turn))
        )

        await _finalize_completed_turn(
            conn=conn,
            conversations=conversations,
            user=user,
            conversation_id=conversation_id,
            turn=turn,
            detected_lang=pause.detected_lang,
            title_user_message=pause.title_user_message,
            conversation_title_pending=pause.conversation_title_pending,
            history_messages=history_messages,
            clear_pause=True,
        )

    except Exception as exc:
        logger.exception("Error handling chat resume")
        await conn.send_error(str(exc), recoverable=True)
