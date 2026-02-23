"""Agent runner module.

Provides a unified interface for invoking agent executors.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Callable

from ..core.logger import get_logger
from ..tools.contracts import ToolResponse

logger = get_logger("agent_runner")


def invoke_agent(
    executor: Any,
    english_query: str,
    *,
    chat_history: Any = None,
    resume: Any = None,
    stream_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Any:
    """
    Single place that defines the agent contract used by the API:
    - Call: executor.invoke({"input": english_query, "chat_history": [...]})
    - Prefer returning response["output"] when available
    - Otherwise return the raw response (for future flexibility)
    """
    payload: Dict[str, Any] = {"input": english_query}
    if chat_history is not None:
        payload["chat_history"] = chat_history
    if resume is not None:
        payload["resume"] = resume
        logger.info(f"Invoking agent with resume - has_resume_state: {'resume_state' in resume}, has_orchestrator_trace: {'orchestrator_trace' in resume}")
    else:
        logger.info(f"Invoking agent with new request - query length: {len(english_query)}, has_history: {chat_history is not None}")
    
    if stream_callback is not None:
        payload["stream_callback"] = stream_callback

    response = executor.invoke(payload)
    
    logger.debug(f"Agent invocation completed - response type: {type(response)}")

    if isinstance(response, dict):
        return response.get("output", response)
    return response


def coerce_tool_response(obj: Any) -> ToolResponse:
    """Normalize agent outputs into the standardized ToolResponse."""

    if isinstance(obj, ToolResponse):
        return obj

    if (
        isinstance(obj, dict)
        and "message" in obj
        and "artifacts" in obj
        and "tool_name" in obj
        and "error" in obj
    ):
        from ..tools.contracts import ToolArtifacts

        artifacts_raw = obj.get("artifacts") or {}
        if isinstance(artifacts_raw, dict):
            artifacts_raw.setdefault("maps", [])
            artifacts_raw.setdefault("thumbnails", [])
            artifacts_raw.setdefault("urls", [])
        artifacts = (
            artifacts_raw
            if isinstance(artifacts_raw, ToolArtifacts)
            else ToolArtifacts(**artifacts_raw)
        )

        logger.debug(
            f"Coerced dict tool response - tool: {obj.get('tool_name')}, error: {obj.get('error')}"
        )
        return ToolResponse(
            tool_name=obj.get("tool_name", "unknown"),
            message=obj.get("message", ""),
            artifacts=artifacts,
            error=obj.get("error", False),
            data=obj.get("data", {}),
            start_date=obj.get("start_date"),
            end_date=obj.get("end_date"),
            country=obj.get("country"),
            city=obj.get("city"),
            coordinates=obj.get("coordinates"),
        )

    logger.debug(f"Coercing non-standard response - type: {type(obj)}")
    if isinstance(obj, dict):
        message = obj.get("message")
        if not isinstance(message, str):
            message = str(obj)
    else:
        message = str(obj)

    return ToolResponse(
        tool_name="unknown",
        message=message,
        error=False,
    )
