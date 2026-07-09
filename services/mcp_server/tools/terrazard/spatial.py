"""Shared spatial resolution helpers for TerraZard tools."""

from __future__ import annotations

from core.logger import get_logger
from tools.terrazard.errors import TerrazardDataError
from utils.bbox_service import get_city_bbox, reverse_geocode
from utils.contracts import ToolCoordinates, ToolResponse

logger = get_logger(__name__)


def resolve_from_lat_lon(lat: float, lon: float) -> tuple[ToolCoordinates, list[float], str]:
    """Resolve coordinates, bbox, and display name from raw lat/lon."""
    lat_f, lon_f = float(lat), float(lon)
    coords = ToolCoordinates(lat=lat_f, lon=lon_f)

    try:
        rev = reverse_geocode(lat_f, lon_f)
        resolved_name = rev.get("city") or rev.get("country") or f"{lat_f:.4f}, {lon_f:.4f}"
    except Exception as exc:
        logger.error("Error reverse geocoding: %s", exc)
        resolved_name = f"{lat_f:.4f}, {lon_f:.4f}"

    bbox_norm = [lat_f - 0.25, lat_f + 0.25, lon_f - 0.25, lon_f + 0.25]
    return coords, bbox_norm, resolved_name


def resolve_from_location(location: str) -> tuple[ToolCoordinates, list[float], str]:
    """Resolve coordinates, bbox, and display name from a place name."""
    bbox, lat_city, lon_city, city_name_final = get_city_bbox(
        location, require_confirmation=True
    )

    if lat_city is None or lon_city is None:
        raise TerrazardDataError(f"Could not geocode location '{location}'.")

    coords = ToolCoordinates(lat=float(lat_city), lon=float(lon_city))
    resolved_name = city_name_final or location

    if not isinstance(bbox, list) or len(bbox) != 4:
        raise TerrazardDataError("Valid bounding box could not be extracted.")

    south, north, west, east = (float(x) for x in bbox)
    bbox_norm = [min(south, north), max(south, north), min(west, east), max(west, east)]
    return coords, bbox_norm, resolved_name


def resolve_spatial_context(
    location: str | None, lat: float | None, lon: float | None
) -> tuple[ToolCoordinates, list[float], str]:
    """Route to the appropriate spatial resolver based on provided inputs."""
    if lat is not None and lon is not None:
        return resolve_from_lat_lon(lat, lon)
    if location:
        return resolve_from_location(location)
    raise TerrazardDataError("Please specify a location or lat/lon coordinates.")


def normalize_terrazard_date(value: str | None, *, field_name: str = "date") -> str:
    """Normalize YYYYMMDD or YYYY-MM-DD to compact YYYYMMDD."""
    if not value:
        raise TerrazardDataError(f"Please specify a {field_name} (YYYYMMDD).")

    raw = str(value).strip()
    if len(raw) == 8 and raw.isdigit():
        return raw

    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        compact = raw.replace("-", "")
        if len(compact) == 8 and compact.isdigit():
            return compact

    raise TerrazardDataError(
        f"{field_name} must be YYYYMMDD or YYYY-MM-DD format."
    )


def validate_dates(start_date: str | None, end_date: str | None) -> tuple[str, str]:
    """Ensure both date bounds are present and return normalized YYYYMMDD values."""
    if not start_date or not end_date:
        raise TerrazardDataError(
            "Please specify both a start_date and an end_date (YYYYMMDD)."
        )
    return (
        normalize_terrazard_date(start_date, field_name="start_date"),
        normalize_terrazard_date(end_date, field_name="end_date"),
    )


def validate_observation_date(observation_date: str | None) -> str:
    """Ensure a single observation date is present and return normalized YYYYMMDD."""
    if not observation_date:
        raise TerrazardDataError("Please specify an observation_date (YYYYMMDD).")
    return normalize_terrazard_date(
        observation_date, field_name="observation_date"
    )


def handle_location_ambiguity(
    *,
    tool_name: str,
    error: Exception,
    location: str | None,
    extra_data: dict | None = None,
) -> ToolResponse | None:
    """Return a location-confirmation response when ambiguity is detected."""
    from utils.bbox_service import LocationAmbiguousError

    if not isinstance(error, LocationAmbiguousError):
        return None

    data: dict = {
        "needs_location_confirmation": True,
        "location_query": error.query,
        "candidates": error.candidates,
        "resume_patch": {"field": "location"},
    }
    if extra_data:
        data.update(extra_data)

    return ToolResponse(
        tool_name=tool_name,
        message=(
            f"I found multiple matches for '{error.query}'. "
            "Please confirm the correct location."
        ),
        city=location,
        data=data,
        error=False,
    )


def handle_terrazard_error(tool_name: str, error: Exception) -> ToolResponse | None:
    """Return a structured error response for known TerraZard failures."""
    if isinstance(error, TerrazardDataError):
        return ToolResponse(tool_name=tool_name, message=str(error), error=True)
    return None
