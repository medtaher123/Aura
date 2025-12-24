"""Shared Pydantic models and cross-tool response contracts.

Tools must return a standardized ToolResponse dict to keep the UI and agent layer simple.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict

from pydantic import BaseModel

class RiskQuery(BaseModel):
    risk_type: str
    region: Optional[str]
    bbox: Optional[List[float]]  # [min_lon, min_lat, max_lon, max_lat]

class GeoServerQuery(RiskQuery):
    layer_name: str  # Name of the GeoServer layer to query


class GeoServerRiskQuery(BaseModel):
    layer_name: str = "georisk:predictions"
    risk_type: Optional[str] = None
    region: Optional[str] = None
    location: Optional[str] = None
    bbox: Optional[List[float]] = None  # [min_lon, min_lat, max_lon, max_lat]
    start_date: Optional[str] = None  # YYYY-MM-DD or ISO timestamp
    end_date: Optional[str] = None  # YYYY-MM-DD or ISO timestamp
    min_confidence: Optional[float] = None
    min_area_m2: Optional[float] = None
    model_name: Optional[str] = None
    model_version: Optional[str] = None
    limit: int = 500
    render_mode: Literal["auto", "wms", "geojson"] = "auto"


class ToolArtifacts(TypedDict):
        maps: List[str]
        thumbnails: List[str]
        urls: List[str]


class ToolCoordinates(TypedDict):
        lat: float
        lon: float


class ToolResponse(TypedDict):
        message: str
        artifacts: ToolArtifacts
        tool_name: str
        start_date: Optional[str]
        end_date: Optional[str]
        country: Optional[str]
        city: Optional[str]
        coordinates: Optional[ToolCoordinates]
        data: Optional[Dict[str, Any]]
        error: bool


def make_tool_response(
        *,
        tool_name: str,
        message: str,
        artifacts: Optional[ToolArtifacts] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        country: Optional[str] = None,
        city: Optional[str] = None,
        coordinates: Optional[ToolCoordinates] = None,
        data: Optional[Dict[str, Any]] = None,
        error: bool = False,
) -> ToolResponse:
        """Create a standardized ToolResponse dict.

        Notes:
        - Always return all keys (UI and agent logic depends on that).
        - Put tool-specific payloads in `data`.
        - Put any renderable assets in `artifacts`.
        """

        normalized_artifacts: ToolArtifacts = artifacts or {"maps": [], "thumbnails": [], "urls": []}
        # Defensive normalization
        normalized_artifacts.setdefault("maps", [])
        normalized_artifacts.setdefault("thumbnails", [])
        normalized_artifacts.setdefault("urls", [])

        return {
                "message": message,
                "artifacts": normalized_artifacts,
                "tool_name": tool_name,
                "start_date": start_date,
                "end_date": end_date,
                "country": country,
                "city": city,
                "coordinates": coordinates,
                "data": data,
                "error": bool(error),
        }