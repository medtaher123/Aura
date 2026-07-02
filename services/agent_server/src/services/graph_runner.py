"""Graph runner service.

Drives the ported EO_LLM LangGraph pipeline (`eo_llm.graph`) from the agent
server and adapts it to the existing WebSocket contract:

- Streams per-node status events and per-tool start/done events so the UI
  behaves exactly like the legacy orchestrator pipeline.
- Maps the final `GraphState` into a `ToolResponse` (including artifact merging
  and the location-confirmation pause payload).
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from eo_llm.adapters.mcp_client import reset_stream_callback, set_stream_callback
from eo_llm.graph.builder import build_graph

from ..core.logger import get_logger
from ..tools.contracts import ToolArtifacts, ToolResponse

logger = get_logger("graph_runner")

StreamCallback = Callable[[dict[str, Any]], None]

# Map each graph node to the user-facing status it should surface. The stage
# strings match `AgentStage` values consumed by the websocket layer.
_NODE_STATUS: dict[str, tuple[str, str]] = {
    "orchestrator": ("planning", "Planning your request..."),
    "location_gate": ("planning", "Resolving location..."),
    "router": ("planning", "Selecting domains..."),
    "flood_damage": ("tool_call", "Analyzing flood damage..."),
    "fire_detection": ("tool_call", "Detecting fires..."),
    "disaster_detection": ("tool_call", "Querying disaster events..."),
    "document_qa": ("tool_call", "Reading the document..."),
    "infrastructure": ("tool_call", "Querying infrastructure..."),
    "stac": ("tool_call", "Searching the satellite catalog..."),
    "web_search": ("tool_call", "Searching the web..."),
    "aggregator": ("analyzing", "Aggregating evidence..."),
    "finalizer": ("analyzing", "Composing the final answer..."),
}


_GRAPH: Any = None


def _get_graph() -> Any:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


# ---------------------------------------------------------------------------
# Query contextualization (mirrors EO_LLM runtime, minus AgentCore memory)
# ---------------------------------------------------------------------------


def _contextualize_query(
    query: str, chat_history: Optional[list[dict[str, str]]]
) -> str:
    q = (query or "").strip()
    if not q:
        return ""
    recent = (chat_history or [])[-6:]
    if not recent:
        return q
    lines: list[str] = [f"Current user message: {q}", "Recent conversation:"]
    for item in recent:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "assistant").upper()
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(f"- {role}: {content}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Streaming graph execution
# ---------------------------------------------------------------------------


def _emit_status(
    stream_callback: Optional[StreamCallback],
    node_name: str,
    emitted: set[str],
) -> None:
    if stream_callback is None or node_name in emitted:
        return
    emitted.add(node_name)
    spec = _NODE_STATUS.get(node_name)
    if spec is None:
        return
    stage, message = spec
    try:
        stream_callback({"type": "graph_status", "stage": stage, "message": message})
    except Exception:
        logger.debug("graph status stream callback failed", exc_info=True)


def _run_streaming(
    state: dict[str, Any], stream_callback: Optional[StreamCallback]
) -> dict[str, Any]:
    graph = _get_graph()
    emitted: set[str] = set()
    final_state: dict[str, Any] = dict(state)

    token = None
    if stream_callback is not None:
        token = set_stream_callback(stream_callback)
    try:
        for mode, chunk in graph.stream(state, stream_mode=["updates", "values"]):
            if mode == "updates" and isinstance(chunk, dict):
                for node_name in chunk:
                    _emit_status(stream_callback, node_name, emitted)
            elif mode == "values" and isinstance(chunk, dict):
                final_state = chunk
    finally:
        if token is not None:
            reset_stream_callback(token)
    return final_state


# ---------------------------------------------------------------------------
# Artifact merging (ported from data_agent_service._merge_steps_into_response)
# ---------------------------------------------------------------------------


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="python")
        except Exception:
            return {}
    return {}


def _is_pydeck_spec(x: Any) -> bool:
    return isinstance(x, dict) and (
        isinstance(x.get("layers"), list) or isinstance(x.get("points"), list)
    )


def _layers_from_spec(spec: dict) -> list[dict]:
    layers: list[dict] = []
    layer_specs = spec.get("layers")
    if isinstance(layer_specs, list):
        layers.extend([x for x in layer_specs if isinstance(x, dict)])
    points = spec.get("points")
    if isinstance(points, list):
        layers.append(
            {
                "type": "ScatterplotLayer",
                "data": points,
                "get_position": spec.get("get_position", "[lon, lat]"),
                "get_radius": spec.get("radius", 50),
                "radius_units": spec.get("radius_units", "meters"),
                "radius_min_pixels": spec.get("radius_min_pixels", 3),
                "radius_max_pixels": spec.get("radius_max_pixels", 15),
                "get_fill_color": spec.get("fill_color", [255, 0, 0, 160]),
                "pickable": bool(spec.get("pickable", True)),
            }
        )
    return layers


def _dedup(xs: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _merge_artifacts(
    artifact_dicts: list[dict[str, Any]], extra_urls: list[str]
) -> ToolArtifacts:
    maps_str: list[str] = []
    maps_other: list[Any] = []
    thumbs: list[str] = []
    urls: list[str] = []

    for a in artifact_dicts:
        for x in a.get("maps", []) or []:
            if isinstance(x, str):
                maps_str.append(x)
            elif isinstance(x, dict):
                maps_other.append(x)
        thumbs.extend([x for x in (a.get("thumbnails", []) or []) if isinstance(x, str)])
        urls.extend([x for x in (a.get("urls", []) or []) if isinstance(x, str)])

    urls.extend([u for u in extra_urls if isinstance(u, str) and u.strip()])

    maps_str = _dedup(maps_str)
    thumbs = _dedup(thumbs)
    urls = _dedup(urls)

    pydeck_specs: list[dict] = [m for m in maps_other if _is_pydeck_spec(m)]
    non_pydeck_specs: list[Any] = [m for m in maps_other if not _is_pydeck_spec(m)]

    combined_specs: list[Any] = []
    if len(pydeck_specs) >= 2:
        base = dict(pydeck_specs[0])
        combined_layers: list[dict] = []
        titles: list[str] = []
        tooltip = base.get("tooltip") if isinstance(base.get("tooltip"), dict) else None
        for spec in pydeck_specs:
            combined_layers.extend(_layers_from_spec(spec))
            title = spec.get("title")
            if isinstance(title, str) and title.strip():
                titles.append(title.strip())
            if tooltip is None and isinstance(spec.get("tooltip"), dict):
                tooltip = spec.get("tooltip")
        seen_titles: set[str] = set()
        titles = [t for t in titles if not (t in seen_titles or seen_titles.add(t))]
        if titles:
            base["title"] = " + ".join(titles)
        if tooltip is not None:
            base["tooltip"] = tooltip
        for key in (
            "points",
            "fill_color",
            "radius",
            "radius_units",
            "radius_min_pixels",
            "radius_max_pixels",
            "get_position",
        ):
            base.pop(key, None)
        base["layers"] = combined_layers
        combined_specs.append(base)
    elif len(pydeck_specs) == 1:
        combined_specs.append(pydeck_specs[0])

    combined_specs.extend(non_pydeck_specs)
    merged_maps: list[Any] = [*maps_str, *combined_specs]
    return ToolArtifacts(maps=merged_maps, thumbnails=thumbs, urls=urls)


def _artifacts_from_state(state: dict[str, Any]) -> ToolArtifacts:
    artifact_dicts: list[dict[str, Any]] = []
    domain_results = state.get("domain_results") or {}
    if isinstance(domain_results, dict):
        for dr in domain_results.values():
            dr = _as_dict(dr)
            executions = dr.get("executions") or []
            collected = False
            if isinstance(executions, list):
                for ex in executions:
                    ex = _as_dict(ex)
                    res = ex.get("result")
                    if isinstance(res, dict) and isinstance(res.get("artifacts"), dict):
                        artifact_dicts.append(res["artifacts"])
                        collected = True
            # Fallback to the single final result if no per-step results carried artifacts.
            if not collected:
                res = dr.get("result")
                if isinstance(res, dict) and isinstance(res.get("artifacts"), dict):
                    artifact_dicts.append(res["artifacts"])

    web_urls: list[str] = []
    for w in state.get("web_results") or []:
        if isinstance(w, dict):
            u = w.get("url")
            if isinstance(u, str) and u.strip():
                web_urls.append(u.strip())

    return _merge_artifacts(artifact_dicts, web_urls)


# ---------------------------------------------------------------------------
# GraphState -> ToolResponse mapping
# ---------------------------------------------------------------------------


def _json_safe(value: Any) -> Any:
    """Make a graph state JSON-serializable for round-tripping through the client."""
    return json.loads(json.dumps(value, default=str))


def _location_pause_response(state: dict[str, Any]) -> ToolResponse:
    candidates = state.get("location_candidates") or []
    graph_state = _json_safe(state)
    return ToolResponse(
        tool_name="graph",
        message="Several places match your query. Please choose a location.",
        error=False,
        data={
            "needs_location_confirmation": True,
            "candidates": candidates,
            "pause": {"graph_state": graph_state},
        },
    )


def _coordinates_from_state(state: dict[str, Any]):
    resolved = state.get("resolved_location")
    if not isinstance(resolved, dict):
        return None, None
    lat = resolved.get("lat")
    lon = resolved.get("lon")
    display = resolved.get("display_name") or None
    coords = None
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        coords = {"lat": float(lat), "lon": float(lon)}
    return coords, display


def _state_to_tool_response(state: dict[str, Any]) -> ToolResponse:
    if state.get("stopped_for_location_confirmation"):
        return _location_pause_response(state)

    message = (state.get("final_answer") or "").strip()
    artifacts = _artifacts_from_state(state)
    coords, city = _coordinates_from_state(state)
    return ToolResponse(
        tool_name="graph",
        message=message or "I couldn't produce an answer for that request.",
        artifacts=artifacts,
        city=city,
        coordinates=coords,
        error=not message,
        data={
            "answer_source": state.get("answer_source"),
            "selected_domains": state.get("selected_domains", []),
        },
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_graph_turn(
    *,
    english_query: str,
    user_id: str,
    session_id: str,
    document_ref: Optional[dict[str, Any]] = None,
    place_hint: Optional[str] = None,
    chat_history: Optional[list[dict[str, str]]] = None,
    stream_callback: Optional[StreamCallback] = None,
) -> ToolResponse:
    """Run one graph turn and return a ToolResponse for the websocket layer."""
    state: dict[str, Any] = {
        "query": _contextualize_query(english_query, chat_history),
        "user_query": english_query,
        "user_id": user_id,
        "session_id": session_id,
        "document_ref": document_ref or {},
    }
    if place_hint and place_hint.strip():
        state["place_hint"] = place_hint.strip()

    logger.info(
        f"Graph turn starting - session_id: {session_id}, query length: {len(english_query)}"
    )
    final = _run_streaming(state, stream_callback)
    return _state_to_tool_response(final)


def resume_graph_turn(
    *,
    graph_state: dict[str, Any],
    confirmed_index: int,
    stream_callback: Optional[StreamCallback] = None,
) -> ToolResponse:
    """Resume a paused graph after the user confirmed a location."""
    merged = {**graph_state, "confirmed_location_index": int(confirmed_index)}
    logger.info(
        f"Graph resume starting - confirmed_index: {confirmed_index}, "
        f"candidates: {len(graph_state.get('location_candidates') or [])}"
    )
    final = _run_streaming(merged, stream_callback)
    return _state_to_tool_response(final)


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
