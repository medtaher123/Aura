"""Shared Pydantic models and cross-tool response contracts.

Tools must return a standardized ToolResponse dict to keep the UI and agent layer simple.
"""

from __future__ import annotations

from typing_extensions import Any, Dict, List, Literal, Optional, TypedDict

from pydantic import BaseModel, Field


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


class ToolArtifacts(BaseModel):
    """Artifacts that can be rendered in UI"""

    # `maps` can contain either HTML filenames (legacy) or structured map specs (e.g. Pydeck).
    maps: list[Any] = Field(default=[])
    thumbnails: list[str] = Field(default=[])
    urls: list[str] = Field(default=[])


class ToolCoordinates(TypedDict):
    lat: float
    lon: float


class ToolResponse(BaseModel):
    message: str
    tool_name: str = Field(..., description="Name of the tool that was called")
    artifacts: ToolArtifacts = Field(default=ToolArtifacts(), description="Artifacts")
    start_date: Optional[str] = Field(default=None, description="Start date")
    end_date: Optional[str] = Field(default=None, description="End date")
    country: Optional[str] = Field(default=None, description="Country")
    city: Optional[str] = Field(default=None, description="City")
    coordinates: Optional[ToolCoordinates] = Field(
        default=None, description="Coordinates"
    )
    data: Dict[str, Any] = Field(default={}, description="Data")
    error: bool = Field(default=False, description="Whether an error occurred")
