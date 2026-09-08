"""Factory for mapping graph state into GraphTurnResult objects."""

from __future__ import annotations

from typing import Any

from eo_llm.graph.hitl import client_payload_needs_input
from eo_llm.graph.state import DomainResultModel, GraphStateModel, validate_state
from src.db.models.message import Message, message_from_graph_dump
from src.tools.contracts import ToolArtifacts, ToolCoordinates

from .artifacts import ArtifactAggregator
from .models import ArtifactBundle, GraphTurnResult


class GraphTurnResultFactory:
    def __init__(self, aggregator: ArtifactAggregator | None = None):
        self._aggregator = aggregator or ArtifactAggregator()

    def from_state(self, state: GraphStateModel | dict[str, Any]) -> GraphTurnResult:
        model = state if isinstance(state, GraphStateModel) else validate_state(state)
        return self.from_completed_state(model)

    @staticmethod
    def from_interrupt(
        interrupt_payload: dict[str, Any],
        state: dict[str, Any] | None,
        *,
        checkpoint_thread_id: str,
        hitl_blobs: dict[str, dict[str, Any]] | None = None,
    ) -> GraphTurnResult:
        needs_input = client_payload_needs_input(interrupt_payload)
        prompt = interrupt_payload.get("prompt") or "Please provide the requested input to continue."
        if not interrupt_payload.get("prompt"):
            for value in needs_input.values():
                if isinstance(value, dict):
                    nested = value.get("prompt")
                    if isinstance(nested, str) and nested.strip():
                        prompt = nested.strip()
                        break
        return GraphTurnResult(
            message=prompt,
            error=False,
            tool_messages=[],
            data={
                "interrupted": True,
                "needs_input": needs_input,
                "checkpoint_thread_id": checkpoint_thread_id,
                "hitl_blobs": dict(hitl_blobs or {}),
                "interrupt_payload": dict(interrupt_payload),
            },
        )

    def from_completed_state(self, state: GraphStateModel) -> GraphTurnResult:
        message = (state.final_answer or "").strip()
        artifacts = self._artifacts_from_state(state)
        coords, city = self._coordinates_from_state(state)
        return GraphTurnResult(
            message=message or "I couldn't produce an answer for that request.",
            artifacts=artifacts,
            city=city,
            coordinates=coords,
            error=not message,
            tool_messages=self._tool_messages_from_state(state),
            data={
                "answer_source": state.answer_source,
                "selected_domains": state.selected_domains,
            },
        )

    @staticmethod
    def _tool_messages_from_state(state: GraphStateModel) -> list[Message]:
        out: list[Message] = []
        for dr in state.domain_results.values():
            if isinstance(dr, DomainResultModel):
                domain_data = dr.model_dump(mode="python")
            elif isinstance(dr, dict):
                domain_data = dr
            else:
                continue
            raw_messages = domain_data.get("tool_messages") or []
            if not isinstance(raw_messages, list):
                continue
            for item in raw_messages:
                if not isinstance(item, dict):
                    continue
                try:
                    out.append(message_from_graph_dump(item))
                except ValueError:
                    continue
        return out

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
        coords: ToolCoordinates = {
            "lat": float(resolved.lat),
            "lon": float(resolved.lon),
        }
        display = resolved.display_name or None
        return coords, display
