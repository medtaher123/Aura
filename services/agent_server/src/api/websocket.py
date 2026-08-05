"""
WebSocket Handler for Agent Server

Manages real-time communication with clients for agent orchestration.
"""

import asyncio
import json
import uuid
from typing import Any
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user
from src.api.websocket_connection import WebSocketConnection
from src.db import ConversationService, User, get_db
from src.schemas.websocket import (
    AgentStage,
    ToolArtifacts,
    ChatRequestMessage,
    ChatResumeMessage,
    ClientMessageType,
    LocationResult,
)
from src.schemas.user_inputs import (
    UserInputRouter,
)
from src.db.models.message import (
    AssistantMessage,
    Message,
    UserMessage,
)
from ..auth import AuthConfigurationError, AuthError
from ..core.logger import get_logger
from ..core.websocket_traffic_logger import log_websocket_traffic
from ..core.memory import normalize_chat_messages
from ..services.agent_runner import coerce_tool_response
from ..services import graph_runner
from ..services.translate_service import (
    detect_and_translate_to_english,
    translate_from_english,
)
from src.api.websocket_stream_subscriber import WebSocketStreamSubscriber
from src.core.event_emitter import EventEmitter

logger = get_logger("websocket")
router = APIRouter()


async def _cancel_active_task(task: asyncio.Task[None] | None) -> None:
    """Cancel and drain an in-flight WebSocket handler task."""
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Active WebSocket request task failed during cancellation")


async def _keepalive_during_task(
    conn: WebSocketConnection,
    task: asyncio.Task[None],
    *,
    interval_seconds: float = 25.0,
) -> None:
    """Send lightweight status updates while a long-running handler is active."""
    while not task.done() and not conn.is_closed:
        await asyncio.sleep(interval_seconds)
        if task.done() or conn.is_closed:
            return
        await conn.send_status(AgentStage.PLANNING, "Still working...")


def _spawn_request_task(
    conn: WebSocketConnection,
    coro: Any,
) -> tuple[asyncio.Task[None], asyncio.Task[None]]:
    """Start a request handler and a keepalive companion task."""
    request_task = asyncio.create_task(coro)
    keepalive_task = asyncio.create_task(
        _keepalive_during_task(conn, request_task)
    )

    def _stop_keepalive(done_task: asyncio.Task[None]) -> None:
        if not keepalive_task.done():
            keepalive_task.cancel()

    request_task.add_done_callback(_stop_keepalive)
    return request_task, keepalive_task


def _assistant_message_metadata(tool_response: Any) -> dict[str, Any]:
    """Build the JSONB metadata persisted alongside an assistant message.

    Artifacts (maps, thumbnails, urls) are produced by tools and must be stored
    so a reloaded conversation can re-render them, not just the text content.
    """
    artifacts = getattr(tool_response, "artifacts", None)
    if artifacts is not None and hasattr(artifacts, "model_dump"):
        artifacts_data = artifacts.model_dump(mode="json")
    elif isinstance(artifacts, dict):
        artifacts_data = artifacts
    else:
        artifacts_data = ToolArtifacts().model_dump(mode="json")

    return {
        "artifacts": artifacts_data,
        "error": bool(getattr(tool_response, "error", False)),
    }


async def _generate_update_and_send_conversation_title(
    *,
    conn: WebSocketConnection,
    conversations: ConversationService,
    user: User,
    conversation_id: uuid.UUID,
    user_message: str,
    assistant_message: str,
) -> None:
    """Generate a title for a new conversation and notify the client."""
    try:
        loop = asyncio.get_running_loop()
        title = await loop.run_in_executor(
            None,
            lambda: conversations.generate_title(user_message, assistant_message),
        )
        conversation = await conversations.update_title(user, conversation_id, title)
        if conversation is None:
            logger.warning(
                f"Skipped title event because conversation was not found: {conversation_id}"
            )
            return
        await conn.send_conversation_title(conversation.id, conversation.title)
        logger.info(
            f"Generated conversation title - conversation_id: {conversation.id}, title: {conversation.title}"
        )
    except Exception as e:
        logger.warning(
            f"Conversation title generation failed for {conversation_id}: {type(e).__name__}: {e}"
        )


