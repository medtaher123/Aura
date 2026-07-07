"""
WebSocket Client for Agent Server Communication

Provides a client for real-time communication with the Agent Server
via WebSocket, supporting streaming responses and status updates.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.logger import get_logger  # noqa: E402

logger = get_logger(__name__)


DEFAULT_AGENT_SERVER_URL = os.getenv("AGENT_SERVER_URL", "ws://localhost:8080")
DEFAULT_RECONNECT_ATTEMPTS = 3
DEFAULT_RECONNECT_DELAY = 1.0
DEFAULT_TIMEOUT = 300


@dataclass
class ChatMessage:
    """A chat message in history."""

    role: str
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class ChatResponse:
    """Response from agent chat."""

    response: str
    conversation_id: Optional[str] = None
    conversation_title: Optional[str] = None
    artifacts: dict = field(
        default_factory=lambda: {"maps": [], "thumbnails": [], "urls": []}
    )
    error: bool = False
    needs_location_confirmation: bool = False
    location_options: list = field(default_factory=list)
    pause_state: dict = field(default_factory=dict)


OSMType = Literal["relation", "way", "node"]
OSMPrefixType = Literal["R", "W", "N"]


def get_osm_type_prefix(osm_type: OSMType) -> OSMPrefixType:
    match osm_type:
        case "relation":
            return "R"
        case "way":
            return "W"
        case "node":
            return "N"
        case _:
            return ""


@dataclass
class LocationOption:
    """A location option for disambiguation."""

    name: str
    coordinates: list[float]
    place_id: Optional[int] = None
    osm_id: Optional[int] = None
    osm_type: Optional[OSMType] = None
    osm_type_prefix: Optional[OSMPrefixType] = None


class AgentWebSocketClient:
    """
    WebSocket client for Agent Server communication.

    Supports:
    - Streaming responses with callbacks
    - Status updates during processing
    - Location confirmation flow (pause/resume)
    - Auto-reconnection with exponential backoff
    - Thread-safe execution for Streamlit
    """

    def __init__(
        self,
        url: Optional[str] = None,
        reconnect_attempts: int = DEFAULT_RECONNECT_ATTEMPTS,
        reconnect_delay: float = DEFAULT_RECONNECT_DELAY,
        timeout: float = DEFAULT_TIMEOUT,
        auth_token: Optional[str] = None,
    ):
        self.url = url or DEFAULT_AGENT_SERVER_URL
        if not self.url.endswith("/ws/chat"):
            self.url = self.url.rstrip("/") + "/ws/chat"

        self.auth_token = self._clean_auth_token(auth_token)
        self.reconnect_attempts = reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self.timeout = timeout

        self._websocket: Optional[Any] = None
        self._connected = False
        self._cancelled = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_id: Optional[int] = None

        logger.info(f"Initialized WebSocket client for URL: {self.url}")

    @staticmethod
    def _clean_auth_token(auth_token: Optional[str]) -> Optional[str]:
        if not auth_token:
            return None

        token = auth_token.strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        return token or None

    def set_auth_token(self, auth_token: Optional[str]) -> None:
        """Update the bearer token used for future WebSocket handshakes."""
        next_token = self._clean_auth_token(auth_token)
        if next_token == self.auth_token:
            return

        self.auth_token = next_token
        if self._connected:
            self.close()

    def _connection_headers(self) -> Optional[dict[str, str]]:
        if not self.auth_token:
            return None
        return {"Authorization": f"Bearer {self.auth_token}"}

    def _run_sync(self, coro: Any) -> Any:
        """Run an async coroutine from sync code, handling Streamlit's event loop."""
        try:
            asyncio.get_running_loop()

            def run_in_thread():
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(coro)
                finally:
                    new_loop.close()

            with ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(run_in_thread)
                return future.result()
        except RuntimeError:
            return asyncio.run(coro)

    async def _connect(self) -> None:
        """Establish WebSocket connection with retry logic."""
        last_error = None
        logger.info(f"Attempting to connect to Agent Server at {self.url}")

        for attempt in range(self.reconnect_attempts):
            try:
                logger.debug(
                    f"Connection attempt {attempt + 1}/{self.reconnect_attempts}"
                )
                self._websocket = await websockets.connect(
                    self.url,
                    additional_headers=self._connection_headers(),
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5,
                )

                ack = await asyncio.wait_for(self._websocket.recv(), timeout=10)
                ack_data = json.loads(ack)

                if ack_data.get("type") == "connection_ack":
                    self._connected = True
                    self._loop = asyncio.get_event_loop()
                    self._loop_id = id(self._loop)
                    logger.info("Successfully connected to Agent Server")
                    return
                else:
                    logger.warning(f"Unexpected acknowledgment: {ack_data}")
                    raise WebSocketException(f"Unexpected ack: {ack_data}")

            except Exception as e:
                last_error = e
                logger.warning(
                    f"Connection attempt {attempt + 1} failed: {type(e).__name__}: {str(e)}"
                )
                if attempt < self.reconnect_attempts - 1:
                    delay = self.reconnect_delay * (2**attempt)
                    logger.debug(f"Retrying in {delay}s...")
                    await asyncio.sleep(delay)

        error_msg = f"Failed to connect to Agent Server after {self.reconnect_attempts} attempts: {last_error}"
        logger.error(error_msg)
        raise ConnectionError(error_msg)

    async def _disconnect(self) -> None:
        """Close WebSocket connection."""
        if self._websocket:
            try:
                logger.debug("Closing WebSocket connection")
                await self._websocket.close()
                logger.info("WebSocket connection closed")
            except Exception as e:
                logger.warning(
                    f"Error while closing WebSocket: {type(e).__name__}: {str(e)}"
                )
            finally:
                self._websocket = None
                self._connected = False
                self._loop = None
                self._loop_id = None

    async def _send_and_receive(
        self,
        message: dict,
        on_token: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str, Optional[str]], None]] = None,
        on_tool_start: Optional[Callable[[str, dict], None]] = None,
        on_tool_result: Optional[Callable[[str, dict, dict], None]] = None,
    ) -> ChatResponse:
        """Send a message and receive streaming response."""
        current_loop_id = id(asyncio.get_event_loop())

        # Reconnect if the event loop has changed (common in Streamlit's threading model)
        if (
            self._connected
            and self._loop_id is not None
            and self._loop_id != current_loop_id
        ):
            logger.warning("Event loop changed. Reconnecting...")
            await self._disconnect()

        if not self._connected:
            await self._connect()

        self._cancelled = False

        if self._websocket is None:
            raise ConnectionError("WebSocket connection not established")

        logger.debug(f"Sending message type: {message.get('type', 'unknown')}")
        await self._websocket.send(json.dumps(message))

        accumulated_response = ""
        final_artifacts = {"maps": [], "thumbnails": [], "urls": []}
        error = False
        needs_location_confirmation = False
        location_options = []
        pause_state = {}
        conversation_id = None
        conversation_title = None

        try:
            async for raw_msg in self._websocket:
                if self._cancelled:
                    await self._websocket.send(json.dumps({"type": "cancel"}))
                    await self._disconnect()
                    accumulated_response = "Request cancelled."
                    break

                try:
                    data = json.loads(raw_msg)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type", "")

                if msg_type == "token":
                    content = data.get("content", "")
                    accumulated_response += content
                    if on_token:
                        try:
                            on_token(content)
                        except Exception as e:
                            logger.warning(f"Error in on_token callback: {e}")

                elif msg_type == "status":
                    stage = data.get("stage", "")
                    detail = data.get("detail")
                    logger.debug(f"Status update: stage={stage}, detail={detail}")
                    if on_status:
                        try:
                            on_status(stage, detail)
                        except Exception as e:
                            logger.warning(f"Error in on_status callback: {e}")

                elif msg_type == "tool_start":
                    tool_name = data.get("tool_name", "")
                    tool_input = data.get("tool_input", {})
                    logger.info(f"Tool started: {tool_name}")
                    if on_tool_start:
                        try:
                            on_tool_start(tool_name, tool_input)
                        except Exception as e:
                            logger.warning(f"Error in on_tool_start callback: {e}")

                elif msg_type == "tool_result":
                    tool_name = data.get("tool_name", "")
                    result = data.get("result", {})
                    artifacts = data.get("artifacts", {})
                    logger.info(f"Tool completed: {tool_name}")

                    for key in ["maps", "thumbnails", "urls"]:
                        if key in artifacts:
                            final_artifacts[key].extend(artifacts.get(key, []))

                    if on_tool_result:
                        try:
                            on_tool_result(tool_name, result, artifacts)
                        except Exception as e:
                            logger.warning(f"Error in on_tool_result callback: {e}")

                elif msg_type == "location_confirmation":
                    needs_location_confirmation = True
                    location_options = data.get("options", [])
                    pause_state = data.get("pause_state", {})
                    conversation_id = pause_state.get("conversation_id")
                    logger.info(
                        f"Location confirmation requested with {len(location_options)} options"
                    )
                    break

                elif msg_type == "conversation_title":
                    conversation_id = data.get("conversation_id") or conversation_id
                    conversation_title = data.get("title") or conversation_title
                    logger.info(f"Conversation title generated: {conversation_title}")

                elif msg_type == "complete":
                    response_text = data.get("response", "")
                    if data.get("replace_streamed", False):
                        accumulated_response = response_text
                    else:
                        accumulated_response = response_text or accumulated_response
                    conversation_id = data.get("conversation_id") or conversation_id
                    response_artifacts = data.get("artifacts", {})
                    error = data.get("error", False)
                    logger.info(f"Agent response complete (error={error})")

                    for key in ["maps", "thumbnails", "urls"]:
                        if key in response_artifacts:
                            final_artifacts[key].extend(
                                response_artifacts.get(key, [])
                            )
                    break

                elif msg_type == "error":
                    error = True
                    accumulated_response = data.get("message", "An error occurred")
                    recoverable = data.get("recoverable", True)
                    logger.error(
                        f"Agent error (recoverable={recoverable}): {accumulated_response}"
                    )
                    if not recoverable:
                        raise RuntimeError(accumulated_response)
                    break

        except ConnectionClosed as e:
            self._connected = False
            if self._cancelled:
                self._websocket = None
                self._loop = None
                self._loop_id = None
                return ChatResponse(
                    response="Request cancelled.",
                    conversation_id=conversation_id,
                    conversation_title=conversation_title,
                    artifacts=final_artifacts,
                    error=False,
                    needs_location_confirmation=False,
                    location_options=[],
                    pause_state={},
                )
            logger.error(f"WebSocket connection closed unexpectedly: {e}")
            raise ConnectionError("WebSocket connection closed unexpectedly")

        return ChatResponse(
            response=accumulated_response,
            conversation_id=conversation_id,
            conversation_title=conversation_title,
            artifacts=final_artifacts,
            error=error,
            needs_location_confirmation=needs_location_confirmation,
            location_options=location_options,
            pause_state=pause_state,
        )

    def send_chat(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        chat_history: Optional[list[ChatMessage]] = None,
        confirmed_locations: Optional[dict[str, list[float]]] = None,
        document_context: Optional[str] = None,
        language: Optional[str] = None,
        on_token: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str, Optional[str]], None]] = None,
        on_tool_start: Optional[Callable[[str, dict], None]] = None,
        on_tool_result: Optional[Callable[[str, dict, dict], None]] = None,
    ) -> ChatResponse:
        """Send a chat message and receive streaming response."""
        payload = {
            "type": "chat_request",
            "message": message,
            "conversation_id": conversation_id,
            "chat_history": [m.to_dict() for m in (chat_history or [])],
            "confirmed_locations": confirmed_locations or {},
            "document_context": document_context,
            "language": language,
        }

        async def _do_send():
            return await self._send_and_receive(
                payload,
                on_token=on_token,
                on_status=on_status,
                on_tool_start=on_tool_start,
                on_tool_result=on_tool_result,
            )

        return self._run_sync(_do_send())

    def resume_chat(
        self,
        confirmed_location: LocationOption,
        conversation_id: str,
        on_token: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str, Optional[str]], None]] = None,
        on_tool_start: Optional[Callable[[str, dict], None]] = None,
        on_tool_result: Optional[Callable[[str, dict, dict], None]] = None,
    ) -> ChatResponse:
        """Resume chat after location confirmation.

        Only the ``conversation_id`` is sent; the paused agent state is retrieved
        server-side from the conversation.
        """
        payload = {
            "type": "chat_resume",
            "confirmed_location": {
                "name": confirmed_location.name,
                "coordinates": confirmed_location.coordinates,
                "place_id": confirmed_location.place_id,
                "osm_id": confirmed_location.osm_id,
                "osm_type": confirmed_location.osm_type,
                "osm_type_prefix": confirmed_location.osm_type_prefix,
            },
            "conversation_id": conversation_id,
        }

        async def _do_send():
            return await self._send_and_receive(
                payload,
                on_token=on_token,
                on_status=on_status,
                on_tool_start=on_tool_start,
                on_tool_result=on_tool_result,
            )

        return self._run_sync(_do_send())

    def cancel(self) -> None:
        """Cancel the current operation."""
        self._cancelled = True
        if not self._connected or self._websocket is None:
            return

        async def _send_cancel() -> None:
            if self._websocket is not None:
                await self._websocket.send(json.dumps({"type": "cancel"}))
                await self._websocket.close()

        try:
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(_send_cancel(), self._loop)
            else:
                self._run_sync(_send_cancel())
        except Exception as e:
            logger.warning(f"Failed to send cancel request: {type(e).__name__}: {e}")

    def close(self) -> None:
        """Close the WebSocket connection."""
        self._run_sync(self._disconnect())

    def is_connected(self) -> bool:
        """Check if the client is connected."""
        return self._connected

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

