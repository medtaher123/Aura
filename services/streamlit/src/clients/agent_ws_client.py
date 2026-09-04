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

# Bump when the websocket client protocol changes (e.g. new message types).
WS_PROTOCOL_VERSION = 5

DEFAULT_AGENT_SERVER_URL = os.getenv("AGENT_SERVER_URL", "ws://localhost:8080")
DEFAULT_RECONNECT_ATTEMPTS = 3
DEFAULT_RECONNECT_DELAY = 1.0
DEFAULT_TIMEOUT = 300


def _artifact_item_key(item: Any) -> str:
    """Stable identity for deduping artifact items (strings or JSON-able dicts)."""
    if isinstance(item, str):
        return f"s:{item}"
    try:
        return f"j:{json.dumps(item, sort_keys=True, default=str)}"
    except (TypeError, ValueError):
        return f"r:{repr(item)}"


def _extend_artifacts_unique(
    target: dict[str, list[Any]], incoming: dict[str, Any] | None
) -> None:
    """Append artifacts from ``incoming`` that are not already in ``target``."""
    if not isinstance(incoming, dict):
        return
    for key in ("maps", "thumbnails", "urls"):
        items = incoming.get(key)
        if not isinstance(items, list):
            continue
        bucket = target.setdefault(key, [])
        seen = {_artifact_item_key(existing) for existing in bucket}
        for item in items:
            identity = _artifact_item_key(item)
            if identity in seen:
                continue
            seen.add(identity)
            bucket.append(item)


def _merge_complete_artifacts(
    streamed: dict[str, list[Any]], complete: dict[str, Any] | None
) -> None:
    """Merge complete-event artifacts without duplicating already-streamed maps.

    The server often rewrites/merges map specs on ``complete``, so exact-match
    dedupe is not enough — if any maps already arrived via ``tool_result``, keep
    those and only fill missing thumbnails/urls from ``complete``.
    """
    if not isinstance(complete, dict):
        return
    if streamed.get("maps"):
        _extend_artifacts_unique(
            streamed,
            {
                "thumbnails": complete.get("thumbnails") or [],
                "urls": complete.get("urls") or [],
            },
        )
        return
    _extend_artifacts_unique(streamed, complete)


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
    needs_input: dict = field(default_factory=dict)
    pause_state: dict = field(default_factory=dict)

    @property
    def needs_location_confirmation(self) -> bool:
        return "location" in (self.needs_input or {})

    @property
    def location_options(self) -> list:
        payload = (self.needs_input or {}).get("location") or {}
        candidates = payload.get("candidates") or []
        options = []
        for c in candidates:
            if not isinstance(c, dict):
                continue
            options.append(
                {
                    "name": c.get("display_name") or c.get("name") or "Unknown",
                    "coordinates": [c.get("lat", 0), c.get("lon", 0)],
                    "place_id": c.get("place_id"),
                    "osm_id": c.get("osm_id"),
                    "osm_type": c.get("osm_type"),
                    "osm_type_prefix": get_osm_type_prefix(c.get("osm_type") or ""),
                }
            )
        return options


OSMType = Literal["relation", "way", "node"]
OSMPrefixType = Literal["R", "W", "N"]