async def _send_user_input_pause(
    *,
    conn: WebSocketConnection,
    conversations: ConversationService,
    user: User,
    conversation_id: uuid.UUID,
    data: dict[str, Any],
    detected_lang: str,
    title_user_message: str,
    conversation_title_pending: bool = False,
    user_message_persisted: bool = False,
) -> None:
    """Persist pause state and notify the client of required user inputs."""
    pending = UserInputRouter.pending_from_tool_data(data)
    needs_input = UserInputRouter.requests_to_dict(pending)
    pause_state = data.get("pause", {})
    if not isinstance(pause_state, dict):
        pause_state = {}
    # Carry resume_patch / location_query from tool data when present.
    for key in ("resume_patch", "location_query", "tool_input"):
        if key in data and key not in pause_state:
            pause_state[key] = data[key]
    pause_state["detected_lang"] = detected_lang
    pause_state["conversation_id"] = str(conversation_id)
    pause_state["conversation_title_pending"] = conversation_title_pending
    pause_state["title_user_message"] = title_user_message
    pause_state["needs_input"] = needs_input

    history_messages: list[Message] = []
    if not user_message_persisted and title_user_message:
        history_messages.append(UserMessage.create(title_user_message))
        user_message_persisted = True
    if pending:
        history_messages.append(UserInputRouter.to_request_message(pending))
    if history_messages:
        await conversations.append_messages(
            user, conversation_id, history_messages, commit=False
        )
    pause_state["user_message_persisted"] = user_message_persisted

    logger.info(
        f"User input required - kinds={list(needs_input.keys())}"
    )
    await conversations.set_pause_state(user, conversation_id, pause_state)
    await conn.send_user_input_request(
        needs_input,
        {"conversation_id": str(conversation_id)},
    )

async def handle_chat_request(
    conn: WebSocketConnection,
    message: ChatRequestMessage,
    user: User,
    conversations: ConversationService,
) -> None:
    """
    Handle a chat request from the client.

    This is the main entry point for agent orchestration.
    """
    try:
        conversation_context = await conversations.get_or_create_conversation_with_messages(
            user, message.conversation_id
        )
        if conversation_context is None:
            await conn.send_error("Conversation not found", recoverable=True)
            return

        logger.info(
            f"Chat request received - message length: {len(message.message)}, "
            f"conversation_id: {conversation_context.conversation.id}, "
            f"new_conversation: {conversation_context.created}, "
            f"history size: {len(conversation_context.messages)}, "
            f"confirmed_locations: {len(message.confirmed_locations)}, "
            f"user_inputs kinds: {list((message.user_inputs or {}).keys())}"
        )

        # Send initial status
        await conn.send_status(AgentStage.PLANNING, "Processing your request...")
        conn.begin_streaming_response()

        # Detect language and translate to English if needed
        user_message = message.message
        detected_lang = message.language
        proactive_user_inputs = dict(message.user_inputs or {})

        if not detected_lang:
            english_message, detected_lang = await asyncio.to_thread(
                detect_and_translate_to_english, user_message
            )
            logger.debug(f"Language detected: {detected_lang}")
        else:
            english_message = user_message if detected_lang == "en" else user_message
            if detected_lang != "en":
                english_message, _ = await asyncio.to_thread(
                    detect_and_translate_to_english, user_message
                )
                logger.debug(f"Translated from {detected_lang} to English")

        user_turn_message = UserMessage.create(
            english_message,
            user_inputs=proactive_user_inputs or None,
        )
        english_query = user_turn_message.to_llm_dict()["content"]

        chat_history = normalize_chat_messages(
            [m.to_llm_dict() for m in conversation_context.messages]
        )

        # Create stream callback for real-time updates
        event_loop = asyncio.get_running_loop()
        stream_emitter = EventEmitter()
        # Keep subscriber alive for the request lifetime (weakref listeners).
        stream_subscriber = WebSocketStreamSubscriber(
            conn, event_loop, emitter=stream_emitter
        )

        def run_graph():
            return graph_runner.run_graph_turn(
                message=user_turn_message,
                user_id=str(user.id),
                session_id=str(conversation_context.conversation.id),
                chat_history=chat_history,
                stream_emitter=stream_emitter,
            )

        # Execute in thread pool
        logger.debug("Invoking graph pipeline")
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = await loop.run_in_executor(pool, run_graph)

        if conn.is_closed:
            return

        logger.debug(f"Orchestrator completed - result type: {type(result)}")

        # Check for cancellation
        if conn.is_cancelled():
            await conn.send_complete(
                response="Request cancelled.",
                conversation_id=conversation_context.conversation.id,
                error=False,
            )
            return

        # Process result
        tool_response = coerce_tool_response(result)

        # Check if user input is needed
        data = tool_response.data or {}
        if UserInputRouter.pending_from_tool_data(data):
            await conversations.append_messages(
                user,
                conversation_context.conversation.id,
                [user_turn_message],
                commit=False,
            )
            await _send_user_input_pause(
                conn=conn,
                conversations=conversations,
                user=user,
                conversation_id=conversation_context.conversation.id,
                data=data,
                detected_lang=detected_lang,
                title_user_message=english_query,
                conversation_title_pending=conversation_context.created,
                user_message_persisted=True,
            )
            return

        # translate response message if needed
        response_message = await asyncio.to_thread(
            translate_from_english, tool_response.message, detected_lang
        )
        logger.debug(f"Translated response to {detected_lang}")

        history_messages: list[Message] = [
            user_turn_message,
            AssistantMessage.create(
                tool_response.message,
                metadata=_assistant_message_metadata(tool_response),
            ),
        ]
        await conversations.append_messages(
            user,
            conversation_context.conversation.id,
            history_messages,
        )

        if conversation_context.created:
            await _generate_update_and_send_conversation_title(
                conn=conn,
                conversations=conversations,
                user=user,
                conversation_id=conversation_context.conversation.id,
                user_message=english_query,
                assistant_message=tool_response.message,
            )

        # Send completion
        logger.info(
            f"Chat request completed - error: {tool_response.error}, artifacts: {len(tool_response.artifacts.maps)} maps, {len(tool_response.artifacts.urls)} urls"
        )
        await conn.send_complete(
            response=response_message,
            conversation_id=conversation_context.conversation.id,
            artifacts=tool_response.artifacts,
            error=tool_response.error,
        )

    except Exception as e:
        logger.exception("Error handling chat request")
        await conn.send_error(str(e), recoverable=True)


