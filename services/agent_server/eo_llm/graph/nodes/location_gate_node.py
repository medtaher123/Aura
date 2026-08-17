"""Resolve / disambiguate place before router and domain tools."""

from __future__ import annotations

from typing import Any

from eo_llm.adapters.bedrock import LocationHint
from eo_llm.adapters.bedrock.chat_history_context import get_chat_history
from eo_llm.adapters.bedrock.llm_model_router import LLMModelRouter
from eo_llm.graph.geocode import search_location_candidates
from eo_llm.graph.nodes.base import GraphNode
from eo_llm.graph.state import (
    GraphState,
    ResolvedLocationModel,
    dump_state,
    GraphStateModel,
)
from eo_llm.prompts import get_query_location_prompt
from src.user_inputs import LocationRequest, UserInputRouter

# Trailing feature words that often make Nominatim return zero hits
# (e.g. "Fontainebleau forests" → retry as "Fontainebleau").
_PLACE_FEATURE_SUFFIXES = frozenset(
    {
        "forest",
        "forests",
        "foret",
        "forêt",
        "woods",
        "wood",
        "park",
        "parks",
        "mountain",
        "mountains",
        "valley",
        "region",
        "area",
        "areas",
        "bay",
        "lake",
        "river",
    }
)


def _simplify_place_query(place: str) -> str:
    """Drop a trailing geographic feature word for a Nominatim retry."""
    parts = [p for p in (place or "").strip().split() if p]
    if len(parts) < 2:
        return ""
    last = parts[-1].lower().strip(".,;:")
    if last not in _PLACE_FEATURE_SUFFIXES:
        return ""
    return " ".join(parts[:-1]).strip(" ,")


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


def _location_candidates_from_needs_input(s: GraphStateModel) -> list[dict[str, Any]]:
    payload = s.needs_input.get("location")
    if isinstance(payload, dict):
        candidates = payload.get("candidates")
        if isinstance(candidates, list) and candidates:
            return [c for c in candidates if isinstance(c, dict)]
    return list(s.location_candidates)


def _clear_user_input_pause(s: GraphStateModel) -> None:
    s.needs_input = {}
    s.stopped_for_user_input = False
    s.confirmed_location_index = None


class LocationGateNode(GraphNode):
    node_name = "location_gate"
    status_stage = "planning"
    status_message = "Resolving location..."

    async def run(self, s: GraphStateModel) -> GraphState:
        # Resume: user picked a candidate index (same session state returned by the client).
        idx = s.confirmed_location_index
        candidates = _location_candidates_from_needs_input(s)
        resuming = bool(s.needs_input.get("location"))
        if (
            resuming
            and isinstance(idx, int)
            and idx >= 0
            and candidates
            and idx < len(candidates)
        ):
            s.resolved_location = _candidate_to_resolved(candidates[idx])
            s.location_candidates = candidates
            _clear_user_input_pause(s)
            s.location_phase = "router"
            return dump_state(s)

        # Already resolved earlier in the same run (should not re-geocode).
        if s.has_resolved_location and not s.needs_input:
            s.location_phase = "router"
            s.stopped_for_user_input = False
            return dump_state(s)

        # Location source priority:
        # explicit place hint -> existing location query -> LLM-extracted place from query.
        place = (s.place_hint or s.location_query).strip()
        if not place:
            place = await self._extract_location_hint(query=s.query)
        s.location_query = place

        if not place:
            s.resolved_location = ResolvedLocationModel()
            s.location_candidates = []
            _clear_user_input_pause(s)
            s.location_phase = "router"
            return dump_state(s)

        found = await search_location_candidates(place, limit=8)
        if not found:
            simplified = _simplify_place_query(place)
            if simplified:
                found = await search_location_candidates(simplified, limit=8)
                if found:
                    s.location_query = simplified

        if not found:
            s.resolved_location = ResolvedLocationModel()
            s.location_candidates = []
            _clear_user_input_pause(s)
            s.location_phase = "router"
            return dump_state(s)

        # Skip confirmation when geocoding is unambiguous (single hit).
        if len(found) == 1:
            s.location_candidates = found
            s.resolved_location = _candidate_to_resolved(found[0])
            _clear_user_input_pause(s)
            s.location_phase = "router"
            return dump_state(s)

        # Country-level matches should not block user flow with confirmation.
        if all(_is_country_candidate(c) for c in found):
            s.location_candidates = found
            s.resolved_location = _candidate_to_resolved(found[0])
            _clear_user_input_pause(s)
            s.location_phase = "router"
            return dump_state(s)

        s.location_candidates = found
        s.resolved_location = ResolvedLocationModel()
        location_request = LocationRequest.from_candidates(
            found,
            prompt="Several places match your query. Please choose a location.",
            location_query=place,
        )
        s.needs_input = UserInputRouter.requests_to_dict({"location": location_request})
        s.location_phase = "pause"
        s.stopped_for_user_input = True
        return dump_state(s)

    async def _extract_location_hint(self, *, query: str) -> str:
        """Extract a geocodable place from a user query."""
        system_prompt, user_prompt = get_query_location_prompt(query=query)
        response = await LLMModelRouter().call_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=LocationHint,
            schema_name="location_hint",
            schema_description="Geocodable place extracted from user query",
            max_tokens=120,
            chat_history=get_chat_history(),
        )
        return response.place_query.strip() if response else ""


location_gate_node = LocationGateNode()
