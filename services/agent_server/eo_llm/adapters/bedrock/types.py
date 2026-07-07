"""Routing type aliases for Bedrock LLM orchestration."""

from __future__ import annotations

from typing import Any, Callable, Literal

RouteDomain = Literal[
    "flood_damage",
    "fire_detection",
    "disaster_detection",
    "infrastructure",
    "stac",
    "document_qa",
    "tools_info",
    "websearch_only",
]
ExecutionMode = Literal["parallel", "sequential"]
RouteDecider = Callable[[str], Any]