async def handle_chat_resume(
    conn: WebSocketConnection,
    message: ChatResumeMessage,
    user: User,
    conversations: ConversationService,
) -> None:
    """
    Handle a chat resume request after collecting required user inputs.
    """
    try:
        parsed_inputs = UserInputRouter.results_from_dict(message.user_inputs)
        logger.info(
            f"Chat resume received - kinds={list(parsed_inputs.keys())}, "
            f"conversation_id: {message.conversation_id}"
        )

        # Retrieve the paused agent state server-side; the client only references
        # the conversation id.
        conversation_id = message.conversation_id
        conversation = await conversations.get_conversation(user, conversation_id)
        if conversation is None:
            await conn.send_error("Conversation not found", recoverable=True)
            return

        pause_state = conversation.pause_state or {}
        if not pause_state:
            logger.warning(
                f"Resume requested but no paused state stored for conversation {conversation_id}"
            )
            await conn.send_error(
                "No paused request to resume for this conversation.",
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

        title_pending = bool(pause_state.get("conversation_title_pending"))
        title_user_message = pause_state.get("title_user_message") or pause_state.get(
            "user_text", ""
        )
        user_message_persisted = bool(pause_state.get("user_message_persisted"))

        # The graph pipeline stores its full state under "graph_state".
        graph_state: dict[str, Any] = pause_state.get("graph_state") or {}
        if not graph_state:
            logger.warning(
                f"Resume requested but no graph_state stored for conversation {conversation_id}"
            )
            await conn.send_error(
                "No paused graph state to resume for this conversation.",
                recoverable=True,
            )
            return

        graph_confirmed_index = 0
        confirmed_location: LocationResult | None = None
        if "location" in parsed_inputs:
            loc = parsed_inputs["location"]
            assert isinstance(loc, LocationResult)
            confirmed_location = loc

        candidates = graph_state.get("location_candidates") or []
        loc_payload = (graph_state.get("needs_input") or {}).get("location")
        if isinstance(loc_payload, dict) and loc_payload.get("candidates"):
            candidates = loc_payload["candidates"]
        if confirmed_location is not None:
            graph_confirmed_index = graph_runner.match_location_index(
                candidates,
                confirmed_location,
            )
        resume_user_text = str(
            graph_state.get("user_query") or pause_state.get("user_text", "")
        )
        logger.debug(
            f"Graph resume - confirmed_index: {graph_confirmed_index}, "
            f"candidates: {len(candidates)}, kinds={list(parsed_inputs.keys())}"
        )

        # Create stream wiring for real-time updates
        event_loop = asyncio.get_running_loop()
        stream_emitter = EventEmitter()
        stream_subscriber = WebSocketStreamSubscriber(
            conn, event_loop, emitter=stream_emitter
        )

        user_inputs_payload = {
            kind: model.model_dump(mode="python") for kind, model in parsed_inputs.items()
        }

        def run_graph_resume():
            return graph_runner.resume_graph_turn(
                graph_state=graph_state,
                user_inputs=user_inputs_payload,
                confirmed_index=graph_confirmed_index
                if confirmed_location is not None
                else None,
                stream_emitter=stream_emitter,
            )

        logger.debug("Invoking graph pipeline with resume")
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = await loop.run_in_executor(pool, run_graph_resume)
        if conn.is_closed:
            return

        logger.debug(f"Orchestrator resume completed - result type: {type(result)}")

        # Check for cancellation
        if conn.is_cancelled():
            await conn.send_complete(
                response="Request cancelled.",
                conversation_id=conversation_id,
                error=False,
            )
            return

        # Process result
        tool_response = coerce_tool_response(result)

        # Retrieve language from pause state before branching
        detected_lang = pause_state.get("detected_lang", "en")

        # Check if another user input is needed
        data = tool_response.data or {}
        if UserInputRouter.pending_from_tool_data(data):
            await _send_user_input_pause(
                conn=conn,
                conversations=conversations,
                user=user,
                conversation_id=conversation_id,
                data=data,
                detected_lang=detected_lang,
                title_user_message=str(title_user_message),
                conversation_title_pending=title_pending,
                user_message_persisted=user_message_persisted,
            )
            return

        response_message = await asyncio.to_thread(
            translate_from_english, tool_response.message, detected_lang
        )

        artifacts = tool_response.artifacts

        if conversation_id:
            # The paused turn has been resumed to completion; drop the stored state.
            await conversations.clear_pause_state(user, conversation_id)
            history_messages: list[Message] = []
            if not user_message_persisted and resume_user_text:
                history_messages.append(UserMessage.create(resume_user_text))
            history_messages.append(
                AssistantMessage.create(
                    tool_response.message,
                    metadata=_assistant_message_metadata(tool_response),
                )
            )
            await conversations.append_messages(
                user,
                conversation_id,
                history_messages,
            )
            if title_pending:
                await _generate_update_and_send_conversation_title(
                    conn=conn,
                    conversations=conversations,
                    user=user,
                    conversation_id=conversation_id,
                    user_message=str(title_user_message),
                    assistant_message=tool_response.message,
                )

        logger.info(
            f"Chat resume completed - error: {tool_response.error}, artifacts: {len(artifacts.maps)} maps, {len(artifacts.urls)} urls"
        )
        await conn.send_complete(
            response=response_message,
            conversation_id=conversation_id,
            artifacts=artifacts,
            error=tool_response.error,
        )

    except Exception as e:
        logger.exception("Error handling chat resume")
        await conn.send_error(str(e), recoverable=True)


@router.websocket("/ws/chat")
async def websocket_chat(
    websocket: WebSocket,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    WebSocket endpoint for real-time chat with the agent.

    Handles the full lifecycle of a WebSocket connection:
    1. Accept connection and send acknowledgment
    2. Listen for client messages
    3. Route messages to appropriate handlers
    4. Handle disconnection gracefully
    """
    conn = WebSocketConnection(websocket, user_id=user.id)
    conversations = ConversationService(db)
    active_task: asyncio.Task[None] | None = None
    keepalive_task: asyncio.Task[None] | None = None

    try:
        await conn.accept()
        log_websocket_traffic(
            event="connection_open",
            direction="server",
            connection_id=conn.connection_id,
            user_id=conn.user_id,
            message_type=None,
            payload={"path": websocket.url.path},
        )
        logger.info("WebSocket connection established")

        while True:
            if active_task and active_task.done():
                try:
                    await active_task
                except asyncio.CancelledError:
                    logger.info("Active WebSocket request task was cancelled")
                except Exception:
                    logger.exception("Active WebSocket request task failed")
                active_task = None
                if keepalive_task and not keepalive_task.done():
                    keepalive_task.cancel()
                keepalive_task = None

            # Receive and parse message
            raw_data = ""
            try:
                raw_data = await websocket.receive_text()
                data = json.loads(raw_data)
            except json.JSONDecodeError as e:
                log_websocket_traffic(
                    event="invalid_json",
                    direction="client_to_server",
                    connection_id=conn.connection_id,
                    user_id=conn.user_id,
                    message_type=None,
                    payload={"raw": raw_data, "error": str(e)},
                )
                logger.warning(f"Received invalid JSON from client: {e}")
                await conn.send_error(f"Invalid JSON: {e}", recoverable=True)
                continue

            # Get message type
            msg_type = data.get("type") if isinstance(data, dict) else None
            log_websocket_traffic(
                direction="client_to_server",
                connection_id=conn.connection_id,
                user_id=conn.user_id,
                message_type=msg_type,
                payload=data,
            )
            if not isinstance(data, dict):
                logger.warning("Received non-object JSON from client")
                await conn.send_error(
                    "Invalid message format: expected JSON object", recoverable=True
                )
                continue

            logger.debug(f"Received message type: {msg_type}")

            if msg_type == ClientMessageType.CHAT_REQUEST.value:
                try:
                    if active_task and not active_task.done():
                        await conn.send_error(
                            "A request is already running. Cancel it before starting another.",
                            recoverable=True,
                        )
                        continue
                    message = ChatRequestMessage(**data)
                    conn.reset_cancellation()
                    logger.debug(
                        f"Processing chat_request: message_length={len(message.message)}"
                    )
                    active_task, keepalive_task = _spawn_request_task(
                        conn,
                        handle_chat_request(conn, message, user, conversations),
                    )
                except ValidationError as e:
                    logger.error(f"Chat request validation error: {e}")
                    await conn.send_error(
                        f"Invalid message format: {e}", recoverable=True
                    )

            elif msg_type == ClientMessageType.CHAT_RESUME.value:
                try:
                    if active_task and not active_task.done():
                        await conn.send_error(
                            "A request is already running. Cancel it before starting another.",
                            recoverable=True,
                        )
                        continue
                    logger.debug(
                        f"Processing chat_resume: data: {json.dumps(data, indent=2)}"
                    )
                    message = ChatResumeMessage(**data)
                    logger.debug(
                        f"Processing chat_resume: kinds={list((message.user_inputs or {}).keys())}"
                    )
                    conn.reset_cancellation()
                    active_task, keepalive_task = _spawn_request_task(
                        conn,
                        handle_chat_resume(conn, message, user, conversations),
                    )
                except ValidationError as e:
                    logger.error(f"Chat resume validation error: {e}")
                    await conn.send_error(
                        f"Invalid message format: {e}", recoverable=True
                    )

            elif msg_type == ClientMessageType.CANCEL.value:
                conn.cancel()
                logger.info("Client requested cancellation")
                await conn.send_complete(response="Request cancelled.", error=False)

            else:
                logger.warning(f"Unknown message type received: {msg_type}")
                await conn.send_error(
                    f"Unknown message type: {msg_type}", recoverable=True
                )

    except AuthError as e:
        logger.warning(f"WebSocket authentication failed: {e.message}")
    except AuthConfigurationError as e:
        logger.exception("WebSocket authentication is misconfigured")
    except WebSocketDisconnect as e:
        conn.mark_closed()
        await _cancel_active_task(active_task)
        if keepalive_task and not keepalive_task.done():
            keepalive_task.cancel()
        log_websocket_traffic(
            event="connection_closed",
            direction="client",
            connection_id=conn.connection_id,
            user_id=conn.user_id,
            message_type=None,
            payload={"code": e.code, "reason": e.reason},
        )
        logger.info("WebSocket disconnected")
    except Exception as e:
        conn.mark_closed()
        await _cancel_active_task(active_task)
        if keepalive_task and not keepalive_task.done():
            keepalive_task.cancel()
        logger.exception("WebSocket error")
        try:
            await conn.send_error(str(e), recoverable=False)
        except Exception:
            pass  # Connection may already be closed
