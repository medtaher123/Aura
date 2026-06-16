
import asyncio
import json
from typing import Any, Optional
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

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
        self,
        tool_name: str,
        result: dict,
        artifacts: Optional[ToolArtifacts] = None,
    ) -> None:
        """Send tool execution result."""
        artifacts = artifacts or ToolArtifacts()
        await self.send(
            ToolResultMessage(
                tool_name=tool_name,
                result=result,
                artifacts=artifacts,
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
        self,
        response: str,
        artifacts: Optional[ToolArtifacts] = None,
        error: bool = False,
    ) -> None:
        """Send completion message."""
        artifacts = artifacts or ToolArtifacts()
        await self.send(
            CompleteMessage(
                response=response,
                artifacts=artifacts,
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
