"""Shared helpers for graph domain nodes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eo_llm.graph.state import GraphState, GraphStateModel


@dataclass(frozen=True)
class LocationContext:
    """Resolved location fields used when building domain tool arguments."""

    resolved: dict[str, Any]
    lat: float | None
    lon: float | None
    display_name: str
    country_name: str

    @classmethod
    def from_state(cls, s: GraphStateModel) -> LocationContext:
        resolved = s.resolved_location.model_dump(mode="python", exclude_none=True)
        display_name = s.resolved_location.display_name or ""
        country_name = display_name.split(",")[-1].strip() if display_name else ""
        return cls(
            resolved=resolved,
            lat=s.resolved_location.lat,
            lon=s.resolved_location.lon,
            display_name=display_name,
            country_name=country_name,
        )

    @property
    def has_coordinates(self) -> bool:
        return self.lat is not None and self.lon is not None


def domain_result_as_dict(result: Any) -> dict[str, Any]:
    """Normalize a domain result value to a plain dict."""
    if isinstance(result, dict):
        return result
    dump = getattr(result, "model_dump", None)
    if callable(dump):
        return dump(mode="python")
    return {}


def wrap_domain_result(domain: str, payload: dict[str, Any]) -> GraphState:
    """Return the standard LangGraph partial state for one domain result."""
    return {"domain_results": {domain: payload}}
