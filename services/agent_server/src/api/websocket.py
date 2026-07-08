"""
WebSocket Handler for Agent Server

Manages real-time communication with clients for agent orchestration.
"""

import asyncio
import json
import uuid
from typing import Any, Optional
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
    CompleteMessage,
    ConnectionAckMessage,
    ErrorMessage,
    LocationConfirmationMessage,
    LocationOption,
    StatusMessage,
    TokenMessage,
    ToolResultMessage,
    ToolStartMessage,
    get_osm_type_prefix,
)
from ..auth import AuthConfigurationError, AuthError
from ..config import get_config
from ..core.logger import get_logger
from ..core.websocket_traffic_logger import log_websocket_traffic
from ..core.memory import normalize_chat_messages
from ..services.orchestrator_agent_service import create_orchestrator_executor
from ..services.agent_runner import invoke_agent, coerce_tool_response
from ..services import graph_runner
from ..services.translate_service import (
    detect_and_translate_to_english,
    translate_from_english,
)


def _graph_status_stage(stage: str) -> AgentStage:
    """Map a graph_runner status string to an AgentStage."""
    return {
        "planning": AgentStage.PLANNING,
        "tool_call": AgentStage.TOOL_CALL,
        "analyzing": AgentStage.ANALYZING,
    }.get(stage, AgentStage.PLANNING)


async def _handle_data_agent_step_event(conn: WebSocketConnection, event: dict[str, Any]) -> None:
    """Map graph tool-step stream events to websocket tool_start/tool_result."""
    phase = event.get("phase", "")
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})
    step_id = event.get("step_id")
    domain = event.get("domain")

    if phase == "running":
        await conn.send_tool_start(
            tool_name,
            tool_input if isinstance(tool_input, dict) else {"input": tool_input},
            step_id=step_id,
            domain=domain,
        )
        return

    if phase != "done":
        return

    observation = event.get("observation", "")
    error = bool(event.get("error"))
    execution_time_seconds = event.get("execution_time_seconds")
    result: dict[str, Any] = {
        "observation": observation,
        "error": error,
    }
    if execution_time_seconds is not None:
        result["execution_time_seconds"] = execution_time_seconds
    if event.get("attempts") is not None:
        result["attempts"] = event.get("attempts")
    if event.get("status") is not None:
        result["status"] = event.get("status")
    if step_id:
        result["step_id"] = step_id
    if domain:
        result["domain"] = domain

    await conn.send_tool_result(
        tool_name=tool_name,
        result=result,
        step_id=step_id,
        domain=domain,
        execution_time_seconds=execution_time_seconds,
    )


logger = get_logger("websocket")
router = APIRouter()


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


