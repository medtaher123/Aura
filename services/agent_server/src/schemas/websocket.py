"""
WebSocket Message Models for Agent Server

Defines the message protocol for client-server communication.
"""

from enum import Enum
import uuid
from typing_extensions import Any, Callable, Literal, Optional, TypedDict
from pydantic import AliasChoices, BaseModel, Field

from src.tools.contracts import ToolArtifacts


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
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    LOCATION_CONFIRMATION = "location_confirmation"
    CONVERSATION_TITLE = "conversation_title"
    COMPLETE = "complete"
    ERROR = "error"


class AgentStage(str, Enum):
    """Stages of agent processing."""

    PLANNING = "planning"
    TOOL_CALL = "tool_call"
    ANALYZING = "analyzing"


# =============================================================================
# Orchestrator Types
# =============================================================================


class OrchestratorTrace(TypedDict, total=False):
    """Trace information from orchestrator planning phase."""

    needs_data: bool
    needs_analysis: bool
    data_query: str
    analysis_goal: str


class ResumeState(TypedDict, total=False):
    """State for resuming a paused orchestrator execution."""

    resume_state: dict[str, Any]
    orchestrator_trace: OrchestratorTrace
    needs_analysis: bool
    analysis_goal: str
    user_text: str


class OrchestratorInputs(TypedDict, total=False):
    """Input parameters for orchestrator executor invoke method."""

    input: str
    chat_history: list["ChatMessage"] | None
    stream_callback: Callable[[dict[str, Any]], None] | None
    resume: ResumeState | None


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


OSMType = Literal["relation", "way", "node"]
# mapper from OSMType to its first letter capitalized
OSMPrefixType = Literal["R", "W", "N"]


def get_osm_type_prefix(osm_type: OSMType) -> Optional[OSMPrefixType]:
    match osm_type:
        case "relation":
            return "R"
        case "way":
            return "W"
        case "node":
            return "N"
        case _:
            return None


class LocationOption(BaseModel):
    """A location option for disambiguation."""

    name: str = Field(..., description="Location display name")
    coordinates: list[float] = Field(..., description="[lat, lon] coordinates")
    place_id: Optional[int] = Field(default=None, description="Place ID")
    osm_id: Optional[int] = Field(default=None, description="OSM ID")
    osm_type: Optional[OSMType] = Field(default=None, description="OSM type")
    osm_type_prefix: Optional[OSMPrefixType] = Field(
        default=None, description="OSM type prefix"
    )


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


class ChatResumeMessage(BaseModel):
    """Client request to resume after location confirmation."""

    type: str = Field(default=ClientMessageType.CHAT_RESUME.value)
    confirmed_location: LocationOption = Field(
        ..., description="The location the user confirmed"
    )
    pause_state: dict[str, Any] = Field(
        ..., description="Serialized agent state from location_confirmation message"
    )


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


class ToolStartMessage(BaseModel):
    """Notification that a tool is being executed."""

    type: str = Field(default=ServerMessageType.TOOL_START.value)
    tool_name: str = Field(..., description="Name of the tool being called")
    tool_input: dict[str, Any] = Field(..., description="Tool input parameters")


class ToolResultMessage(BaseModel):
    """Result from tool execution."""

    type: str = Field(default=ServerMessageType.TOOL_RESULT.value)
    tool_name: str = Field(..., description="Name of the tool that was called")
    result: dict[str, Any] = Field(..., description="Tool result data")
    artifacts: ToolArtifacts = Field(default=ToolArtifacts(), description="Artifacts")


class LocationConfirmationMessage(BaseModel):
    """Request for user to confirm ambiguous location."""

    type: str = Field(default=ServerMessageType.LOCATION_CONFIRMATION.value)
    options: list[LocationOption] = Field(
        ..., description="Location options for user to choose from"
    )
    pause_state: dict[str, Any] = Field(
        ..., description="Serialized agent state to resume after confirmation"
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


class ErrorMessage(BaseModel):
    """Error message."""

    type: str = Field(default=ServerMessageType.ERROR.value)
    message: str = Field(..., description="Error description")
    recoverable: bool = Field(default=True, description="Whether the client can retry")


# =============================================================================
# Union Types for Parsing
# =============================================================================

# Type alias for any server message
ServerMessage = (
    ConnectionAckMessage
    | TokenMessage
    | StatusMessage
    | ToolStartMessage
    | ToolResultMessage
    | LocationConfirmationMessage
    | ConversationTitleMessage
    | CompleteMessage
    | ErrorMessage
)

# Type alias for any client message
ClientMessage = ChatRequestMessage | ChatResumeMessage | CancelMessage
