"""Spatial area models for user input and resolved graph context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


AreaKind = Literal["bounding_box"]

class Area(BaseModel, ABC):
    """Abstract geographic area."""

    model_config = ConfigDict(extra="forbid")

    kind: AreaKind

    @abstractmethod
    def centroid(self) -> tuple[float, float]:
        """Return the centroid of the area."""
        raise NotImplementedError


class BoundingBox(Area):
    """Axis-aligned bounding box in WGS84.

    Convention: ``[min_lat, max_lat, min_lon, max_lon]`` via :meth:`as_list`.
    """

    kind: AreaKind = "bounding_box"
    min_lat: float = Field(..., ge=-90.0, le=90.0)
    max_lat: float = Field(..., ge=-90.0, le=90.0)
    min_lon: float = Field(..., ge=-180.0, le=180.0)
    max_lon: float = Field(..., ge=-180.0, le=180.0)

    @model_validator(mode="after")
    def validate_order(self) -> BoundingBox:
        if self.min_lat > self.max_lat:
            raise ValueError("min_lat must be <= max_lat")
        if self.min_lon > self.max_lon:
            raise ValueError("min_lon must be <= max_lon")
        return self

    def as_list(self) -> list[float]:
        return [self.min_lat, self.max_lat, self.min_lon, self.max_lon]

    def as_tool_args(self) -> dict[str, float]:
        """Named fields for MCP tools that expect a structured bbox object."""
        return {
            "min_lat": self.min_lat,
            "max_lat": self.max_lat,
            "min_lon": self.min_lon,
            "max_lon": self.max_lon,
        }

    def centroid(self) -> tuple[float, float]:
        return (
            (self.min_lat + self.max_lat) / 2.0,
            (self.min_lon + self.max_lon) / 2.0,
        )

    @classmethod
    def from_list(cls, values: list[float]) -> BoundingBox:
        if len(values) != 4:
            raise ValueError("bbox list must have 4 elements")
        return cls(
            min_lat=float(values[0]),
            max_lat=float(values[1]),
            min_lon=float(values[2]),
            max_lon=float(values[3]),
        )

    def label(self) -> str:
        return (
            f"bbox[{self.min_lat:.4f},{self.max_lat:.4f},"
            f"{self.min_lon:.4f},{self.max_lon:.4f}]"
        )
