"""
MCP Tool Contracts and Helpers

Shared utilities for MCP tools to maintain consistent response format.
"""

from __future__ import annotations
from typing_extensions import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ToolArtifacts(BaseModel):
    """Artifacts that can be rendered in UI"""

    maps: List[Any] = []
    thumbnails: List[str] = []
    urls: List[str] = []


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