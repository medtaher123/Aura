"""Typed message attachments persisted on ``messages.attachments`` (JSONB)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field, TypeAdapter, field_validator

AttachmentType = Literal["location", "file", "bounding_box"]
OSMType = Literal["relation", "way", "node"]
OSMPrefixType = Literal["R", "W", "N"]


class MessageAttachment(BaseModel, ABC):
    """Base attachment carried on a conversation message."""

    @abstractmethod
    def llm_text(self) -> str:
        """Human-readable summary for LLM / conversation history."""

    def apply_to_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """Apply this attachment onto a mutable graph/pause state dict."""
        return state


class LocationAttachment(MessageAttachment):
    """Confirmed place attached to a user turn (proactive or resume)."""

    type: Literal["location"] = "location"
    name: str = Field(..., description="Location display name")
    coordinates: list[float] = Field(..., description="[lat, lon] coordinates")
    place_id: Optional[int] = Field(default=None, description="Place ID")
    osm_id: Optional[int] = Field(default=None, description="OSM ID")
    osm_type: Optional[OSMType] = Field(default=None, description="OSM type")
    osm_type_prefix: Optional[OSMPrefixType] = Field(
        default=None, description="OSM type prefix"
    )

    def llm_text(self) -> str:
        lat, lon = self.coordinates
        return f"Confirmed location: {self.name} ({lat}, {lon})."

    def apply_to_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """Seed resolved location data (proactive or resume)."""
        from eo_llm.graph.state import ResolvedLocationModel

        lat, lon = self.coordinates
        state["resolved_location"] = ResolvedLocationModel(
            display_name=self.name,
            lat=lat,
            lon=lon,
        ).model_dump(mode="python")
        return state

    @field_validator("coordinates")
    @classmethod
    def validate_coordinates(cls, value: list[float]) -> list[float]:
        if len(value) != 2:
            raise ValueError("coordinates must be [lat, lon]")
        lat, lon = float(value[0]), float(value[1])
        if not -90.0 <= lat <= 90.0:
            raise ValueError("lat must be in [-90, 90]")
        if not -180.0 <= lon <= 180.0:
            raise ValueError("lon must be in [-180, 180]")
        return [lat, lon]


class BoundingBoxAttachment(MessageAttachment):
    """Map area attached to a user turn (proactive or resume)."""

    type: Literal["bounding_box"] = "bounding_box"
    area: dict[str, Any] = Field(..., description="BoundingBox payload")

    def llm_text(self) -> str:
        from src.schemas.spatial import BoundingBox

        box = BoundingBox.model_validate(self.area)
        return f"Selected area: {box.label()}."

    def apply_to_state(self, state: dict[str, Any]) -> dict[str, Any]:
        from eo_llm.graph.state import ResolvedLocationModel
        from src.schemas.spatial import BoundingBox

        box = BoundingBox.model_validate(self.area)
        lat, lon = box.centroid()
        state["resolved_area"] = box.model_dump(mode="python")
        state["resolved_location"] = ResolvedLocationModel(
            display_name=box.label(),
            lat=lat,
            lon=lon,
            bbox=box.as_list(),
        ).model_dump(mode="python")
        return state


#TODO: to implement
class FileAttachment(MessageAttachment):
    """Uploaded file reference (stub — not wired to upload yet)."""

    type: Literal["file"] = "file"
    name: str = Field(default="", description="Original filename")
    path: str = Field(default="", description="Server-side storage path")
    format: str = Field(default="", description="File format, e.g. pdf")
    size_bytes: Optional[int] = Field(default=None, description="Byte size")

    def llm_text(self) -> str:
        label = self.name or self.path or "attached file"
        if self.format:
            return f"Attached file: {label} ({self.format})."
        return f"Attached file: {label}."


AnyMessageAttachment = Annotated[
    Union[LocationAttachment, BoundingBoxAttachment, FileAttachment],
    Field(discriminator="type"),
]

_attachment_adapter: TypeAdapter[AnyMessageAttachment] = TypeAdapter(
    AnyMessageAttachment
)
_attachments_adapter: TypeAdapter[list[AnyMessageAttachment]] = TypeAdapter(
    list[AnyMessageAttachment]
)


def parse_attachments(
    raw: list[dict[str, Any] | MessageAttachment] | None,
) -> list[MessageAttachment]:
    if not raw:
        return []
    return list(_attachments_adapter.validate_python(raw))


def dump_attachments(
    attachments: list[MessageAttachment] | None,
) -> list[dict[str, Any]]:
    if not attachments:
        return []
    return [a.model_dump(mode="python") for a in attachments]



def apply_attachments(
    attachments: list[MessageAttachment] | None,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Apply each attachment onto ``state`` in order."""
    for attachment in attachments or []:
        attachment.apply_to_state(state)
    return state
