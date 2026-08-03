"""Factory for mapping graph state into ToolResponse objects."""

from __future__ import annotations

import json
from typing import Any

from eo_llm.graph.state import DomainResultModel, GraphStateModel, validate_state
from src.schemas.user_inputs import LocationRequest, UserInputRouter

from ...tools.contracts import ToolArtifacts, ToolCoordinates, ToolResponse
from .artifacts import ArtifactAggregator
from .models import ArtifactBundle


def _json_safe(value: Any) -> Any:
    """Make a graph state JSON-serializable for round-tripping through the client."""
    return json.loads(json.dumps(value, default=str))


class ToolResponseFactory:
    def __init__(self, aggregator: ArtifactAggregator | None = None):
        self._aggregator = aggregator or ArtifactAggregator()

    def from_state(self, state: GraphStateModel | dict[str, Any]) -> ToolResponse:
        model = state if isinstance(state, GraphStateModel) else validate_state(state)
        if model.stopped_for_user_input and model.needs_input:
            return self.from_paused_state(model)
        return self.from_completed_state(model)

    @staticmethod
    def from_paused_state(state: GraphStateModel) -> ToolResponse:
        graph_state = _json_safe(state.model_dump(mode="python"))
        requests = UserInputRouter.requests_from_dict(state.needs_input)
        if not requests and state.location_candidates:
            requests = {
                "location": LocationRequest.from_candidates(
                    state.location_candidates,
                    prompt="Several places match your query. Please choose a location.",
                    location_query=state.location_query or None,
                )
            }
        needs_input = UserInputRouter.requests_to_dict(requests)
        prompt = "Please provide the requested input to continue."
        location_req = requests.get("location")
        if isinstance(location_req, LocationRequest) and location_req.prompt:
            prompt = location_req.prompt
        bbox_req = requests.get("bounding_box")
        if bbox_req is not None and getattr(bbox_req, "prompt", None):
            prompt = str(bbox_req.prompt)
        return ToolResponse(
            tool_name="graph",
            message=prompt,
            error=False,
            data={
                "needs_input": needs_input,
                "pause": {"graph_state": graph_state},
            },
        )

    def from_completed_state(self, state: GraphStateModel) -> ToolResponse:
        message = (state.final_answer or "").strip()
        artifacts = self._artifacts_from_state(state)
        coords, city = self._coordinates_from_state(state)
        return ToolResponse(
            tool_name="graph",
            message=message or "I couldn't produce an answer for that request.",
            artifacts=artifacts,
            city=city,
            coordinates=coords,
            error=not message,
            data={
                "answer_source": state.answer_source,
                "selected_domains": state.selected_domains,
            },
        )

    def _artifacts_from_state(self, state: GraphStateModel) -> ToolArtifacts:
        bundles: list[ArtifactBundle] = []
        for dr in state.domain_results.values():
            domain = (
                dr
                if isinstance(dr, DomainResultModel)
                else DomainResultModel.model_validate(dr)
            )
            domain_data = domain.model_dump(mode="python")
            collected = False
            executions = domain_data.get("executions") or []
            if isinstance(executions, list):
                for ex in executions:
                    if not isinstance(ex, dict):
                        continue
                    ex_result = ex.get("result")
                    if isinstance(ex_result, dict) and isinstance(
                        ex_result.get("artifacts"), dict
                    ):
                        bundles.append(
                            ArtifactBundle.model_validate(ex_result["artifacts"])
                        )
                        collected = True
            if not collected:
                result = domain.result or {}
                if isinstance(result, dict):
                    artifacts = result.get("artifacts")
                    if isinstance(artifacts, dict):
                        bundles.append(ArtifactBundle.model_validate(artifacts))

        web_urls = [
            (w.get("url") or "").strip()
            for w in state.web_results
            if isinstance(w, dict) and (w.get("url") or "").strip()
        ]
        return self._aggregator.aggregate(bundles, extra_urls=web_urls)

    @staticmethod
    def _coordinates_from_state(
        state: GraphStateModel,
    ) -> tuple[ToolCoordinates | None, str | None]:
        resolved = state.resolved_location
        if resolved.lat is None or resolved.lon is None:
            if state.resolved_area is not None:
                lat, lon = state.resolved_area.centroid()
                return {"lat": lat, "lon": lon}, state.resolved_area.label()
            return None, resolved.display_name or None
        coords: ToolCoordinates = {"lat": float(resolved.lat), "lon": float(resolved.lon)}
        display = resolved.display_name or None
        return coords, display
