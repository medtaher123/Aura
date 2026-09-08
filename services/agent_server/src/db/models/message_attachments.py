"""Typed message attachments persisted on ``messages.attachments`` (JSONB)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Annotated, Any, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter, field_validator, model_validator

from eo_llm.graph.state import ResolvedLocationModel
from src.schemas.spatial import BoundingBox
from src.user_inputs.types import OTHER_OPTION_ID

AttachmentType = Literal["location", "file", "bounding_box", "multiple_choice"]
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
        box = BoundingBox.model_validate(self.area)
        return f"Selected area: {box.label()}."

    def apply_to_state(self, state: dict[str, Any]) -> dict[str, Any]:
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


class FileAttachment(MessageAttachment):
    """Reference to a row in the ``files`` table."""

    type: Literal["file"] = "file"
    file_id: UUID = Field(..., description="Stored file id")
    name: str = Field(default="", description="Original filename snapshot")

    def llm_text(self) -> str:
        label = self.name or str(self.file_id)
        return f"Attached file: {label}."


class MultipleChoiceAttachment(MessageAttachment):
    """User answer to a multiple-choice prompt."""

    type: Literal["multiple_choice"] = "multiple_choice"
    option_id: str = Field(..., description="Selected option id or reserved other id")
    label: str = Field(..., description="Resolved label shown to the agent")
    custom_text: Optional[str] = Field(
        default=None,
        description="Custom answer when the user picked Other",
    )
    prompt: Optional[str] = Field(
        default=None,
        description="Question text shown to the user (echoed for agent context)",
    )
    offered_options: Optional[list[dict[str, str]]] = Field(
        default=None,
        description="Options presented to the user as [{id, label}, ...]",
    )
    allow_other: bool = Field(
        default=True,
        description="Whether an Other/custom option was offered",
    )
    other_label: str = Field(
        default="Other",
        description="Label used for the Other option when offered",
    )

    def llm_text(self) -> str:
        if self.option_id == OTHER_OPTION_ID and self.custom_text:
            return (
                "User answered your multiple-choice question with a custom response: "
                f"{self.custom_text.strip()}."
            )
        return (
            "User answered your multiple-choice question by selecting "
            f"{self.label!r} (option_id={self.option_id!r})."
        )

    def answer_summary(self) -> str:
        """One-line answer for tool results and chat history."""
        if self.option_id == OTHER_OPTION_ID and self.custom_text:
            return f"Custom answer: {self.custom_text.strip()}"
        return f"Selected option: {self.label} (id={self.option_id})"

    @field_validator("option_id")
    @classmethod
    def validate_option_id(cls, value: str) -> str:
        option_id = str(value).strip()
        if not option_id:
            raise ValueError("option_id must be non-empty")
        return option_id

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        label = str(value).strip()
        if not label:
            raise ValueError("label must be non-empty")
        return label

    @model_validator(mode="after")
    def validate_other_answer(self) -> MultipleChoiceAttachment:
        if self.option_id == OTHER_OPTION_ID:
            text = (self.custom_text or "").strip()
            if not text:
                raise ValueError("custom_text is required when option_id is other")
            self.custom_text = text
        elif self.custom_text:
            raise ValueError("custom_text is only allowed when option_id is other")
        return self


AnyMessageAttachment = Annotated[
    Union[
        LocationAttachment,
        BoundingBoxAttachment,
        FileAttachment,
        MultipleChoiceAttachment,
    ],
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
    return [a.model_dump(mode="json") for a in attachments]



def apply_attachments(
    attachments: list[MessageAttachment] | None,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Apply each attachment onto ``state`` in order."""
    for attachment in attachments or []:
        attachment.apply_to_state(state)
    return state
