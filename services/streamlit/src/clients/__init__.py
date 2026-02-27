"""Clients for external service communication."""

from .agent_ws_client import (
    AgentWebSocketClient,
    ChatMessage,
    ChatResponse,
    LocationOption,
)

__all__ = [
    "AgentWebSocketClient",
    "ChatMessage",
    "ChatResponse",
    "LocationOption",
    "AgentResponse",
    "RemoteAgentAdapter",
    "get_agent_adapter",
    "get_shared_agent_adapter",
]

_ADAPTER_NAMES = {"AgentResponse", "RemoteAgentAdapter", "get_agent_adapter", "get_shared_agent_adapter"}


def __getattr__(name: str):
    if name in _ADAPTER_NAMES:
        from .agent_adapter import (
            AgentResponse,
            RemoteAgentAdapter,
            get_agent_adapter,
            get_shared_agent_adapter,
        )
        globals().update({
            "AgentResponse": AgentResponse,
            "RemoteAgentAdapter": RemoteAgentAdapter,
            "get_agent_adapter": get_agent_adapter,
            "get_shared_agent_adapter": get_shared_agent_adapter,
        })
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
