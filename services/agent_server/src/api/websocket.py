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

from ..config import get_config
from ..core.logger import get_logger
from ..core.memory import normalize_chat_messages
from ..services.orchestrator_agent_service import create_orchestrator_executor
from ..services.agent_runner import invoke_agent, coerce_tool_response
from ..services.translate_service import (
    detect_and_translate_to_english,
    translate_from_english,
)
from .models import (
    AgentStage,
    Artifacts,
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

logger = get_logger("websocket")
router = APIRouter()


def get_pid(opt: dict) -> str:
    return str(opt.get("osm_id")) or str(opt.get("place_id"))


class WebSocketConnection:
    """
    Manages a single WebSocket connection and message handling.

    Provides methods for sending typed messages and managing connection state.
    """

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.config = get_config()
        self._cancelled = False

    async def accept(self) -> None:
        """Accept the WebSocket connection and send acknowledgment."""
        await self.websocket.accept()
        await self.send(ConnectionAckMessage(server_version=self.config.version))
        logger.info("WebSocket connection accepted")

    async def send(self, message: Any) -> None:
        """Send a typed message to the client."""
        if hasattr(message, "model_dump"):
            data = message.model_dump()
        else:
            data = message
        await self.websocket.send_json(data)

    async def send_token(self, content: str) -> None:
        """Send a streaming token."""
        await self.send(TokenMessage(content=content))

    async def send_status(
        self, stage: AgentStage, detail: Optional[str] = None
    ) -> None:
        """Send a status update."""
        await self.send(StatusMessage(stage=stage, detail=detail))

    async def send_tool_start(self, tool_name: str, tool_input: dict) -> None:
        """Send notification that a tool is starting."""
        await self.send(ToolStartMessage(tool_name=tool_name, tool_input=tool_input))

    async def send_tool_result(
        self, tool_name: str, result: dict, artifacts: Optional[Artifacts] = None
    ) -> None:
        """Send tool execution result."""
        await self.send(
            ToolResultMessage(
                tool_name=tool_name,
                result=result,
                artifacts=artifacts or Artifacts(),
            )
        )

    async def send_location_confirmation(
        self, options: list[LocationOption], pause_state: dict
    ) -> None:
        """Send location confirmation request."""
        await self.send(
            LocationConfirmationMessage(options=options, pause_state=pause_state)
        )

    async def send_complete(
        self, response: str, artifacts: Optional[Artifacts] = None, error: bool = False
    ) -> None:
        """Send completion message."""
        await self.send(
            CompleteMessage(
                response=response,
                artifacts=artifacts or Artifacts(),
                error=error,
            )
        )

    async def send_error(self, message: str, recoverable: bool = True) -> None:
        """Send error message."""
        await self.send(ErrorMessage(message=message, recoverable=recoverable))

    def cancel(self) -> None:
        """Mark the current operation as cancelled."""
        self._cancelled = True

    def is_cancelled(self) -> bool:
        """Check if the current operation is cancelled."""
        return self._cancelled

    def reset_cancellation(self) -> None:
        """Reset cancellation state for new operation."""
        self._cancelled = False


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
                        artifacts=Artifacts(),
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
            await conn.send_complete(
                response="Request cancelled.", artifacts=Artifacts(), error=False
            )
            return

        # Process result
        tool_response = coerce_tool_response(result)

        # Check if location confirmation is needed
        data = tool_response.get("data") or {}
        if data.get("needs_location_confirmation"):
            # Tools return 'candidates', not 'location_options'
            options_raw = data.get("candidates", data.get("location_options", []))

            options = [
                LocationOption(
                    name=opt.get("display_name", opt.get("name", "Unknown")),
                    coordinates=[opt.get("lat", 0), opt.get("lon", 0)],
                    place_id=opt.get("place_id", ""),
                    osm_id=opt.get("osm_id", ""),
                    osm_type=opt.get("osm_type", None),
                    osm_type_prefix=get_osm_type_prefix(opt.get("osm_type", "")),
                )
                for opt in options_raw
                if isinstance(opt, dict)
            ]
            pause_state = data.get("pause", {})
            logger.info(
                f"Location confirmation required - {len(options)} options provided"
            )
            logger.debug(
                f"Pause state keys: {list(pause_state.keys())}, has_resume_state: {'resume_state' in pause_state}, has_orchestrator_trace: {'orchestrator_trace' in pause_state}"
            )
            await conn.send_location_confirmation(options, pause_state)
            return

        # Get response message and translate back if needed
        response_message = tool_response.get("message", "")
        if detected_lang and detected_lang != "en":
            response_message = translate_from_english(response_message, detected_lang)
            logger.debug(f"Translated response back to {detected_lang}")

        # Extract artifacts
        artifacts_raw = tool_response.get("artifacts", {})
        artifacts = Artifacts(
            maps=artifacts_raw.get("maps", []),
            thumbnails=artifacts_raw.get("thumbnails", []),
            urls=artifacts_raw.get("urls", []),
        )

        # Send completion
        logger.info(
            f"Chat request completed - error: {bool(tool_response.get('error', False))}, artifacts: {len(artifacts_raw.get('maps', []))} maps, {len(artifacts_raw.get('urls', []))} urls"
        )
        await conn.send_complete(
            response=response_message,
            artifacts=artifacts,
            error=bool(tool_response.get("error", False)),
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
            confirmed_locations = resume_payload["resume_state"].get(
                "confirmed_locations", {}
            )
            logger.debug(f"Resume payload: {json.dumps(resume_payload, indent=2)}")
            # CONFIRMED LOCATION should be of format: name: osmid or place_id
            prefix = confirmed_location.osm_type_prefix
            osm_id = confirmed_location.osm_id
            place_id = confirmed_location.place_id
            location_key = confirmed_location.name
            if prefix and osm_id:
                confirmed_locations[location_key] = f"@osm_id:{prefix}{osm_id}"
            elif place_id:
                confirmed_locations[location_key] = f"@place_id:{place_id}"
            else:
                logger.warning(
                    f"Confirmed location is missing osm_type or osm_id or place_id: {confirmed_location}"
                )

            resume_payload["resume_state"]["confirmed_locations"] = confirmed_locations
            resume_payload["resume_state"]["next_input"]["location"] = (
                confirmed_locations[location_key]
            )
            logger.debug(
                f"Added confirmed location to resume state: {confirmed_locations}"
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
                        artifacts=Artifacts(),
                    )

        # Capture the current event loop for use in thread
        event_loop = asyncio.get_running_loop()

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
            await conn.send_complete(
                response="Request cancelled.", artifacts=Artifacts(), error=False
            )
            return

        # Process result
        tool_response = coerce_tool_response(result)

        # Check if another location confirmation is needed
        data = tool_response.get("data") or {}
        if data.get("needs_location_confirmation"):
            # Tools return 'candidates', not 'location_options'
            options_raw = data.get("candidates", data.get("location_options", []))
            options = [
                LocationOption(
                    name=opt.get("display_name", opt.get("name", "Unknown")),
                    coordinates=[opt.get("lat", 0), opt.get("lon", 0)],
                    place_id=opt.get("place_id", ""),
                    osm_id=opt.get("osm_id", ""),
                    osm_type=opt.get("osm_type", None),
                    osm_type_prefix=get_osm_type_prefix(opt.get("osm_type", "")),
                )
                for opt in options_raw
                if isinstance(opt, dict)
            ]
            new_pause_state = data.get("pause", {})
            logger.info(
                f"Another location confirmation required during resume - {len(options)} options provided"
            )
            logger.debug(f"New pause state keys: {list(new_pause_state.keys())}")
            await conn.send_location_confirmation(options, new_pause_state)
            return

        # Get response message
        response_message = tool_response.get("message", "")

        # Extract artifacts
        artifacts_raw = tool_response.get("artifacts", {})
        artifacts = Artifacts(
            maps=artifacts_raw.get("maps", []),
            thumbnails=artifacts_raw.get("thumbnails", []),
            urls=artifacts_raw.get("urls", []),
        )

        # Send completion
        logger.info(
            f"Chat resume completed - error: {bool(tool_response.get('error', False))}, artifacts: {len(artifacts_raw.get('maps', []))} maps, {len(artifacts_raw.get('urls', []))} urls"
        )
        await conn.send_complete(
            response=response_message,
            artifacts=artifacts,
            error=bool(tool_response.get("error", False)),
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

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.exception("WebSocket error")
        try:
            await conn.send_error(str(e), recoverable=False)
        except Exception:
            pass  # Connection may already be closed
