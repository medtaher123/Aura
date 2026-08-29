"""Resolve / disambiguate place before router and domain tools."""

from __future__ import annotations

from typing import Any

from eo_llm.adapters.bedrock import LocationHint
from eo_llm.adapters.bedrock.chat_history_context import get_chat_history
from eo_llm.adapters.bedrock.llm_model_router import LLMModelRouter
from eo_llm.graph.geocode import search_location_candidates
from eo_llm.graph.nodes.base import GraphNode
from eo_llm.graph.nodes.helpers import resolved_location_from_candidate
from eo_llm.graph.state import (
    GraphState,
    ResolvedLocationModel,
    dump_state,
    GraphStateModel,
)
from eo_llm.prompts import get_query_location_prompt
from src.user_inputs import LocationRequest, UserInputRouter

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
    parts = [p for p in (place or "").strip().split() if p]
    if len(parts) < 2:
        return ""
    last = parts[-1].lower().strip(".,;:")
    if last not in _PLACE_FEATURE_SUFFIXES:
        return ""
    return " ".join(parts[:-1]).strip(" ,")


def _is_country_candidate(c: dict[str, Any]) -> bool:
    addresstype = str(c.get("addresstype") or "").strip().lower()
    place_type = str(c.get("type") or "").strip().lower()
    class_name = str(c.get("class") or "").strip().lower()
    if addresstype == "country":
        return True
    if place_type == "country":
        return True
    if class_name == "boundary" and place_type == "administrative" and addresstype == "country":
        return True
    return False


class LocationGateNode(GraphNode):
    node_name = "location_gate"
    status_stage = "planning"
    status_message = "Resolving location..."

    def serialize_hitl_blob(self, s: GraphStateModel) -> dict[str, Any]:
        return {
            "location_query": s.location_query,
            "location_candidates": list(s.location_candidates or []),
        }

    def apply_hitl_blob(
        self,
        s: GraphStateModel,
        blob: dict[str, Any],
    ) -> GraphStateModel:
        s.location_query = str(blob.get("location_query") or s.location_query or "")
        candidates = blob.get("location_candidates")
        if isinstance(candidates, list):
            s.location_candidates = [c for c in candidates if isinstance(c, dict)]
        return s

    async def run(self, s: GraphStateModel) -> GraphState:
        blob = self.load_hitl_blob()
        if blob:
            s = self.apply_hitl_blob(s, blob)
        if s.has_resolved_location:
            return dump_state(s)

        place = (s.place_hint or s.location_query).strip()
        if not place:
            place = await self._extract_location_hint()
        s.location_query = place

        if not place:
            s.resolved_location = ResolvedLocationModel()
            s.location_candidates = []
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
            return dump_state(s)

        if len(found) == 1:
            s.location_candidates = found
            s.resolved_location = resolved_location_from_candidate(found[0])
            return dump_state(s)

        if all(_is_country_candidate(c) for c in found):
            s.location_candidates = found
            s.resolved_location = resolved_location_from_candidate(found[0])
            return dump_state(s)

        s.location_candidates = found
        s.resolved_location = ResolvedLocationModel()
        location_request = LocationRequest.from_candidates(
            found,
            prompt="Several places match your query. Please choose a location.",
            location_query=place,
        )
        needs_input = UserInputRouter.requests_to_dict({"location": location_request})
        s = await self.pause_for_hitl(
            s,
            {
                "data": {"needs_input": needs_input},
                "prompt": location_request.prompt,
            },
            blob=self.serialize_hitl_blob(s),
        )
        return dump_state(s)

    async def _extract_location_hint(self) -> str:
        response = await LLMModelRouter().call_structured(
            system_prompt=get_query_location_prompt(),
            response_model=LocationHint,
            schema_name="location_hint",
            schema_description="Geocodable place extracted from user query",
            max_tokens=120,
            chat_history=get_chat_history(),
        )
        return response.place_query.strip() if response else ""


location_gate_node = LocationGateNode()
