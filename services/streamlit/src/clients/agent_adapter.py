"""Agent Adapter - Abstraction layer for agent communication.

Provides remote agent communication via WebSocket to Agent Server.

Configured via AGENT_SERVER_URL environment variable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing_extensions import Any, Callable, Optional
from src.models.tools import ToolArtifacts
from src.clients.agent_ws_client import LocationOption, WS_PROTOCOL_VERSION
from src.core.logger import get_logger

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = get_logger(__name__)

# Agent server configuration
AGENT_SERVER_URL = os.getenv("AGENT_SERVER_URL", "ws://localhost:8080")


@dataclass
class AgentResponse:
    """Unified response from agent."""

    message: str
    conversation_id: Optional[str] = None
    conversation_title: Optional[str] = None
    artifacts: ToolArtifacts = field(default_factory=lambda: ToolArtifacts())
    error: bool = False
    needs_input: dict = field(default_factory=dict)
    pause_state: dict = field(default_factory=dict)
    raw_data: dict = field(default_factory=dict)

    @property
    def needs_location_confirmation(self) -> bool:
        return "location" in (self.needs_input or {})

    @property
    def location_options(self) -> list[LocationOption]:
        payload = (self.needs_input or {}).get("location") or {}
        candidates = payload.get("candidates") or []
        options: list[LocationOption] = []
        for c in candidates:
            if not isinstance(c, dict):
                continue
            options.append(
                LocationOption(
                    name=str(c.get("display_name") or c.get("name") or "Unknown"),
                    coordinates=[float(c.get("lat") or 0), float(c.get("lon") or 0)],
                    place_id=c.get("place_id"),
                    osm_id=c.get("osm_id"),
                    osm_type=c.get("osm_type"),
                    osm_type_prefix=c.get("osm_type_prefix"),
                )
            )
        return options


def _clean_auth_token(auth_token: Optional[str]) -> Optional[str]:
    if not auth_token:
        return None

    token = auth_token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token or None


class RemoteAgentAdapter:
    """Adapter for remote Agent Server via WebSocket."""

    def __init__(self, url: Optional[str] = None, auth_token: Optional[str] = None):
        self.url = url or AGENT_SERVER_URL
        self.auth_token = _clean_auth_token(auth_token)
        self._client = None
        logger.info(f"RemoteAgentAdapter initialized with URL: {self.url}")

    def _get_client(self):
        """Lazy-load the WebSocket client."""
        from src.clients.agent_ws_client import AgentWebSocketClient, WS_PROTOCOL_VERSION

        if (
            self._client is None
            or getattr(self, "_client_protocol_version", None) != WS_PROTOCOL_VERSION
        ):
            if self._client is not None:
                self._client.close()
            self._client = AgentWebSocketClient(
                url=self.url,
                auth_token=self.auth_token,
            )
            self._client_protocol_version = WS_PROTOCOL_VERSION
        return self._client

    def set_auth_token(self, auth_token: Optional[str]) -> None:
        """Update the bearer token used by the underlying WebSocket client."""
        next_token = _clean_auth_token(auth_token)
        if next_token == self.auth_token:
            return

        self.auth_token = next_token
        if self._client:
            self._client.set_auth_token(next_token)

    def invoke(
        self,
        message: str,
        chat_history: Optional[list[dict]] = None,
        document_context: Optional[str] = None,
        resume: Optional[bool] = None,
        confirmed_location: Optional[dict] = None,
        user_inputs: Optional[dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
        stream_callback: Optional[Callable[[dict], None]] = None,
        language: Optional[str] = None,
    ) -> AgentResponse:
        """Invoke the remote agent via WebSocket."""
        from src.clients.agent_ws_client import ChatMessage, LocationOption

        logger.info(f"Invoking agent with message length: {len(message)}")
        logger.debug(f"Chat history length: {len(chat_history) if chat_history else 0}")
        logger.debug(
            f"Is resume: {bool(resume)}, Has confirmed location: {bool(confirmed_location)}, "
            f"user_inputs kinds: {list((user_inputs or {}).keys())}"
        )

        client = self._get_client()

        history = []
        if chat_history:
            for msg in chat_history:
                if isinstance(msg, dict) and "role" in msg and "content" in msg:
                    history.append(
                        ChatMessage(role=msg["role"], content=msg["content"])
                    )

        def on_status(stage: str, detail: Optional[str] = None):
            if stream_callback:
                stream_callback(
                    {"type": "stage", "stage": stage, "message": detail or stage}
                )

        def on_thinking(payload: dict):
            if stream_callback:
                stream_callback(
                    {
                        "type": "thinking",
                        "source": payload.get("source", ""),
                        "content": payload.get("content", ""),
                        "reasoning": payload.get("reasoning", ""),
                        "stage": payload.get("stage", "planning"),
                    }
                )

        def on_tool_start(tool_name: str, tool_input: dict):
            if stream_callback:
                payload = {
                    "type": "data_agent_step",
                    "phase": "running",
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                }
                if isinstance(tool_input, dict):
                    if tool_input.get("step_id"):
                        payload["step_id"] = tool_input["step_id"]
                    if tool_input.get("domain"):
                        payload["domain"] = tool_input["domain"]
                stream_callback(payload)

        def on_tool_result(tool_name: str, result: dict, artifacts: dict):
            if stream_callback:
                stream_callback(
                    {
                        "type": "data_agent_step",
                        "phase": "done",
                        "tool_name": tool_name,
                        "observation": result.get("observation", ""),
                        "error": result.get("error", False),
                        "execution_time_seconds": result.get("execution_time_seconds"),
                        "attempts": result.get("attempts"),
                        "status": result.get("status"),
                        "step_id": result.get("step_id"),
                        "domain": result.get("domain"),
                        "artifacts": artifacts or {},
                    }
                )

        def on_token(content: str):
            if stream_callback and content:
                stream_callback({"type": "token", "content": content})

        try:
            if resume and (user_inputs or confirmed_location):
                if not conversation_id:
                    raise ValueError(
                        "Cannot resume a paused turn without a conversation_id"
                    )
                logger.info("Resuming agent from paused state with user inputs")
                loc = None
                if confirmed_location:
                    loc = LocationOption(
                        name=confirmed_location.get("name", ""),
                        coordinates=confirmed_location.get("coordinates", [0, 0]),
                        place_id=confirmed_location.get("place_id", None),
                        osm_id=confirmed_location.get("osm_id", None),
                        osm_type=confirmed_location.get("osm_type", None),
                        osm_type_prefix=confirmed_location.get("osm_type_prefix", None),
                    )
                response = client.resume_chat(
                    conversation_id=conversation_id,
                    user_inputs=user_inputs,
                    confirmed_location=loc,
                    on_token=on_token,
                    on_status=on_status,
                    on_thinking=on_thinking,
                    on_tool_start=on_tool_start,
                    on_tool_result=on_tool_result,
                )
            else:
                logger.debug("Sending normal chat request")
                response = client.send_chat(
                    message=message,
                    conversation_id=conversation_id,
                    chat_history=history,
                    document_context=document_context,
                    language=language,
                    on_token=on_token,
                    on_status=on_status,
                    on_thinking=on_thinking,
                    on_tool_start=on_tool_start,
                    on_tool_result=on_tool_result,
                )

            artifacts_dict = response.artifacts or {}
            artifacts = ToolArtifacts(
                maps=artifacts_dict.get("maps", []),
                thumbnails=artifacts_dict.get("thumbnails", []),
                urls=artifacts_dict.get("urls", []),
            )

            logger.info(f"Agent response received: {len(response.response)} chars")
            logger.debug(
                f"Artifacts: {len(artifacts.maps)} maps, {len(artifacts.thumbnails)} thumbnails, {len(artifacts.urls)} urls"
            )
            logger.debug(
                f"Error: {response.error}, needs_input kinds: {list((response.needs_input or {}).keys())}"
            )

            return AgentResponse(
                message=response.response,
                conversation_id=response.conversation_id,
                conversation_title=response.conversation_title,
                artifacts=artifacts,
                error=response.error,
                needs_input=response.needs_input or {},
                pause_state=response.pause_state,
            )

        except Exception as e:
            logger.error(
                f"Error communicating with Agent Server: {type(e).__name__}: {str(e)}"
            )
            return AgentResponse(
                message=f"Error communicating with Agent Server: {str(e)}",
                error=True,
            )

    def close(self):
        """Close the WebSocket connection."""
        if self._client:
            logger.info("Closing WebSocket client")
            self._client.close()
            self._client = None

    def cancel(self):
        """Cancel the active WebSocket request, if any."""
        if self._client:
            logger.info("Cancelling active WebSocket request")
            self._client.cancel()


def get_agent_adapter() -> RemoteAgentAdapter:
    """Get the remote agent adapter."""
    return RemoteAgentAdapter(url=AGENT_SERVER_URL)


_adapter_instance: Optional[RemoteAgentAdapter] = None


def get_shared_agent_adapter() -> RemoteAgentAdapter:
    """Get a shared agent adapter instance for Streamlit session reuse."""
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = get_agent_adapter()
    return _adapter_instance


def reset_shared_agent_adapter() -> RemoteAgentAdapter:
    """Drop cached adapter/client state after websocket protocol changes."""
    global _adapter_instance
    if _adapter_instance is not None:
        _adapter_instance.close()
    _adapter_instance = get_agent_adapter()
    return _adapter_instance
