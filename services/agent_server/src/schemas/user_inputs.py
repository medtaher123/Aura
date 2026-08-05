"""User-input contracts: each input owns its request (TRequest) and result (TResult)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Generic, Literal, Optional, TypeVar, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.db.models.message import InputRequestMessage, InputResponseMessage

from .spatial import BoundingBox

InputKind = Literal["location", "bounding_box"]

OSMType = Literal["relation", "way", "node"]
OSMPrefixType = Literal["R", "W", "N"]


def get_osm_type_prefix(osm_type: str | None) -> Optional[OSMPrefixType]:
    match osm_type:
        case "relation":
            return "R"
        case "way":
            return "W"
        case "node":
            return "N"
        case _:
            return None


class UserInputRequest(BaseModel, ABC):
    """Base payload the server sends when requesting a user input."""

    model_config = ConfigDict(extra="allow")

    @abstractmethod
    def llm_text(self) -> str:
        """Human-readable summary for LLM / conversation history."""

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="python")

    def to_message(self, *, kind: InputKind) -> InputRequestMessage:
        """Convert this single-kind request into an ``InputRequestMessage``."""
        return InputRequestMessage.create(
            content=self.llm_text(),
            needs_input={kind: self.to_dict()},
        )


class UserInputResult(BaseModel, ABC):
    """Base value the client returns after the user answers an input."""

    model_config = ConfigDict(extra="allow")

    @abstractmethod
    def llm_text(self) -> str:
        """Human-readable summary for LLM / conversation history."""

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="python")

    def to_message(self, *, kind: InputKind) -> InputResponseMessage:
        """Convert this single-kind result into an ``InputResponseMessage``."""
        return InputResponseMessage.create(
            content=self.llm_text(),
            user_inputs={kind: self.to_dict()},
        )


TRequest = TypeVar("TRequest", bound=UserInputRequest)
TResult = TypeVar("TResult", bound=UserInputResult)


class UserInput(ABC, Generic[TRequest, TResult]):
    """Abstract user input: server asks with TRequest; client answers with TResult.

    Subclasses register themselves by ``kind`` (same pattern as ``GraphNode``).
    """

    kind: ClassVar[InputKind]
    request_model: ClassVar[type[UserInputRequest]]
    result_model: ClassVar[type[UserInputResult]]

    _registry: ClassVar[dict[str, type[UserInput[Any, Any]]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        kind = getattr(cls, "kind", None)
        if kind:
            UserInput._registry[kind] = cls

    @classmethod
    def for_kind(cls, kind: str) -> type[UserInput[Any, Any]]:
        input_cls = cls._registry.get(kind)
        if input_cls is None:
            raise ValueError(f"Unknown input kind: {kind!r}")
        return input_cls

    @classmethod
    def request_from_dict(cls, data: dict[str, Any] | BaseModel) -> TRequest:
        if isinstance(data, cls.request_model):
            return data  # type: ignore[return-value]
        return cls.request_model.model_validate(data)  # type: ignore[return-value]

    @classmethod
    def result_from_dict(cls, data: dict[str, Any] | BaseModel) -> TResult:
        if isinstance(data, cls.result_model):
            return data  # type: ignore[return-value]
        return cls.result_model.model_validate(data)  # type: ignore[return-value]

    @classmethod
    def request_to_dict(cls, request: UserInputRequest) -> dict[str, Any]:
        return request.to_dict()

    @classmethod
    def result_to_dict(cls, result: UserInputResult) -> dict[str, Any]:
        return result.to_dict()

    @classmethod
    def apply_result(
        cls,
        result: UserInputResult,
        state: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Apply a typed result onto a mutable graph/pause state dict. Override per kind."""
        return state


