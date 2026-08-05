"""Normalize agent / graph outputs into ToolResponse."""

from __future__ import annotations

from typing import Any

from ..core.logger import get_logger
from ..tools.contracts import ToolResponse

logger = get_logger("agent_runner")


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
