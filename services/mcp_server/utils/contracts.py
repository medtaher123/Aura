"""
MCP Tool Contracts and Helpers

Shared utilities for MCP tools to maintain consistent response format.
"""

from __future__ import annotations
from typing_extensions import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ToolArtifacts(BaseModel):
    """Artifacts that can be rendered in UI"""

    maps: List[Any] = []
    thumbnails: List[str] = []
    urls: List[str] = []


class BoundingBox(BaseModel):
    """Axis-aligned WGS84 bounding box with named corners (order-safe for tool calls)."""

    min_lat: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="Southern latitude bound (degrees)",
    )
    max_lat: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="Northern latitude bound (degrees)",
    )
    min_lon: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="Western longitude bound (degrees)",
    )
    max_lon: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="Eastern longitude bound (degrees)",
    )

    @model_validator(mode="after")
    def validate_order(self) -> BoundingBox:
        if self.min_lat > self.max_lat:
            raise ValueError("min_lat must be <= max_lat")
        if self.min_lon > self.max_lon:
            raise ValueError("min_lon must be <= max_lon")
        return self

    def as_list(self) -> list[float]:
        """Legacy list form ``[min_lat, max_lat, min_lon, max_lon]`` for internal APIs."""
        return [self.min_lat, self.max_lat, self.min_lon, self.max_lon]


class ToolCoordinates(BaseModel):
    """Geographic coordinates"""

    lat: float = Field(..., description="Latitude")
    lon: float = Field(..., description="Longitude")
    zoom: Optional[float] = Field(default=None, description="Map zoom level")


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


BDTOPOQueryType = Literal["admin_lookup", "nearest_transport", "regulated_zones", "named_places"]
BDTOPOIntersectionInputMode = Literal["point", "road_name"]
BDTOPOAreaInputMode = Literal["point", "place_name", "bbox"]
BDTOPOExplainObjective = Literal["site_screening", "mobility_risk", "compliance", "general"]