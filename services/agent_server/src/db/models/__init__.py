"""ORM model package.

Importing this package registers all mapped classes on ``Base.metadata`` for
Alembic autogenerate.
"""

from .message import (
    AssistantMessage,
    InputRequestMessage,
    InputResponseMessage,
    Message,
    MessageKind,
    MessageRole,
    UserMessage,
)
from .message_attachments import (
    FileAttachment,
    LocationAttachment,
    MessageAttachment,
    parse_attachments,
)
from .agent_profile import AgentProfile, AgentToolBinding
from .conversation import Conversation
from .file import File
from .mcp_server import McpServer
from .tool_definition import ToolDefinition
from .user import User

__all__ = [
    "User",
    "Conversation",
    "File",
    "McpServer",
    "ToolDefinition",
    "AgentProfile",
    "AgentToolBinding",
    "Message",
    "MessageKind",
    "MessageRole",
    "UserMessage",
    "AssistantMessage",
    "InputRequestMessage",
    "InputResponseMessage",
    "MessageAttachment",
    "LocationAttachment",
    "FileAttachment",
    "parse_attachments",
]
