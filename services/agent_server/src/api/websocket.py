"""
WebSocket Handler for Agent Server

Manages real-time communication with clients for agent orchestration.
"""

import asyncio
import json
from typing import Any, Optional
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from src.api.websocket_connection import WebSocketConnection
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
from ..auth import AuthConfigurationError, AuthError, authenticate_websocket
from ..config import get_config
from ..core.logger import get_logger
from ..core.memory import normalize_chat_messages
from ..services.orchestrator_agent_service import create_orchestrator_executor
from ..services.agent_runner import invoke_agent, coerce_tool_response
from ..services.translate_service import (
    detect_and_translate_to_english,
    translate_from_english,
)


logger = get_logger("websocket")
router = APIRouter()


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
    conn: WebSocketConnection, message: ChatRequestMessage
) -> None:
    """
    Handle a chat request from the client.

    This is the main entry point for agent orchestration.
    """
    try:
        logger.info(
            f"Chat request received - message length: {len(message.message)}, history size: {len(message.chat_history)}, confirmed_locations: {len(message.confirmed_locations)}"
        )

        # Send initial status
        await conn.send_status(AgentStage.PLANNING, "Processing your request...")

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

        # Normalize chat history
        chat_history = normalize_chat_messages(
            [{"role": m.role, "content": m.content} for m in message.chat_history]
        )

        # Create stream callback for real-time updates
        async def stream_callback_async(event: dict):
            event_type = event.get("type", "")

            if event_type == "orchestrator_plan":
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
                phase = event.get("phase", "")
                tool_name = event.get("tool_name", "")
                tool_input = event.get("tool_input", {})

                if phase == "running":
                    await conn.send_tool_start(
                        tool_name,
                        tool_input
                        if isinstance(tool_input, dict)
                        else {"input": tool_input},
                    )
                elif phase == "done":
                    observation = event.get("observation", "")
                    error = event.get("error", False)
                    await conn.send_tool_result(
                        tool_name=tool_name,
                        result={"observation": observation, "error": error},
                    )

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

        # Run orchestrator in thread pool to avoid blocking
        def run_orchestrator():
            executor = create_orchestrator_executor()
            return invoke_agent(
                executor,
                english_message,
                chat_history=chat_history,
                stream_callback=stream_callback,
            )

        # Execute in thread pool
        logger.debug("Invoking orchestrator agent")
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = await loop.run_in_executor(pool, run_orchestrator)

        logger.debug(f"Orchestrator completed - result type: {type(result)}")

        # Check for cancellation
        if conn.is_cancelled():
            await conn.send_complete(response="Request cancelled.", error=False)
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
            logger.info(
                f"Location confirmation required - {len(options)} options provided"
            )
            logger.debug(
                f"Pause state keys: {list(pause_state.keys())}, has_resume_state: {'resume_state' in pause_state}, has_orchestrator_trace: {'orchestrator_trace' in pause_state}"
            )
            await conn.send_location_confirmation(options, pause_state)
            return

        # translate response message if needed
        response_message = translate_from_english(tool_response.message, detected_lang)
        logger.debug(f"Translated response to {detected_lang}")

        # Send completion
        logger.info(
            f"Chat request completed - error: {tool_response.error}, artifacts: {len(tool_response.artifacts.maps)} maps, {len(tool_response.artifacts.urls)} urls"
        )
        await conn.send_complete(
            response=response_message,
            artifacts=tool_response.artifacts,
            error=tool_response.error,
        )

    except Exception as e:
        logger.exception("Error handling chat request")
        await conn.send_error(str(e), recoverable=True)


