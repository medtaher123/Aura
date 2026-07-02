import uuid
from typing import Any, Optional

from fastapi import WebSocket

from src.schemas.websocket import (
    AgentStage,
    ToolArtifacts,
    ConnectionAckMessage,
    ConversationTitleMessage,
    CompleteMessage,
    ErrorMessage,
    LocationConfirmationMessage,
    LocationOption,
    StatusMessage,
    ToolResultMessage,
    ToolStartMessage,
)

from ..config import get_config
from ..core.logger import get_logger
from ..core.websocket_traffic_logger import log_websocket_traffic

logger = get_logger("websocket")
config = get_config()


class WebSocketConnection:
    """
    Manages a single WebSocket connection and message handling.

    Provides methods for sending typed messages and managing connection state.
    """

    def __init__(self, websocket: WebSocket, user_id: str | None = None):
        self.websocket = websocket
        self.config = get_config()
        self._cancelled = False
        self.connection_id = str(uuid.uuid4())
        self.user_id = user_id

    async def accept(self) -> None:
        """Accept the WebSocket connection and send acknowledgment."""
        await self.websocket.accept()
        await self.send(ConnectionAckMessage(server_version=self.config.version))
        logger.info(f"WebSocket connection accepted - connection_id: {self.connection_id}")

    async def send(self, message: Any) -> None:
        """Send a typed message to the client."""
        if hasattr(message, "model_dump"):
            data = message.model_dump(mode="json")
        else:
            data = message
        
        if config.ws_traffic_log_enabled:
            log_websocket_traffic(
                direction="server_to_client",
                connection_id=self.connection_id,
                user_id=self.user_id,
                message_type=data.get("type") if isinstance(data, dict) else None,
                payload=data,
            )
        await self.websocket.send_json(data)

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

    async def send_conversation_title(
        self, conversation_id: uuid.UUID, title: str
    ) -> None:
        """Send generated conversation title."""
        await self.send(
            ConversationTitleMessage(conversation_id=conversation_id, title=title)
        )

    async def send_complete(
        self,
        response: str,
        conversation_id: Optional[uuid.UUID | str] = None,
        artifacts: Optional[ToolArtifacts] = None,
        error: bool = False,
    ) -> None:
        """Send completion message."""
        artifacts = artifacts or ToolArtifacts()
        if isinstance(conversation_id, str):
            normalized_conversation_id = (
                uuid.UUID(conversation_id) if conversation_id else None
            )
        else:
            normalized_conversation_id = conversation_id
        await self.send(
            CompleteMessage(
                response=response,
                conversation_id=normalized_conversation_id,
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
