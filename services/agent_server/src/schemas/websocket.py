"""
WebSocket Message Models for Agent Server

Defines the message protocol for client-server communication.
"""

from enum import Enum
import uuid
from typing import Any as TypingAny
from typing_extensions import Any, Literal, Optional
from pydantic import BaseModel, Field

from src.db.models.message import InputResponseMessage, UserMessage
from src.db.models.message_attachments import AnyMessageAttachment
from src.tools.contracts import ToolArtifacts
from src.user_inputs import (
    InputKind,
    get_osm_type_prefix,
)
from src.schemas.spatial import BoundingBox

# Re-export for call sites that imported these from websocket.
OSMType = Literal["relation", "way", "node"]
OSMPrefixType = Literal["R", "W", "N"]

__all__ = [
    "AgentStage",
    "BoundingBox",
    "CancelMessage",
    "ChatRequestMessage",
    "ChatResumeMessage",
    "ClientMessage",
    "ClientMessageType",
    "CompleteMessage",
    "ConnectionAckMessage",
    "ConversationTitleMessage",
    "Coordinates",
    "ErrorMessage",
    "InputKind",
    "OSMPrefixType",
    "OSMType",
    "ServerMessage",
    "ServerMessageType",
    "StatusMessage",
    "ThinkingMessage",
    "TokenMessage",
    "ToolResultMessage",
    "ToolStartMessage",
    "UserInputRequestMessage",
    "get_osm_type_prefix",
]


# =============================================================================
# Enums
# =============================================================================


class ClientMessageType(str, Enum):
    """Types of messages the client can send."""

    CHAT_REQUEST = "chat_request"
    CHAT_RESUME = "chat_resume"
    CANCEL = "cancel"


class ServerMessageType(str, Enum):
    """Types of messages the server can send."""

    CONNECTION_ACK = "connection_ack"
    TOKEN = "token"
    STATUS = "status"
    THINKING = "thinking"
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    USER_INPUT_REQUEST = "user_input_request"
    CONVERSATION_TITLE = "conversation_title"
    COMPLETE = "complete"
    ERROR = "error"


class AgentStage(str, Enum):
    """Stages of agent processing."""

    PLANNING = "planning"
    TOOL_CALL = "tool_call"
    ANALYZING = "analyzing"


# =============================================================================
# Shared Models
# =============================================================================


class Coordinates(BaseModel):
    """Geographic coordinates."""

    lat: float = Field(..., description="Latitude")
    lon: float = Field(..., description="Longitude")


# =============================================================================
# Client -> Server Messages
# =============================================================================


class ChatRequestMessage(BaseModel):
    """Client request to start a new chat."""

    type: str = Field(default=ClientMessageType.CHAT_REQUEST.value)
    message: str = Field(..., description="User message")
    conversation_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Conversation ID; omit to create a new conversation",
    )
    language: Optional[str] = Field(
        default=None,
        description="User's language for translation (auto-detected if None)",
    )
    attachments: list[AnyMessageAttachment] = Field(
        default_factory=list,
        description=(
            "Optional message attachments (e.g. type=location, type=bounding_box, type=file) "
            "sent proactively with the message"
        ),
    )

    def to_message(self) -> UserMessage:
        """Build the persisted user turn from this wire payload."""
        return UserMessage.create(self.message, attachments=list(self.attachments))


class ChatResumeMessage(BaseModel):
    """Client request to resume after collecting required user inputs.

    The client only references the conversation; the paused agent state is
    retrieved server-side from the conversation rather than round-tripped
    through the client.
    """

    type: str = Field(default=ClientMessageType.CHAT_RESUME.value)
    conversation_id: uuid.UUID = Field(
        ..., description="Conversation whose paused state should be resumed"
    )
    attachments: list[AnyMessageAttachment] = Field(
        ...,
        min_length=1,
        description=(
            "Non-empty attachments answering needs_input "
            "(type=location, type=bounding_box, …)"
        ),
    )

    def to_message(self) -> InputResponseMessage:
        """Build the persisted input-response turn from this wire payload."""
        return InputResponseMessage.create(attachments=list(self.attachments))


class CancelMessage(BaseModel):
    """Client request to cancel current operation."""

    type: str = Field(default=ClientMessageType.CANCEL.value)


# =============================================================================
# Server -> Client Messages
# =============================================================================


class ConnectionAckMessage(BaseModel):
    """Server acknowledgment of WebSocket connection."""

    type: str = Field(default=ServerMessageType.CONNECTION_ACK.value)
    server_version: str = Field(..., description="Agent server version")


