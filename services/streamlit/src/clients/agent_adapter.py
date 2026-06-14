"""
Agent Adapter - Abstraction layer for agent communication.

Provides remote agent communication via WebSocket to Agent Server.

Configured via AGENT_SERVER_URL environment variable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing_extensions import Callable, Optional
from src.models.tools import ToolArtifacts
from src.clients.agent_ws_client import LocationOption
from src.core.logger import get_logger

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = get_logger(__name__)

# Agent server configuration
AGENT_SERVER_URL = os.getenv("AGENT_SERVER_URL", "ws://localhost:8080")
AGENT_SERVER_AUTH_TOKEN = os.getenv("AGENT_SERVER_AUTH_TOKEN") or os.getenv(
    "COGNITO_ACCESS_TOKEN"
)


@dataclass
class AgentResponse:
    """Unified response from agent."""

    message: str
    artifacts: ToolArtifacts = field(default_factory=lambda: ToolArtifacts())
    error: bool = False
    needs_location_confirmation: bool = False
    location_options: list[LocationOption] = field(default_factory=list)
    pause_state: dict = field(default_factory=dict)
    raw_data: dict = field(default_factory=dict)


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
        self.auth_token = _clean_auth_token(
            auth_token if auth_token is not None else AGENT_SERVER_AUTH_TOKEN
        )
        self._client = None
        logger.info(f"RemoteAgentAdapter initialized with URL: {self.url}")

    def _get_client(self):
        """Lazy-load the WebSocket client."""
        if self._client is None:
            from src.clients.agent_ws_client import AgentWebSocketClient

            self._client = AgentWebSocketClient(
                url=self.url,
                auth_token=self.auth_token,
            )
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
        resume: Optional[dict] = None,
        confirmed_location: Optional[dict] = None,
        stream_callback: Optional[Callable[[dict], None]] = None,
        language: Optional[str] = None,
    ) -> AgentResponse:
        """
        Invoke the remote agent via WebSocket.

        Args:
            message: User message
            chat_history: Previous conversation history
            document_context: Extracted text from documents
            resume: Resume state for paused agents (the pause_state dict)
            confirmed_location: Confirmed location dict with name, coordinates, etc.
            stream_callback: Callback for streaming updates
            language: User's language

        Returns:
            AgentResponse with result
        """
        from src.clients.agent_ws_client import ChatMessage, LocationOption

        logger.info(f"Invoking agent with message length: {len(message)}")
        logger.debug(f"Chat history length: {len(chat_history) if chat_history else 0}")
        logger.debug(f"Is resume: {bool(resume)}, Has confirmed location: {bool(confirmed_location)}")

        client = self._get_client()

        # Convert chat history to ChatMessage objects
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

        def on_tool_start(tool_name: str, tool_input: dict):
            if stream_callback:
                stream_callback(
                    {
                        "type": "data_agent_step",
                        "phase": "running",
                        "tool_name": tool_name,
                        "tool_input": tool_input,
                    }
                )

        def on_tool_result(tool_name: str, result: dict, artifacts: dict):
            if stream_callback:
                stream_callback(
                    {
                        "type": "data_agent_step",
                        "phase": "done",
                        "tool_name": tool_name,
                        "observation": result.get("observation", ""),
                        "error": result.get("error", False),
                    }
                )

        try:
            if resume and confirmed_location:
                logger.info("Resuming agent from paused state with confirmed location")
                loc = LocationOption(
                    name=confirmed_location.get("name", ""),
                    coordinates=confirmed_location.get("coordinates", [0, 0]),
                    place_id=confirmed_location.get("place_id", None),
                    osm_id=confirmed_location.get("osm_id", None),
                    osm_type=confirmed_location.get("osm_type", None),
                    osm_type_prefix=confirmed_location.get("osm_type_prefix", None),
                )
                response = client.resume_chat(
                    confirmed_location=loc,
                    pause_state=resume,
                    on_status=on_status,
                    on_tool_start=on_tool_start,
                    on_tool_result=on_tool_result,
                )
            else:
                logger.debug("Sending normal chat request")
                response = client.send_chat(
                    message=message,
                    chat_history=history,
                    document_context=document_context,
                    language=language,
                    on_status=on_status,
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
                f"Error: {response.error}, Needs location confirmation: {response.needs_location_confirmation}"
            )

            location_options: list[LocationOption] = []
            for opt in response.location_options or []:
                location_options.append(
                    LocationOption(
                        name=opt.get("name", ""),
                        coordinates=opt.get("coordinates", [0, 0]),
                        place_id=opt.get("place_id", None),
                        osm_id=opt.get("osm_id", None),
                        osm_type=opt.get("osm_type", None),
                        osm_type_prefix=opt.get("osm_type_prefix", None),
                    )
                )

            return AgentResponse(
                message=response.response,
                artifacts=artifacts,
                error=response.error,
                needs_location_confirmation=response.needs_location_confirmation,
                location_options=location_options,
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


def get_agent_adapter() -> RemoteAgentAdapter:
    """Get the remote agent adapter."""
    return RemoteAgentAdapter(url=AGENT_SERVER_URL, auth_token=AGENT_SERVER_AUTH_TOKEN)


# Singleton instance for session reuse
_adapter_instance: Optional[RemoteAgentAdapter] = None


def get_shared_agent_adapter() -> RemoteAgentAdapter:
    """
    Get a shared agent adapter instance.

    This is useful for Streamlit to avoid recreating adapters on each rerun.
    """
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = get_agent_adapter()
    return _adapter_instance
