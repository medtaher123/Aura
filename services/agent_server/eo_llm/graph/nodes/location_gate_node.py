"""Resolve / disambiguate place before router and domain tools."""

from __future__ import annotations

from typing import Any

from eo_llm.graph.geocode import search_location_candidates
from eo_llm.graph.nodes.base import GraphNode
from eo_llm.graph.state import (
    GraphState,
    ResolvedLocationModel,
    dump_state,
    GraphStateModel,
)


def _candidate_to_resolved(c: dict[str, Any]) -> ResolvedLocationModel:
    lat, lon = c.get("lat"), c.get("lon")
    lat_f = float(lat) if lat is not None else None
    lon_f = float(lon) if lon is not None else None

    out: dict[str, Any] = {
        "display_name": str(c.get("display_name") or c.get("name") or ""),
        "lat": lat_f,
        "lon": lon_f,
    }
    bbox = c.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        out["bbox"] = [float(x) for x in bbox]
    return ResolvedLocationModel.model_validate(out)


def _is_country_candidate(c: dict[str, Any]) -> bool:
    addresstype = str(c.get("addresstype") or "").strip().lower()
    place_type = str(c.get("type") or "").strip().lower()
    class_name = str(c.get("class") or "").strip().lower()
    if addresstype == "country":
        return True
    if place_type == "country":
        return True
    # Nominatim often represents countries as administrative boundaries.
    if class_name == "boundary" and place_type == "administrative" and addresstype == "country":
        return True
    return False


class LocationGateNode(GraphNode):
    node_name = "location_gate"
    status_stage = "planning"
    status_message = "Resolving location..."

    def run(self, s: GraphStateModel) -> GraphState:
        # Resume: user picked a candidate index (same session state returned by the client).
        idx = s.confirmed_location_index
        candidates = list(s.location_candidates)
        resuming = s.needs_location_confirmation
        if (
            resuming
            and isinstance(idx, int)
            and idx >= 0
            and candidates
            and idx < len(candidates)
        ):
            s.resolved_location = _candidate_to_resolved(candidates[idx])
            s.needs_location_confirmation = False
            s.stopped_for_location_confirmation = False
            s.confirmed_location_index = None
            s.location_phase = "router"
            return dump_state(s)

        # Already resolved earlier in the same run (should not re-geocode).
        if s.has_resolved_location and not s.needs_location_confirmation:
            s.location_phase = "router"
            s.stopped_for_location_confirmation = False
            return dump_state(s)

        # Location source priority:
        # explicit place hint -> existing location query -> LLM-extracted place from query.
        place = (s.place_hint or s.location_query).strip()
        if not place:
            place = self._adapter.extract_location_hint(query=s.query)
        s.location_query = place

        if not place:
            s.resolved_location = ResolvedLocationModel()
            s.location_candidates = []
            s.needs_location_confirmation = False
            s.location_phase = "router"
            s.stopped_for_location_confirmation = False
            return dump_state(s)

        found = search_location_candidates(place, limit=8)

        if not found:
            s.resolved_location = ResolvedLocationModel()
            s.location_candidates = []
            s.needs_location_confirmation = False
            s.location_phase = "router"
            s.stopped_for_location_confirmation = False
            return dump_state(s)

        # Skip confirmation when geocoding is unambiguous (single hit).
        if len(found) == 1:
            s.location_candidates = found
            s.resolved_location = _candidate_to_resolved(found[0])
            s.needs_location_confirmation = False
            s.location_phase = "router"
            s.stopped_for_location_confirmation = False
            return dump_state(s)

        # Country-level matches should not block user flow with confirmation.
        if all(_is_country_candidate(c) for c in found):
            s.location_candidates = found
            s.resolved_location = _candidate_to_resolved(found[0])
            s.needs_location_confirmation = False
            s.location_phase = "router"
            s.stopped_for_location_confirmation = False
            return dump_state(s)

        s.location_candidates = found
        s.resolved_location = ResolvedLocationModel()
        s.needs_location_confirmation = True
        s.location_phase = "pause"
        s.stopped_for_location_confirmation = True
        return dump_state(s)


location_gate_node = LocationGateNode()