class LocationCandidate(BaseModel):
    """One geocoding candidate shown to the user."""

    model_config = ConfigDict(extra="allow")

    display_name: str = Field(..., description="Location display name")
    lat: float = Field(..., description="Latitude")
    lon: float = Field(..., description="Longitude")
    name: Optional[str] = Field(default=None, description="Short name")
    place_id: Optional[int] = Field(default=None, description="Place ID")
    osm_id: Optional[int] = Field(default=None, description="OSM ID")
    osm_type: Optional[str] = Field(default=None, description="OSM type")
    bbox: Optional[list[float]] = Field(
        default=None, description="[min_lat, max_lat, min_lon, max_lon]"
    )

    @classmethod
    def from_geocode(cls, data: dict[str, Any]) -> LocationCandidate | None:
        """Build a candidate from a Nominatim-style geocode dict."""
        lat, lon = data.get("lat"), data.get("lon")
        if lat is None or lon is None:
            return None
        display = str(data.get("display_name") or data.get("name") or "Unknown")
        entry: dict[str, Any] = {
            "display_name": display,
            "lat": float(lat),
            "lon": float(lon),
            "name": data.get("name"),
            "place_id": data.get("place_id"),
            "osm_id": data.get("osm_id"),
            "osm_type": data.get("osm_type"),
            "bbox": data.get("bbox"),
        }
        for key in ("class", "type", "addresstype"):
            if key in data:
                entry[key] = data[key]
        return cls.model_validate(entry)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="python")


class LocationRequest(UserInputRequest):
    """Payload the server sends when requesting a location choice."""

    candidates: list[LocationCandidate] = Field(
        ..., min_length=1, description="Location options for the user"
    )
    prompt: Optional[str] = Field(default=None, description="UI prompt")
    location_query: Optional[str] = Field(
        default=None, description="Original ambiguous query string"
    )

    def llm_text(self) -> str:
        if self.prompt:
            return self.prompt
        n = len(self.candidates)
        query = f" for {self.location_query!r}" if self.location_query else ""
        return f"Please confirm the location{query} ({n} option{'s' if n != 1 else ''} available)."

    @classmethod
    def from_dict(cls, data: dict[str, Any] | LocationRequest) -> LocationRequest:
        if isinstance(data, LocationRequest):
            return data
        return cls.model_validate(data)

    @classmethod
    def from_candidates(
        cls,
        candidates: list[dict[str, Any] | LocationCandidate],
        *,
        prompt: str | None = None,
        location_query: str | None = None,
    ) -> LocationRequest:
        parsed: list[LocationCandidate] = []
        for item in candidates:
            if isinstance(item, LocationCandidate):
                parsed.append(item)
                continue
            if not isinstance(item, dict):
                continue
            candidate = LocationCandidate.from_geocode(item)
            if candidate is not None:
                parsed.append(candidate)
        return cls(
            candidates=parsed,
            prompt=prompt,
            location_query=location_query,
        )


class LocationResult(UserInputResult):
    """Value the client returns after the user picks a location."""

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

    @classmethod
    def from_dict(cls, data: dict[str, Any] | LocationResult) -> LocationResult:
        if isinstance(data, LocationResult):
            return data
        return cls.model_validate(data)

    @classmethod
    def from_candidate(
        cls, candidate: dict[str, Any] | LocationCandidate
    ) -> LocationResult:
        if isinstance(candidate, LocationCandidate):
            data = candidate.to_dict()
        else:
            data = candidate
        osm_type = data.get("osm_type")
        return cls(
            name=str(data.get("display_name") or data.get("name") or "Unknown"),
            coordinates=[float(data["lat"]), float(data["lon"])],
            place_id=data.get("place_id"),
            osm_id=data.get("osm_id"),
            osm_type=osm_type if osm_type in get_args(OSMType) else None,
            osm_type_prefix=get_osm_type_prefix(osm_type),
        )


