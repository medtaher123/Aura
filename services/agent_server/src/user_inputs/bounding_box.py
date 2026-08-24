"""Bounding-box user-input kind: map area request and bounding-box attachment."""

from __future__ import annotations

from typing import Any, ClassVar, Optional

from pydantic import Field, field_validator

from src.db.models.message_attachments import BoundingBoxAttachment, MessageAttachment

from .base import UserInput, UserInputRequest
from .types import InputKind


class BoundingBoxRequest(UserInputRequest):
    """Payload the server sends when requesting a map bounding box.
    The map_center is the initial center of the map, and the map_zoom is the initial zoom level.
    The prompt is the prompt that will be displayed to the user.
    This tool presents to the user an interactive map and asks them to draw a precise bounding box on the map.
    """

    prompt: Optional[str] = Field(default=None, description="UI prompt")
    map_center: Optional[list[float]] = Field(
        default=None, description="[lat, lon] initial map center"
    )
    map_zoom: Optional[float] = Field(default=None, description="Initial map zoom")

    @field_validator("map_center")
    @classmethod
    def validate_map_center(
        cls, value: list[float] | None
    ) -> list[float] | None:
        if value is None:
            return value
        if len(value) != 2:
            raise ValueError("map_center must be [lat, lon]")
        lat, lon = float(value[0]), float(value[1])
        if not -90.0 <= lat <= 90.0:
            raise ValueError("map_center lat must be in [-90, 90]")
        if not -180.0 <= lon <= 180.0:
            raise ValueError("map_center lon must be in [-180, 180]")
        return [lat, lon]


class BoundingBoxUserInput(UserInput[BoundingBoxRequest, BoundingBoxAttachment]):
    kind: ClassVar[InputKind] = "bounding_box"
    request_model: ClassVar[type[UserInputRequest]] = BoundingBoxRequest
    attachment_model: ClassVar[type[MessageAttachment]] = BoundingBoxAttachment
