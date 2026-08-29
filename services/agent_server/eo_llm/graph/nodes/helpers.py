"""Shared helpers for graph domain nodes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eo_llm.graph.state import GraphState, GraphStateModel, ResolvedLocationModel
from src.schemas.spatial import BoundingBox


@dataclass(frozen=True)
class LocationContext:
    """Resolved location fields used when building domain tool arguments."""

    resolved: dict[str, Any]
    lat: float | None
    lon: float | None
    display_name: str
    country_name: str
    resolved_area: BoundingBox | None = None

    @classmethod
    def from_state(cls, s: GraphStateModel) -> LocationContext:
        resolved = s.resolved_location.model_dump(mode="python", exclude_none=True)
        display_name = s.resolved_location.display_name or ""
        country_name = display_name.split(",")[-1].strip() if display_name else ""
        area = s.resolved_area
        lat = s.resolved_location.lat
        lon = s.resolved_location.lon
        if (lat is None or lon is None) and area is not None:
            lat, lon = area.centroid()
        return cls(
            resolved=resolved,
            lat=lat,
            lon=lon,
            display_name=display_name,
            country_name=country_name,
            resolved_area=area,
        )

    @property
    def has_coordinates(self) -> bool:
        return self.lat is not None and self.lon is not None

    @property
    def bbox_list(self) -> list[float] | None:
        if self.resolved_area is None:
            return None
        return self.resolved_area.as_list()

    def known_coords(self) -> dict[str, float]:
        """Lat/lon only when resolved — omit keys so the arg-resolver LLM can fill gaps."""
        out: dict[str, float] = {}
        if self.lat is not None:
            out["lat"] = float(self.lat)
        if self.lon is not None:
            out["lon"] = float(self.lon)
        return out


def resolved_location_from_candidate(c: dict[str, Any]) -> ResolvedLocationModel:
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


def omit_none(values: dict[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is None so callers do not pre-fill missing tool args."""
    return {key: value for key, value in values.items() if value is not None}


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