class LocationUserInput(UserInput[LocationRequest, LocationResult]):
    kind: ClassVar[InputKind] = "location"
    request_model: ClassVar[type[UserInputRequest]] = LocationRequest
    result_model: ClassVar[type[UserInputResult]] = LocationResult

    @classmethod
    def apply_result(
        cls,
        result: UserInputResult,
        state: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not isinstance(result, LocationResult):
            raise TypeError(f"expected LocationResult, got {type(result)!r}")
        confirmed_index = kwargs.get("confirmed_index")
        if confirmed_index is not None:
            # Resume path: location_gate resolves via candidate index.
            state["confirmed_location_index"] = int(confirmed_index)
            needs = dict(state.get("needs_input") or {})
            if "location" not in needs and state.get("location_candidates"):
                request = LocationRequest.from_candidates(
                    list(state.get("location_candidates") or []),
                    location_query=state.get("location_query"),
                )
                needs["location"] = request.to_dict()
            state["needs_input"] = needs
            return state

        # Proactive attach on a fresh turn: seed resolved_location so
        # location_gate short-circuits via has_resolved_location.
        from eo_llm.graph.state import ResolvedLocationModel

        lat, lon = result.coordinates
        state["resolved_location"] = ResolvedLocationModel(
            display_name=result.name,
            lat=lat,
            lon=lon,
        ).model_dump(mode="python")
        needs = dict(state.get("needs_input") or {})
        needs.pop("location", None)
        state["needs_input"] = needs
        if not needs:
            state["stopped_for_user_input"] = False
            state["location_phase"] = "router"
        return state


class BoundingBoxRequest(UserInputRequest):
    """Payload the server sends when requesting a map bounding box."""

    prompt: Optional[str] = Field(default=None, description="UI prompt")
    map_center: Optional[list[float]] = Field(
        default=None, description="[lat, lon] initial map center"
    )
    map_zoom: Optional[float] = Field(default=None, description="Initial map zoom")

    def llm_text(self) -> str:
        if self.prompt:
            return self.prompt
        return "Please draw a bounding box on the map."

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

    @classmethod
    def from_dict(cls, data: dict[str, Any] | BoundingBoxRequest) -> BoundingBoxRequest:
        if isinstance(data, BoundingBoxRequest):
            return data
        return cls.model_validate(data)


class BoundingBoxResult(UserInputResult):
    """Value the client returns after the user draws a bounding box."""

    model_config = ConfigDict(extra="forbid")

    area: BoundingBox

    def llm_text(self) -> str:
        return f"Selected area: {self.area.label()}."

    @classmethod
    def from_dict(cls, data: dict[str, Any] | BoundingBoxResult) -> BoundingBoxResult:
        if isinstance(data, BoundingBoxResult):
            return data
        return cls.model_validate(data)


class BoundingBoxUserInput(UserInput[BoundingBoxRequest, BoundingBoxResult]):
    kind: ClassVar[InputKind] = "bounding_box"
    request_model: ClassVar[type[UserInputRequest]] = BoundingBoxRequest
    result_model: ClassVar[type[UserInputResult]] = BoundingBoxResult

    @classmethod
    def apply_result(
        cls,
        result: UserInputResult,
        state: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not isinstance(result, BoundingBoxResult):
            raise TypeError(f"expected BoundingBoxResult, got {type(result)!r}")
        from eo_llm.graph.state import ResolvedLocationModel

        area = result.area
        lat, lon = area.centroid()
        state["resolved_area"] = area.model_dump(mode="python")
        state["resolved_location"] = ResolvedLocationModel(
            display_name=area.label(),
            lat=lat,
            lon=lon,
            bbox=area.as_list(),
        ).model_dump(mode="python")
        needs = dict(state.get("needs_input") or {})
        needs.pop("bounding_box", None)
        state["needs_input"] = needs
        if not needs:
            state["stopped_for_user_input"] = False
            state["location_phase"] = "router"
        return state


# Alias for call sites that previously used LocationOption.
LocationOption = LocationResult


class UserInputRouter:
    """Routes kind → payload maps through the ``UserInput`` registry."""

    @classmethod
    def requests_from_dict(
        cls, raw: dict[str, Any] | None
    ) -> dict[InputKind, UserInputRequest]:
        if not isinstance(raw, dict) or not raw:
            return {}
        out: dict[InputKind, UserInputRequest] = {}
        for key, payload in raw.items():
            input_cls = UserInput.for_kind(str(key))
            kind: InputKind = input_cls.kind
            if isinstance(payload, BaseModel):
                out[kind] = input_cls.request_from_dict(
                    payload.model_dump(mode="python")
                )
            else:
                out[kind] = input_cls.request_from_dict(payload)
        return out

    @classmethod
    def results_from_dict(
        cls, raw: dict[str, Any] | None
    ) -> dict[InputKind, UserInputResult]:
        if not isinstance(raw, dict) or not raw:
            return {}
        out: dict[InputKind, UserInputResult] = {}
        for key, payload in raw.items():
            input_cls = UserInput.for_kind(str(key))
            kind: InputKind = input_cls.kind
            if isinstance(payload, BaseModel):
                out[kind] = input_cls.result_from_dict(
                    payload.model_dump(mode="python")
                )
            else:
                out[kind] = input_cls.result_from_dict(payload)
        return out

    @classmethod
    def requests_to_dict(cls, requests: dict[str, Any] | None) -> dict[str, Any]:
        typed = cls.requests_from_dict(requests)
        return {
            kind: UserInput.for_kind(kind).request_to_dict(model)
            for kind, model in typed.items()
        }

    @classmethod
    def results_to_dict(cls, results: dict[str, Any] | None) -> dict[str, Any]:
        typed = cls.results_from_dict(results)
        return {
            kind: UserInput.for_kind(kind).result_to_dict(model)
            for kind, model in typed.items()
        }

    @classmethod
    def to_request_message(
        cls, requests: dict[str, Any] | None
    ) -> InputRequestMessage:
        """Build one ``InputRequestMessage`` covering all pending request kinds."""
        typed = cls.requests_from_dict(requests)
        if not typed:
            return InputRequestMessage.create(
                content="Additional input required.",
                needs_input={},
            )
        parts = [req.llm_text() for req in typed.values()]
        wire = {kind: req.to_dict() for kind, req in typed.items()}
        return InputRequestMessage.create(
            content=" ".join(parts),
            needs_input=wire,
        )

    @classmethod
    def to_response_message(
        cls, results: dict[str, Any] | None
    ) -> InputResponseMessage:
        """Build one ``InputResponseMessage`` covering all answered result kinds."""
        typed = cls.results_from_dict(results)
        if not typed:
            return InputResponseMessage.create(content="", user_inputs={})
        parts = [result.llm_text() for result in typed.values()]
        wire = {kind: result.to_dict() for kind, result in typed.items()}
        return InputResponseMessage.create(
            content=" ".join(parts),
            user_inputs=wire,
        )

    @classmethod
    def results_llm_text(cls, results: dict[str, Any] | None) -> str:
        """Human-readable summary of result kinds for LLM / message content."""
        typed = cls.results_from_dict(results)
        if not typed:
            return ""
        return "\n".join(result.llm_text() for result in typed.values())

    @classmethod
    def append_user_inputs_text(
        cls, message: str, results: dict[str, Any] | None
    ) -> str:
        """Append attached user-input summaries to a user message body."""
        base = (message or "").rstrip()
        suffix = cls.results_llm_text(results)
        if not suffix:
            return base
        if not base:
            return suffix
        return f"{base}\n\n{suffix}"

    @classmethod
    def pending_from_tool_data(
        cls, data: dict[str, Any] | None
    ) -> dict[InputKind, UserInputRequest]:
        """Read ``needs_input`` from tool/graph response data as typed requests."""
        if not isinstance(data, dict):
            return {}
        raw = data.get("needs_input")
        if not isinstance(raw, dict) or not raw:
            return {}
        return cls.requests_from_dict(raw)

    @classmethod
    def apply_results(
        cls,
        results: dict[str, Any] | None,
        state: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        typed = cls.results_from_dict(results)
        for kind, result in typed.items():
            UserInput.for_kind(kind).apply_result(result, state, **kwargs)
        return state