async def handle_chat_resume(
    conn: WebSocketConnection, message: ChatResumeMessage
) -> None:
    """
    Handle a chat resume request after location confirmation.
    """
    try:
        logger.info(
            f"Chat resume received - location: {message.confirmed_location.name}, pause_state_keys: {list(message.pause_state.keys())}"
        )

        await conn.send_status(
            AgentStage.PLANNING, "Resuming with confirmed location..."
        )

        # Extract resume information
        pause_state = message.pause_state
        confirmed_location = message.confirmed_location

        # Build resume payload for orchestrator
        resume_payload = {
            "resume_state": pause_state.get("resume_state", {}),
            "orchestrator_trace": pause_state.get("orchestrator_trace", {}),
            "needs_analysis": pause_state.get("needs_analysis", False),
            "analysis_goal": pause_state.get("analysis_goal", ""),
            "user_text": pause_state.get("user_text", ""),
        }

        logger.debug(
            f"Resume payload constructed - has_resume_state: {bool(resume_payload.get('resume_state'))}, has_orchestrator_trace: {bool(resume_payload.get('orchestrator_trace'))}, user_text: {resume_payload.get('user_text', '')[:100]}"
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

            if event_type == "stage":
                stage = event.get("stage", "")
                msg = event.get("message", "")
                if stage == "data_agent":
                    await conn.send_status(AgentStage.TOOL_CALL, msg)
                elif stage == "analysis_agent":
                    await conn.send_status(AgentStage.ANALYZING, msg)

            elif event_type == "data_agent_step":
                phase = event.get("phase", "")
                tool_name = event.get("tool_name", "")
                tool_input = event.get("tool_input", {})

                if phase == "running":
                    await conn.send_tool_start(
                        tool_name,
                        tool_input
                        if isinstance(tool_input, dict)
                        else {"input": tool_input},
                    )
                elif phase == "done":
                    observation = event.get("observation", "")
                    error = event.get("error", False)
                    await conn.send_tool_result(
                        tool_name=tool_name,
                        result={"observation": observation, "error": error},
                    )

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

        # Run orchestrator resume in thread pool
        def run_orchestrator_resume():
            executor = create_orchestrator_executor()
            return invoke_agent(
                executor,
                resume_payload.get("user_text", ""),
                resume=resume_payload,
                stream_callback=stream_callback,
            )

        logger.debug("Invoking orchestrator agent with resume payload")
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = await loop.run_in_executor(pool, run_orchestrator_resume)

        logger.debug(f"Orchestrator resume completed - result type: {type(result)}")

        # Check for cancellation
        if conn.is_cancelled():
            await conn.send_complete(response="Request cancelled.", error=False)
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
            logger.info(
                f"Another location confirmation required during resume - {len(options)} options provided"
            )
            logger.debug(f"New pause state keys: {list(new_pause_state.keys())}")
            await conn.send_location_confirmation(options, new_pause_state)
            return

        response_message = translate_from_english(tool_response.message, detected_lang)

        artifacts = tool_response.artifacts

        logger.info(
            f"Chat resume completed - error: {tool_response.error}, artifacts: {len(artifacts.maps)} maps, {len(artifacts.urls)} urls"
        )
        await conn.send_complete(
            response=response_message,
            artifacts=artifacts,
            error=tool_response.error,
        )

    except Exception as e:
        logger.exception("Error handling chat resume")
        await conn.send_error(str(e), recoverable=True)


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for real-time chat with the agent.

    Handles the full lifecycle of a WebSocket connection:
    1. Accept connection and send acknowledgment
    2. Listen for client messages
    3. Route messages to appropriate handlers
    4. Handle disconnection gracefully
    """
    conn = WebSocketConnection(websocket)

    try:
        user = await authenticate_websocket(websocket)
        if user:
            logger.info(f"Authenticated WebSocket user: {user.user_id}")

        await conn.accept()
        logger.info("WebSocket connection established")

        while True:
            # Receive and parse message
            try:
                raw_data = await websocket.receive_text()
                data = json.loads(raw_data)
            except json.JSONDecodeError as e:
                logger.warning(f"Received invalid JSON from client: {e}")
                await conn.send_error(f"Invalid JSON: {e}", recoverable=True)
                continue

            # Get message type
            msg_type = data.get("type")
            logger.debug(f"Received message type: {msg_type}")

            if msg_type == ClientMessageType.CHAT_REQUEST.value:
                try:
                    message = ChatRequestMessage(**data)
                    conn.reset_cancellation()
                    logger.debug(
                        f"Processing chat_request: message_length={len(message.message)}"
                    )
                    await handle_chat_request(conn, message)
                except ValidationError as e:
                    logger.error(f"Chat request validation error: {e}")
                    await conn.send_error(
                        f"Invalid message format: {e}", recoverable=True
                    )

            elif msg_type == ClientMessageType.CHAT_RESUME.value:
                try:
                    logger.debug(
                        f"Processing chat_resume: data: {json.dumps(data, indent=2)}"
                    )
                    message = ChatResumeMessage(**data)
                    logger.debug(
                        f"Processing chat_resume: location={message.confirmed_location.name}"
                    )
                    conn.reset_cancellation()
                    await handle_chat_resume(conn, message)
                except ValidationError as e:
                    logger.error(f"Chat resume validation error: {e}")
                    await conn.send_error(
                        f"Invalid message format: {e}", recoverable=True
                    )

            elif msg_type == ClientMessageType.CANCEL.value:
                conn.cancel()
                logger.info("Client requested cancellation")

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
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.exception("WebSocket error")
        try:
            await conn.send_error(str(e), recoverable=False)
        except Exception:
            pass  # Connection may already be closed
