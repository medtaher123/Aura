"""Shared graph state contract."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


AnswerSource = Literal["domain_tools", "web_search", "hybrid"]
NextStep = Literal[
    "route",
    "finalize_direct",
    "run_domains",
    "websearch_only",
    "web_search",
    "finalize",
]
DomainStatus = Literal["done", "error", "skipped"]


class ResolvedLocation(TypedDict, total=False):
    """Canonical place chosen for downstream domain tools / MCP calls."""

    display_name: str
    lat: float
    lon: float
    bbox: list[float]  # [min_lat, max_lat, min_lon, max_lon] when available


class GraphState(TypedDict, total=False):
    # Request
    query: str
    user_query: str
    session_id: str
    user_id: str

    # Optional explicit place string (orchestrator / client can set; else query is used)
    place_hint: str
    document_ref: dict[str, Any]
    document_context: dict[str, Any]

    # Location gate (after orchestrator, before router)
    location_query: str
    location_candidates: list[dict[str, Any]]
    needs_location_confirmation: bool
    confirmed_location_index: int
    resolved_location: ResolvedLocation
    # Set when graph stops for user to pick a candidate (client resumes with index)
    stopped_for_location_confirmation: bool

    # Planning / routing
    intent: str
    selected_domains: list[str]
    next_step: NextStep
    # "router" | "pause" — where to go after location_gate_node
    location_phase: Literal["router", "pause"]

    # Domain outputs
    domain_results: Annotated[dict[str, Any], operator.or_]
    aggregated_evidence: str

    # Fallback decision
    can_answer: bool
    confidence: float
    fallback_to_websearch: bool
    web_results: list[dict[str, str]]

    # Final output
    answer_source: AnswerSource
    final_answer: str


class ResolvedLocationModel(BaseModel):
    """Canonical place chosen for downstream domain tools / MCP calls."""

    model_config = ConfigDict(extra="allow")

    display_name: str = ""
    lat: float | None = None
    lon: float | None = None
    bbox: list[float] | None = None  # [min_lat, max_lat, min_lon, max_lon]

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if not -90.0 <= value <= 90.0:
            raise ValueError("lat must be in [-90, 90]")
        return value

    @field_validator("lon")
    @classmethod
    def validate_lon(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if not -180.0 <= value <= 180.0:
            raise ValueError("lon must be in [-180, 180]")
        return value

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return value
        if len(value) != 4:
            raise ValueError("bbox must have 4 elements")
        min_lat, max_lat, min_lon, max_lon = value
        if not (-90.0 <= min_lat <= 90.0 and -90.0 <= max_lat <= 90.0):
            raise ValueError("bbox latitude values must be in [-90, 90]")
        if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0):
            raise ValueError("bbox longitude values must be in [-180, 180]")
        if min_lat > max_lat or min_lon > max_lon:
            raise ValueError("bbox must be [min_lat, max_lat, min_lon, max_lon]")
        return value


class DomainResultModel(BaseModel):
    """Normalized domain-node result envelope."""

    model_config = ConfigDict(extra="allow")

    status: DomainStatus
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    message: str | None = None
    resolved_location: ResolvedLocationModel | dict[str, Any] | None = None
    error: bool | None = None


class GraphStateModel(BaseModel):
    """Runtime-validated graph state while keeping dict-compatible LangGraph flow."""

    model_config = ConfigDict(extra="allow")

    # Request
    query: str = ""
    user_query: str = ""
    session_id: str = "local-session"
    user_id: str = "anonymous"
    place_hint: str = ""
    document_ref: dict[str, Any] = Field(default_factory=dict)
    document_context: dict[str, Any] = Field(default_factory=dict)

    # Location gate (after orchestrator, before router)
    location_query: str = ""
    location_candidates: list[dict[str, Any]] = Field(default_factory=list)
    needs_location_confirmation: bool = False
    confirmed_location_index: int | None = None
    resolved_location: ResolvedLocationModel = Field(default_factory=ResolvedLocationModel)
    stopped_for_location_confirmation: bool = False

    # Planning / routing
    intent: str = ""
    selected_domains: list[str] = Field(default_factory=list)
    next_step: NextStep | None = None
    # "router" | "pause" — where to go after location_gate_node
    location_phase: Literal["router", "pause"] = "router"

    # Domain outputs
    domain_results: dict[str, DomainResultModel | dict[str, Any]] = Field(
        default_factory=dict
    )
    aggregated_evidence: str = ""

    # Fallback decision
    can_answer: bool | None = None
    confidence: float | None = None
    fallback_to_websearch: bool | None = None
    web_results: list[dict[str, str]] = Field(default_factory=list)

    # Final output
    answer_source: AnswerSource | None = None
    final_answer: str = ""

    @field_validator("confirmed_location_index")
    @classmethod
    def validate_confirmed_location_index(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value < 0:
            raise ValueError("confirmed_location_index must be >= 0")
        return value

    @model_validator(mode="after")
    def validate_location_confirmation_state(self) -> "GraphStateModel":
        if self.needs_location_confirmation and not self.location_candidates:
            raise ValueError(
                "location_candidates must be non-empty when needs_location_confirmation=True"
            )
        return self

    @computed_field
    @property
    def has_resolved_location(self) -> bool:
        return (
            self.resolved_location.lat is not None
            and self.resolved_location.lon is not None
        )

    @computed_field
    @property
    def should_pause_for_location(self) -> bool:
        return (
            self.needs_location_confirmation
            and bool(self.location_candidates)
            and not self.has_resolved_location
        )


def validate_state(state: GraphState | dict[str, Any]) -> GraphStateModel:
    """Validate/coerce incoming dict-like graph state."""
    return GraphStateModel.model_validate(state)


def dump_state(state: GraphStateModel | GraphState | dict[str, Any]) -> GraphState:
    """Validate and return a plain python dict suitable for LangGraph state passing."""
    model = state if isinstance(state, GraphStateModel) else validate_state(state)
    data = model.model_dump(mode="python")
    data.pop("has_resolved_location", None)
    data.pop("should_pause_for_location", None)
    return cast(GraphState, data)
