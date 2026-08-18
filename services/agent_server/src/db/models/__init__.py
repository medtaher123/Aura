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
from .conversation import Conversation
from .user import User

__all__ = [
    "User",
    "Conversation",
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
