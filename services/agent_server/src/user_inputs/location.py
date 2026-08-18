"""Location user-input kind: candidates request and location attachment answer."""

from __future__ import annotations

from typing import Any, ClassVar, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.db.models import MessageAttachment
from src.db.models.message_attachments import LocationAttachment

from .base import UserInput, UserInputRequest
from .types import InputKind


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


class LocationRequest(UserInputRequest):
    """Payload the server sends when requesting a location choice."""

    candidates: list[LocationCandidate] = Field(
        ..., min_length=1, description="Location options for the user"
    )
    prompt: Optional[str] = Field(default=None, description="UI prompt")
    location_query: Optional[str] = Field(
        default=None, description="Original ambiguous query string"
    )

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


class LocationUserInput(UserInput[LocationRequest, LocationAttachment]):
    kind: ClassVar[InputKind] = "location"
    request_model: ClassVar[type[UserInputRequest]] = LocationRequest
    attachment_model: ClassVar[type[MessageAttachment]] = LocationAttachment

    @classmethod
    def candidates_from_state(cls, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Candidates waiting for confirmation in pause / graph state."""
        needs = state.get("needs_input") or {}
        if isinstance(needs, dict):
            payload = needs.get("location")
            if isinstance(payload, dict):
                raw = payload.get("candidates")
                if isinstance(raw, list) and raw:
                    return [c for c in raw if isinstance(c, dict)]
        raw = state.get("location_candidates") or []
        if isinstance(raw, list):
            return [c for c in raw if isinstance(c, dict)]
        return []

    @classmethod
    def match_candidate_index(
        cls,
        candidates: list[dict[str, Any]],
        attachment: LocationAttachment,
    ) -> int:
        """Find the confirmed location within candidates; fall back to 0."""
        if not candidates:
            return 0

        osm_id = attachment.osm_id
        place_id = attachment.place_id
        name = (attachment.name or "").strip().lower()
        coords = attachment.coordinates or []

        if osm_id is not None:
            for i, c in enumerate(candidates):
                if c.get("osm_id") == osm_id:
                    return i
        if place_id is not None:
            for i, c in enumerate(candidates):
                if c.get("place_id") == place_id:
                    return i
        if name:
            for i, c in enumerate(candidates):
                cand_name = str(
                    c.get("display_name") or c.get("name") or ""
                ).strip().lower()
                if cand_name == name:
                    return i
        if len(coords) == 2:
            try:
                lat, lon = float(coords[0]), float(coords[1])
                best_i, best_d = 0, float("inf")
                for i, c in enumerate(candidates):
                    clat, clon = c.get("lat"), c.get("lon")
                    if isinstance(clat, (int, float)) and isinstance(clon, (int, float)):
                        d = (float(clat) - lat) ** 2 + (float(clon) - lon) ** 2
                        if d < best_d:
                            best_i, best_d = i, d
                return best_i
            except (TypeError, ValueError):
                return 0
        return 0

    @classmethod
    def apply_resume(
        cls,
        attachment: LocationAttachment,
        state: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not isinstance(attachment, LocationAttachment):
            raise TypeError(
                f"expected LocationAttachment, got {type(attachment)!r}"
            )
        candidates = cls.candidates_from_state(state)
        if candidates:
            state["confirmed_location_index"] = cls.match_candidate_index(
                candidates, attachment
            )
        return super().apply_resume(attachment, state, **kwargs)
