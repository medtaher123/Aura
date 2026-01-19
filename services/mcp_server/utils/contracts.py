"""
MCP Tool Contracts and Helpers

Shared utilities for MCP tools to maintain consistent response format.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, TypedDict
import json


class ToolArtifacts(TypedDict):
    """Artifacts that can be rendered in UI"""

    maps: List[Any]
    thumbnails: List[str]
    urls: List[str]


class ToolCoordinates(TypedDict):
    """Geographic coordinates"""

    lat: float
    lon: float


class ToolResponse(TypedDict):
    """Standardized tool response format"""

    message: str
    artifacts: ToolArtifacts
    tool_name: str
    start_date: Optional[str]
    end_date: Optional[str]
    country: Optional[str]
    city: Optional[str]
    coordinates: Optional[ToolCoordinates]
    data: Optional[Dict[str, Any]]
    error: bool


def make_tool_response(
    *,
    tool_name: str,
    message: str,
    artifacts: Optional[ToolArtifacts] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    country: Optional[str] = None,
    city: Optional[str] = None,
    coordinates: Optional[ToolCoordinates] = None,
    data: Optional[Dict[str, Any]] = None,
    error: bool = False,
) -> ToolResponse:
    """Create a standardized ToolResponse dict.

    Notes:
    - Always return all keys (UI and agent logic depends on that).
    - Put tool-specific payloads in `data`.
    - Put any renderable assets in `artifacts`.
    """
    normalized_artifacts: ToolArtifacts = artifacts or {
        "maps": [],
        "thumbnails": [],
        "urls": [],
    }
    # Defensive normalization
    normalized_artifacts.setdefault("maps", [])
    normalized_artifacts.setdefault("thumbnails", [])
    normalized_artifacts.setdefault("urls", [])

    return {
        "message": message,
        "artifacts": normalized_artifacts,
        "tool_name": tool_name,
        "start_date": start_date,
        "end_date": end_date,
        "country": country,
        "city": city,
        "coordinates": coordinates,
        "data": data,
        "error": bool(error),
    }


def format_mcp_response(tool_response: ToolResponse) -> str:
    """Format tool response as JSON for MCP"""
    return json.dumps(tool_response, indent=2, default=str)
