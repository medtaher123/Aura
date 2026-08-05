"""
WebSocket Message Models for Agent Server

Defines the message protocol for client-server communication.
"""

from enum import Enum
import uuid
from typing import Any as TypingAny
from typing_extensions import Any, Literal, Optional
from pydantic import AliasChoices, BaseModel, Field, model_validator

from src.tools.contracts import ToolArtifacts
from src.schemas.user_inputs import (
    BoundingBoxResult,
    InputKind,
    LocationOption,
    LocationResult,
    get_osm_type_prefix,
)
from src.schemas.spatial import BoundingBox

# Re-export for call sites that imported these from websocket.
OSMType = Literal["relation", "way", "node"]
OSMPrefixType = Literal["R", "W", "N"]

__all__ = [
    "AgentStage",
    "BoundingBox",
    "BoundingBoxResult",
    "CancelMessage",
    "ChatMessage",
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
    "LocationOption",
    "LocationResult",
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


class ChatMessage(BaseModel):
    """A single chat message in history."""

    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")


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
    conversation_history: list[ChatMessage] = Field(
        default_factory=list,
        validation_alias=AliasChoices("conversation_history", "chat_history"),
        description="Previous conversation history",
    )
    conversation_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Conversation ID to load history from when history is not provided",
    )
    confirmed_locations: dict[str, list[float]] = Field(
        default_factory=dict,
        description="Cache of confirmed locations: {name: [lat, lon]}",
    )
    document_context: Optional[str] = Field(
        default=None, description="Extracted text from uploaded documents"
    )
    language: Optional[str] = Field(
        default=None,
        description="User's language for translation (auto-detected if None)",
    )
    user_inputs: dict[str, TypingAny] = Field(
        default_factory=dict,
        description=(
            "Optional kind → TResult map attached proactively with the message "
            "(same shapes as chat_resume.user_inputs)"
        ),
    )


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
    user_inputs: dict[str, TypingAny] = Field(
        default_factory=dict,
        description="kind → TResult map answering needs_input keys",
    )
    # Accepted for older clients; copied into user_inputs["location"].
    confirmed_location: Optional[LocationResult] = Field(
        default=None,
        description="Deprecated: use user_inputs['location'] instead",
    )

    @model_validator(mode="after")
    def merge_confirmed_location_into_user_inputs(self) -> "ChatResumeMessage":
        if self.confirmed_location is not None and "location" not in self.user_inputs:
            self.user_inputs = {
                **self.user_inputs,
                "location": self.confirmed_location.to_dict(),
            }
        if not self.user_inputs:
            raise ValueError("user_inputs must be non-empty (or provide confirmed_location)")
        return self


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
    result: dict[str, Any] = Field(..., description="Tool result data")
    artifacts: ToolArtifacts = Field(default=ToolArtifacts(), description="Artifacts")
    step_id: Optional[str] = Field(default=None, description="Planned tool step id")
    domain: Optional[str] = Field(default=None, description="Domain that ran the tool")
    execution_time_seconds: Optional[float] = Field(
        default=None, description="Wall-clock execution time in seconds"
    )


class UserInputRequestMessage(BaseModel):
    """Request for the client to collect one or more user inputs."""

    type: str = Field(default=ServerMessageType.USER_INPUT_REQUEST.value)
    needs_input: dict[str, TypingAny] = Field(
        ...,
        description="kind → TRequest map; non-empty means the agent is paused",
    )
    pause_state: dict[str, Any] = Field(
        ..., description="Opaque pause reference (conversation_id)"
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
