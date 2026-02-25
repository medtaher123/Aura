from typing_extensions import Any, Dict, Optional, TypedDict
from pydantic import BaseModel, Field


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
