from __future__ import annotations

from typing import Any, Dict

from src.tools.contracts import ToolResponse, make_tool_response


def invoke_agent(executor: Any, english_query: str) -> Any:
    """
    Single place that defines the agent contract used by the UI:
    - Call: executor.invoke({"input": english_query})
    - Prefer returning response["output"] when available
    - Otherwise return the raw response (for future flexibility)
    """
    response = executor.invoke({"input": english_query})

    if isinstance(response, dict):
        return response.get("output", response)
    return response


def coerce_tool_response(obj: Any) -> ToolResponse:
    """Normalize agent outputs into the standardized ToolResponse dict shape."""

    if (
        isinstance(obj, dict)
        and "message" in obj
        and "artifacts" in obj
        and "tool_name" in obj
        and "error" in obj
    ):
        # Best-effort normalization of artifacts keys
        artifacts = obj.get("artifacts") or {"maps": [], "thumbnails": [], "urls": []}
        if isinstance(artifacts, dict):
            artifacts.setdefault("maps", [])
            artifacts.setdefault("thumbnails", [])
            artifacts.setdefault("urls", [])
        obj["artifacts"] = artifacts
        return obj  # type: ignore[return-value]

    # Legacy tool outputs (string or partial dict)
    if isinstance(obj, dict):
        message = obj.get("message")
        if not isinstance(message, str):
            message = str(obj)
    else:
        message = str(obj)

    return make_tool_response(
        tool_name="unknown",
        message=message,
        artifacts={"maps": [], "thumbnails": [], "urls": []},
        start_date=None,
        end_date=None,
        country=None,
        city=None,
        coordinates=None,
        data=None,
        error=False,
    )