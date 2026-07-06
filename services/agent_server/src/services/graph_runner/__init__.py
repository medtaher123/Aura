"""Graph runner service.

Drives the ported EO_LLM LangGraph pipeline (`eo_llm.graph`) from the agent
server and adapts it to the existing WebSocket contract:

- Streams per-node status events and per-tool start/done events so the UI
  behaves exactly like the legacy orchestrator pipeline.
- Maps the final `GraphState` into a `ToolResponse` (including artifact merging
  and the location-confirmation pause payload).
"""

from __future__ import annotations

from typing import Any

from .models import ChatMessage, GraphResumeRequest, GraphTurnRequest, StreamCallback
from .service import GraphRunnerService

_default_service: GraphRunnerService | None = None


def get_graph_runner_service() -> GraphRunnerService:
    global _default_service
    if _default_service is None:
        _default_service = GraphRunnerService()
    return _default_service


def run_graph_turn(
    *,
    english_query: str,
    user_id: str,
    session_id: str,
    document_ref: dict[str, Any] | None = None,
    place_hint: str | None = None,
    chat_history: list[dict[str, str]] | None = None,
    stream_callback: StreamCallback | None = None,
) -> Any:
    """Run one graph turn and return a ToolResponse for the websocket layer."""
    history = [
        ChatMessage(role=str(item.get("role") or "assistant"), content=str(item.get("content") or ""))
        for item in (chat_history or [])
        if isinstance(item, dict)
    ]
    request = GraphTurnRequest(
        english_query=english_query,
        user_id=user_id,
        session_id=session_id,
        document_ref=document_ref or {},
        place_hint=place_hint,
        chat_history=history,
        stream_callback=stream_callback,
    )
    return get_graph_runner_service().run_turn(request)


def resume_graph_turn(
    *,
    graph_state: dict[str, Any],
    confirmed_index: int,
    stream_callback: StreamCallback | None = None,
) -> Any:
    """Resume a paused graph after the user confirmed a location."""
    request = GraphResumeRequest(
        graph_state=graph_state,
        confirmed_index=confirmed_index,
        stream_callback=stream_callback,
    )
    return get_graph_runner_service().resume_turn(request)


def match_location_index(
    candidates: list[dict[str, Any]], confirmed_location: Any
) -> int:
    """Find the index of the confirmed location within the candidate list.

    `confirmed_location` is a websocket LocationOption (osm_id/place_id/name/
    coordinates). Falls back to 0 when no robust match is found.
    """
    if not candidates:
        return 0

    osm_id = getattr(confirmed_location, "osm_id", None)
    place_id = getattr(confirmed_location, "place_id", None)
    name = (getattr(confirmed_location, "name", "") or "").strip().lower()
    coords = getattr(confirmed_location, "coordinates", None) or []

    if osm_id is not None:
        for i, c in enumerate(candidates):
            if c.get("osm_id") == osm_id:
                return i
    if place_id is not None:
        for i, c in enumerate(candidates):
            if c.get("place_id") == place_id:
                return i
    if name:
        for i, c in enumerate(candidates):
            cand_name = str(c.get("display_name") or c.get("name") or "").strip().lower()
            if cand_name == name:
                return i
    if isinstance(coords, list) and len(coords) == 2:
        try:
            lat, lon = float(coords[0]), float(coords[1])
            best_i, best_d = 0, float("inf")
            for i, c in enumerate(candidates):
                clat, clon = c.get("lat"), c.get("lon")
                if isinstance(clat, (int, float)) and isinstance(clon, (int, float)):
                    d = (float(clat) - lat) ** 2 + (float(clon) - lon) ** 2
                    if d < best_d:
                        best_i, best_d = i, d
            return best_i
        except (TypeError, ValueError):
            return 0
    return 0


__all__ = [
    "ChatMessage",
    "GraphResumeRequest",
    "GraphRunnerService",
    "GraphTurnRequest",
    "StreamCallback",
    "get_graph_runner_service",
    "match_location_index",
    "resume_graph_turn",
    "run_graph_turn",
]
