"""Clients for external service communication."""

from .agent_ws_client import (
    ChatMessage,
    LocationOption,
)

__all__ = [
    "ChatMessage",
    "LocationOption",
    "AgentResponse",
    "RemoteAgentAdapter",
    "get_shared_agent_adapter",
]

_ADAPTER_NAMES = {"AgentResponse", "RemoteAgentAdapter", "get_shared_agent_adapter"}


def __getattr__(name: str):
    if name in _ADAPTER_NAMES:
        from .agent_adapter import (
            AgentResponse,
            RemoteAgentAdapter,
            get_shared_agent_adapter,
        )
        globals().update({
            "AgentResponse": AgentResponse,
            "RemoteAgentAdapter": RemoteAgentAdapter,
            "get_shared_agent_adapter": get_shared_agent_adapter,
        })
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