class TokenMessage(BaseModel):
    """Streaming token from LLM response."""

    type: str = Field(default=ServerMessageType.TOKEN.value)
    content: str = Field(..., description="Token text content")


class StatusMessage(BaseModel):
    """Agent status update."""

    type: str = Field(default=ServerMessageType.STATUS.value)
    stage: AgentStage = Field(..., description="Current processing stage")
    detail: Optional[str] = Field(default=None, description="Additional detail")


class ThinkingMessage(BaseModel):
    """Agent decision reasoning shown while work is in progress."""

    type: str = Field(default=ServerMessageType.THINKING.value)
    source: str = Field(..., description="Decision source, e.g. route_domains or tool_plan")
    content: str = Field(..., description="User-facing formatted reasoning line")
    reasoning: str = Field(default="", description="Raw reasoning text from the model")
    stage: AgentStage = Field(
        default=AgentStage.PLANNING,
        description="Processing stage this reasoning belongs to",
    )


class ToolStartMessage(BaseModel):
    """Notification that a tool is being executed."""

    type: str = Field(default=ServerMessageType.TOOL_START.value)
    tool_name: str = Field(..., description="Name of the tool being called")
    tool_input: dict[str, Any] = Field(..., description="Tool input parameters")
    step_id: Optional[str] = Field(default=None, description="Planned tool step id")
    domain: Optional[str] = Field(default=None, description="Domain executing the tool")


class ToolResultMessage(BaseModel):
    """Result from tool execution."""

    type: str = Field(default=ServerMessageType.TOOL_RESULT.value)
    tool_name: str = Field(..., description="Name of the tool that was called")
    result: dict[str, Any] = Field(
        ..., description="ToolResponse body (message, data, error, artifacts, …)"
    )
    artifacts: ToolArtifacts = Field(default=ToolArtifacts(), description="Artifacts")
    step_id: Optional[str] = Field(default=None, description="Planned tool step id")
    domain: Optional[str] = Field(default=None, description="Domain that ran the tool")
    execution_time_seconds: Optional[float] = Field(
        default=None, description="Wall-clock execution time in seconds"
    )
    status: Optional[str] = Field(
        default=None, description="Step status: done, error, or skipped"
    )
    attempts: Optional[int] = Field(default=None, description="Number of attempts")
    observation: Optional[str] = Field(
        default=None, description="Short observation / message for UI detail"
    )
    error: bool = Field(default=False, description="Whether the step ended in error")
    tool_input: Optional[dict[str, Any]] = Field(
        default=None,
        description="Tool arguments (redundant with tool_start for late UI joins)",
    )


class UserInputRequestMessage(BaseModel):
    """Request for the client to collect one or more user inputs."""

    type: str = Field(default=ServerMessageType.USER_INPUT_REQUEST.value)
    needs_input: dict[str, TypingAny] = Field(
        ...,
        description="kind → TRequest map; non-empty means the agent is paused",
    )
    pause_state: dict[str, Any] = Field(
        ...,
        description=(
            "Client resume reference only — currently {conversation_id}. "
            "Full pause payload is stored server-side on the conversation."
        ),
    )


class ConversationTitleMessage(BaseModel):
    """Generated title for a conversation."""

    type: str = Field(default=ServerMessageType.CONVERSATION_TITLE.value)
    conversation_id: uuid.UUID = Field(..., description="Conversation that was titled")
    title: str = Field(..., description="Generated conversation title")


class CompleteMessage(BaseModel):
    """Final response indicating completion."""

    type: str = Field(default=ServerMessageType.COMPLETE.value)
    response: str = Field(..., description="Final response text")
    conversation_id: Optional[uuid.UUID] = Field(
        default=None, description="Conversation associated with this response"
    )
    artifacts: ToolArtifacts = Field(default=ToolArtifacts(), description="Artifacts")
    error: bool = Field(default=False, description="Whether an error occurred")
    replace_streamed: bool = Field(
        default=False,
        description=(
            "When true, clients should replace any text assembled from prior "
            "token events with this response."
        ),
    )


class ErrorMessage(BaseModel):
    """Error message."""

    type: str = Field(default=ServerMessageType.ERROR.value)
    message: str = Field(..., description="Error description")
    recoverable: bool = Field(default=True, description="Whether the client can retry")


# =============================================================================
# Union Types for Parsing
# =============================================================================

ServerMessage = (
    ConnectionAckMessage
    | TokenMessage
    | StatusMessage
    | ThinkingMessage
    | ToolStartMessage
    | ToolResultMessage
    | UserInputRequestMessage
    | ConversationTitleMessage
    | CompleteMessage
    | ErrorMessage
)

ClientMessage = ChatRequestMessage | ChatResumeMessage | CancelMessage