def get_osm_type_prefix(osm_type: str) -> str:
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
                    ping_timeout=self.timeout,
                    close_timeout=10,
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
        on_thinking: Optional[Callable[[dict], None]] = None,
        on_tool_start: Optional[Callable[..., None]] = None,
        on_tool_result: Optional[Callable[..., None]] = None,
        on_node_start: Optional[Callable[..., None]] = None,
        on_node_end: Optional[Callable[..., None]] = None,
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
        needs_input: dict = {}
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

                elif msg_type == "thinking":
                    if on_thinking:
                        try:
                            on_thinking(data)
                        except Exception as e:
                            logger.warning(f"Error in on_thinking callback: {e}")

                elif msg_type == "tool_start":
                    tool_name = data.get("tool_name", "")
                    tool_input = dict(data.get("tool_input", {}) or {})
                    meta = {
                        "step_id": data.get("step_id"),
                        "domain": data.get("domain"),
                    }
                    logger.info(f"Tool started: {tool_name}")
                    if on_tool_start:
                        try:
                            on_tool_start(tool_name, tool_input, meta)
                        except TypeError:
                            try:
                                on_tool_start(tool_name, tool_input)
                            except Exception as e:
                                logger.warning(f"Error in on_tool_start callback: {e}")
                        except Exception as e:
                            logger.warning(f"Error in on_tool_start callback: {e}")

                elif msg_type == "tool_result":
                    tool_name = data.get("tool_name", "")
                    result = dict(data.get("result", {}) or {})
                    artifacts = data.get("artifacts", {})
                    meta = {
                        "step_id": data.get("step_id"),
                        "domain": data.get("domain"),
                        "execution_time_seconds": data.get("execution_time_seconds"),
                        "status": data.get("status"),
                        "attempts": data.get("attempts"),
                        "observation": data.get("observation"),
                        "error": data.get("error", False),
                        "tool_input": data.get("tool_input"),
                    }
                    logger.info(f"Tool completed: {tool_name}")

                    _extend_artifacts_unique(final_artifacts, artifacts)

                    if on_tool_result:
                        try:
                            on_tool_result(tool_name, result, artifacts, meta)
                        except TypeError:
                            try:
                                on_tool_result(tool_name, result, artifacts)
                            except Exception as e:
                                logger.warning(f"Error in on_tool_result callback: {e}")
                        except Exception as e:
                            logger.warning(f"Error in on_tool_result callback: {e}")

                elif msg_type == "node_start":
                    node_name = data.get("node_name", "")
                    logger.info(f"Node started: {node_name}")
                    if on_node_start:
                        try:
                            on_node_start(
                                node_name,
                                {
                                    "domain": data.get("domain"),
                                    "message": data.get("message"),
                                },
                            )
                        except Exception as e:
                            logger.warning(f"Error in on_node_start callback: {e}")

                elif msg_type == "node_end":
                    node_name = data.get("node_name", "")
                    logger.info(f"Node completed: {node_name}")
                    if on_node_end:
                        try:
                            on_node_end(
                                node_name,
                                {
                                    "domain": data.get("domain"),
                                    "message": data.get("message"),
                                    "result": data.get("result"),
                                    "error": data.get("error", False),
                                },
                            )
                        except Exception as e:
                            logger.warning(f"Error in on_node_end callback: {e}")

                elif msg_type == "user_input_request":
                    needs_input = data.get("needs_input") or {}
                    pause_state = data.get("pause_state", {})
                    conversation_id = pause_state.get("conversation_id")
                    if not accumulated_response and isinstance(needs_input, dict):
                        for payload in needs_input.values():
                            if isinstance(payload, dict):
                                prompt = payload.get("prompt")
                                if isinstance(prompt, str) and prompt.strip():
                                    accumulated_response = prompt.strip()
                                    break
                        if not accumulated_response:
                            accumulated_response = (
                                "Please provide the requested input to continue."
                            )
                    logger.info(
                        f"User input requested kinds={list(needs_input.keys())}"
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

                    # tool_result already carried progressive artifacts; complete
                    # often includes a rewritten/merged map — don't double-add it.
                    _merge_complete_artifacts(final_artifacts, response_artifacts)
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
                    needs_input={},
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
            needs_input=needs_input,
            pause_state=pause_state,
        )

    def send_chat(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        language: Optional[str] = None,
        attachments: Optional[list] = None,
        on_token: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str, Optional[str]], None]] = None,
        on_thinking: Optional[Callable[[dict], None]] = None,
        on_tool_start: Optional[Callable[..., None]] = None,
        on_tool_result: Optional[Callable[..., None]] = None,
        on_node_start: Optional[Callable[..., None]] = None,
        on_node_end: Optional[Callable[..., None]] = None,
    ) -> ChatResponse:
        """Send a chat message and receive streaming response."""
        payload = {
            "type": "chat_request",
            "message": message,
            "conversation_id": conversation_id,
            "language": language,
            "attachments": list(attachments or []),
        }

        async def _do_send():
            return await self._send_and_receive(
                payload,
                on_token=on_token,
                on_status=on_status,
                on_thinking=on_thinking,
                on_tool_start=on_tool_start,
                on_tool_result=on_tool_result,
                on_node_start=on_node_start,
                on_node_end=on_node_end,
            )

        return self._run_sync(_do_send())

    def resume_chat(
        self,
        conversation_id: str,
        attachments: list,
        on_token: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str, Optional[str]], None]] = None,
        on_thinking: Optional[Callable[[dict], None]] = None,
        on_tool_start: Optional[Callable[..., None]] = None,
        on_tool_result: Optional[Callable[..., None]] = None,
        on_node_start: Optional[Callable[..., None]] = None,
        on_node_end: Optional[Callable[..., None]] = None,
    ) -> ChatResponse:
        """Resume chat after collecting required user inputs.

        Only the ``conversation_id`` and ``attachments`` are sent; the paused
        agent state is retrieved server-side from the conversation.
        """
        if not attachments:
            raise ValueError("attachments must be non-empty")
        payload = {
            "type": "chat_resume",
            "attachments": list(attachments),
            "conversation_id": conversation_id,
        }

        async def _do_send():
            return await self._send_and_receive(
                payload,
                on_token=on_token,
                on_status=on_status,
                on_thinking=on_thinking,
                on_tool_start=on_tool_start,
                on_tool_result=on_tool_result,
                on_node_start=on_node_start,
                on_node_end=on_node_end,
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