def _patch_resume_state_with_confirmed_location(
    *,
    pause_state: dict[str, Any],
    resume_state: dict[str, Any],
    confirmed_location: LocationOption,
) -> tuple[dict[str, str], str | None]:
    """
    Add confirmed location mapping and patch resume_state["next_input"] safely.

    If next_input is not a dict (legacy paused state), prefer pause_state["tool_input"]
    as the base payload so required structured fields are preserved.
    """
    confirmed_locations = resume_state.get("confirmed_locations", {})
    if not isinstance(confirmed_locations, dict):
        confirmed_locations = {}

    prefix = confirmed_location.osm_type_prefix
    osm_id = confirmed_location.osm_id
    place_id = confirmed_location.place_id
    location_key = confirmed_location.name

    confirmed_value = ""
    if prefix and osm_id:
        confirmed_value = f"@osm_id:{prefix}{osm_id}"
    elif place_id:
        confirmed_value = f"@place_id:{place_id}"

    if confirmed_value:
        confirmed_locations[location_key] = confirmed_value
    else:
        logger.warning(
            f"Confirmed location is missing osm_type or osm_id or place_id: {confirmed_location}"
        )

    resume_state["confirmed_locations"] = confirmed_locations

    resume_patch = pause_state.get("resume_patch", {})
    patch_field = resume_patch.get("field") if isinstance(resume_patch, dict) else None
    next_input = resume_state.get("next_input")
    tool_input = pause_state.get("tool_input")

    if patch_field and confirmed_value:
        if isinstance(next_input, dict):
            patched_input = dict(next_input)
        elif isinstance(tool_input, dict):
            patched_input = dict(tool_input)
        else:
            patched_input = {}

        patched_input[patch_field] = confirmed_value
        resume_state["next_input"] = patched_input
    elif isinstance(next_input, dict):
        # No resume_patch available; leave next_input as-is and rely on
        # confirmed_locations + _apply_confirmed_locations in the DataAgent.
        pass
    else:
        resume_state["next_input"] = next_input

    return confirmed_locations, patch_field


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
            f"Chat request received - message length: {len(message.message)}, conversation_id: {conversation_context.conversation.id}, new_conversation: {conversation_context.created}, history size: {len(conversation_context.messages)}, confirmed_locations: {len(message.confirmed_locations)}"
        )

        # Send initial status
        await conn.send_status(AgentStage.PLANNING, "Processing your request...")
        conn.begin_streaming_response()

        # Detect language and translate to English if needed
        user_message = message.message
        detected_lang = message.language

        if not detected_lang:
            english_message, detected_lang = detect_and_translate_to_english(
                user_message
            )
            logger.debug(f"Language detected: {detected_lang}")
        else:
            english_message = user_message if detected_lang == "en" else user_message
            if detected_lang != "en":
                english_message, _ = detect_and_translate_to_english(user_message)
                logger.debug(f"Translated from {detected_lang} to English")

        chat_history = normalize_chat_messages(
            [
                {"role": m.role, "content": m.content}
                for m in conversation_context.messages
            ]
        )

        # Create stream callback for real-time updates
        async def stream_callback_async(event: dict):
            event_type = event.get("type", "")

            if event_type == "graph_status":
                await conn.send_status(
                    _graph_status_stage(event.get("stage", "")),
                    event.get("message", ""),
                )

            elif event_type == "token":
                content = event.get("content", "")
                if content:
                    await conn.send_token(str(content))

            elif event_type == "orchestrator_plan":
                trace = event.get("trace", {})
                detail = f"Planning: data={trace.get('needs_data')}, analysis={trace.get('needs_analysis')}"
                await conn.send_status(AgentStage.PLANNING, detail)

            elif event_type == "stage":
                stage = event.get("stage", "")
                msg = event.get("message", "")
                if stage == "data_agent":
                    await conn.send_status(AgentStage.TOOL_CALL, msg)
                elif stage == "analysis_agent":
                    await conn.send_status(AgentStage.ANALYZING, msg)

            elif event_type == "data_agent_step":
                await _handle_data_agent_step_event(conn, event)

        # Capture the current event loop for use in thread
        event_loop = asyncio.get_running_loop()

        # Wrapper for sync callback
        def stream_callback(event: dict):
            try:
                # Use the captured event loop from the async context
                asyncio.run_coroutine_threadsafe(
                    stream_callback_async(event), event_loop
                )
            except Exception as e:
                logger.warning(f"Stream callback error: {e}")

        use_graph = get_config().use_graph_pipeline

        # Run the selected engine in a thread pool to avoid blocking the loop.
        def run_orchestrator():
            if use_graph:
                return graph_runner.run_graph_turn(
                    english_query=english_message,
                    user_id=str(user.id),
                    session_id=str(conversation_context.conversation.id),
                    chat_history=chat_history,
                    stream_callback=stream_callback,
                )
            executor = create_orchestrator_executor()
            return invoke_agent(
                executor,
                english_message,
                chat_history=chat_history,
                stream_callback=stream_callback,
            )

        # Execute in thread pool
        logger.debug(f"Invoking agent engine - use_graph_pipeline: {use_graph}")
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = await loop.run_in_executor(pool, run_orchestrator)

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

        # Check if location confirmation is needed
        data = tool_response.data or {}
        if data.get("needs_location_confirmation"):
            # Tools return 'candidates', not 'location_options'
            options_raw = data.get("candidates", data.get("location_options", []))

            options = [
                LocationOption(
                    name=opt.get("display_name", opt.get("name", "Unknown")),
                    coordinates=[opt.get("lat", 0), opt.get("lon", 0)],
                    place_id=opt.get("place_id") or None,
                    osm_id=opt.get("osm_id") or None,
                    osm_type=opt.get("osm_type") or None,
                    osm_type_prefix=get_osm_type_prefix(opt.get("osm_type", "")),
                )
                for opt in options_raw
                if isinstance(opt, dict)
            ]
            pause_state = data.get("pause", {})
            pause_state["detected_lang"] = detected_lang
            pause_state["conversation_id"] = str(conversation_context.conversation.id)
            pause_state["conversation_title_pending"] = conversation_context.created
            pause_state["title_user_message"] = english_message
            logger.info(
                f"Location confirmation required - {len(options)} options provided"
            )
            logger.debug(
                f"Pause state keys: {list(pause_state.keys())}, has_resume_state: {'resume_state' in pause_state}, has_orchestrator_trace: {'orchestrator_trace' in pause_state}"
            )
            # Persist the paused state server-side so the client only needs to
            # reference the conversation id when resuming.
            await conversations.set_pause_state(
                user, conversation_context.conversation.id, pause_state
            )
            await conn.send_location_confirmation(
                options,
                {"conversation_id": str(conversation_context.conversation.id)},
            )
            return

        # translate response message if needed
        response_message = translate_from_english(tool_response.message, detected_lang)
        logger.debug(f"Translated response to {detected_lang}")

        await conversations.append_messages(
            user,
            conversation_context.conversation.id,
            [
                {"role": "user", "content": english_message},
                {
                    "role": "assistant",
                    "content": tool_response.message,
                    "metadata": _assistant_message_metadata(tool_response),
                },
            ],
        )

        if conversation_context.created:
            await _generate_update_and_send_conversation_title(
                conn=conn,
                conversations=conversations,
                user=user,
                conversation_id=conversation_context.conversation.id,
                user_message=english_message,
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
    Handle a chat resume request after location confirmation.
    """
    try:
        logger.info(
            f"Chat resume received - location: {message.confirmed_location.name}, conversation_id: {message.conversation_id}"
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

        await conn.send_status(
            AgentStage.PLANNING, "Resuming with confirmed location..."
        )
        conn.begin_streaming_response()

        # Extract resume information from the persisted pause state.
        confirmed_location = message.confirmed_location
        title_pending = bool(pause_state.get("conversation_title_pending"))
        title_user_message = pause_state.get("title_user_message") or pause_state.get(
            "user_text", ""
        )

        # The graph pipeline stores its full state under "graph_state"; the legacy
        # orchestrator stores a "resume_state". Pick the engine accordingly.
        use_graph = get_config().use_graph_pipeline or ("graph_state" in pause_state)

        graph_state: dict[str, Any] = pause_state.get("graph_state") or {}
        graph_confirmed_index = 0
        resume_payload: dict[str, Any] = {}

        if use_graph:
            graph_confirmed_index = graph_runner.match_location_index(
                graph_state.get("location_candidates") or [],
                confirmed_location,
            )
            resume_user_text = str(
                graph_state.get("user_query") or pause_state.get("user_text", "")
            )
            logger.debug(
                f"Graph resume - confirmed_index: {graph_confirmed_index}, "
                f"candidates: {len(graph_state.get('location_candidates') or [])}"
            )
        else:
            # Build resume payload for orchestrator
            resume_payload = {
                "resume_state": pause_state.get("resume_state", {}),
                "orchestrator_trace": pause_state.get("orchestrator_trace", {}),
                "needs_analysis": pause_state.get("needs_analysis", False),
                "analysis_goal": pause_state.get("analysis_goal", ""),
                "user_text": pause_state.get("user_text", ""),
            }
            resume_user_text = resume_payload.get("user_text", "")

            logger.debug(
                f"Resume payload constructed - has_resume_state: {bool(resume_payload.get('resume_state'))}, has_orchestrator_trace: {bool(resume_payload.get('orchestrator_trace'))}, user_text: {resume_user_text[:100]}"
            )

            # Add confirmed location to the resume state
            if resume_payload.get("resume_state"):
                logger.debug(f"Resume payload: {json.dumps(resume_payload, indent=2)}")
                confirmed_locations, patch_field = (
                    _patch_resume_state_with_confirmed_location(
                        pause_state=pause_state,
                        resume_state=resume_payload["resume_state"],
                        confirmed_location=confirmed_location,
                    )
                )

                logger.debug(
                    f"Added confirmed location to resume state: {confirmed_locations}, patch_field={patch_field}"
                )
            else:
                logger.warning(
                    "Resume state is empty or missing, location confirmation may not work properly"
                )

        # Create stream callback for real-time updates
        async def stream_callback_async(event: dict):
            event_type = event.get("type", "")

            if event_type == "graph_status":
                await conn.send_status(
                    _graph_status_stage(event.get("stage", "")),
                    event.get("message", ""),
                )

            elif event_type == "token":
                content = event.get("content", "")
                if content:
                    await conn.send_token(str(content))

            elif event_type == "stage":
                stage = event.get("stage", "")
                msg = event.get("message", "")
                if stage == "data_agent":
                    await conn.send_status(AgentStage.TOOL_CALL, msg)
                elif stage == "analysis_agent":
                    await conn.send_status(AgentStage.ANALYZING, msg)

            elif event_type == "data_agent_step":
                await _handle_data_agent_step_event(conn, event)

        # Capture the current event loop for use in thread
        event_loop = asyncio.get_running_loop()

        # wrap the stream callback in a thread safe way
        def stream_callback(event: dict):
            try:
                # Use the captured event loop from the async context
                asyncio.run_coroutine_threadsafe(
                    stream_callback_async(event), event_loop
                )
            except Exception as e:
                logger.warning(f"Stream callback error: {e}")

        # Run resume in thread pool
        def run_orchestrator_resume():
            if use_graph:
                return graph_runner.resume_graph_turn(
                    graph_state=graph_state,
                    confirmed_index=graph_confirmed_index,
                    stream_callback=stream_callback,
                )
            executor = create_orchestrator_executor()
            return invoke_agent(
                executor,
                resume_payload.get("user_text", ""),
                resume=resume_payload,
                stream_callback=stream_callback,
            )

        logger.debug(f"Invoking agent engine with resume - use_graph_pipeline: {use_graph}")
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = await loop.run_in_executor(pool, run_orchestrator_resume)

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

        # Check if another location confirmation is needed
        data = tool_response.data or {}
        if data.get("needs_location_confirmation"):
            # Tools return 'candidates', not 'location_options'
            options_raw = data.get("candidates", data.get("location_options", []))
            options = [
                LocationOption(
                    name=opt.get("display_name", opt.get("name", "Unknown")),
                    coordinates=[opt.get("lat", 0), opt.get("lon", 0)],
                    place_id=opt.get("place_id") or None,
                    osm_id=opt.get("osm_id") or None,
                    osm_type=opt.get("osm_type") or None,
                    osm_type_prefix=get_osm_type_prefix(opt.get("osm_type", "")),
                )
                for opt in options_raw
                if isinstance(opt, dict)
            ]
            new_pause_state = data.get("pause", {})
            new_pause_state["detected_lang"] = detected_lang
            if conversation_id:
                new_pause_state["conversation_id"] = str(conversation_id)
            if title_pending:
                new_pause_state["conversation_title_pending"] = True
                new_pause_state["title_user_message"] = title_user_message
            logger.info(
                f"Another location confirmation required during resume - {len(options)} options provided"
            )
            logger.debug(f"New pause state keys: {list(new_pause_state.keys())}")
            # Replace the persisted pause state with the new one so the next
            # resume can reference it by conversation id.
            if conversation_id:
                await conversations.set_pause_state(
                    user, conversation_id, new_pause_state
                )
            await conn.send_location_confirmation(
                options,
                {"conversation_id": str(conversation_id)} if conversation_id else {},
            )
            return

        response_message = translate_from_english(tool_response.message, detected_lang)

        artifacts = tool_response.artifacts

        if conversation_id:
            # The paused turn has been resumed to completion; drop the stored state.
            await conversations.clear_pause_state(user, conversation_id)
            await conversations.append_messages(
                user,
                conversation_id,
                [
                    {"role": "user", "content": resume_user_text},
                    {
                        "role": "assistant",
                        "content": tool_response.message,
                        "metadata": _assistant_message_metadata(tool_response),
                    },
                ],
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
                    active_task = asyncio.create_task(
                        handle_chat_request(conn, message, user, conversations)
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
                        f"Processing chat_resume: location={message.confirmed_location.name}"
                    )
                    conn.reset_cancellation()
                    active_task = asyncio.create_task(
                        handle_chat_resume(conn, message, user, conversations)
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
        logger.exception("WebSocket error")
        try:
            await conn.send_error(str(e), recoverable=False)
        except Exception:
            pass  # Connection may already be closed
