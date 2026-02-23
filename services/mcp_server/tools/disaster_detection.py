# disaster_detection.py
import requests
import pycountry
from datetime import datetime
import math
import re
from geopy.geocoders import Nominatim
import time
from mcp_singleton import mcp

from core.logger import get_logger
from utils.contracts import ToolResponse, ToolArtifacts, ToolCoordinates
from typing import Optional

from utils.bbox_service import get_city_candidates, reverse_geocode
from utils.map_view_service import (
    view_state_from_bbox,
    view_state_from_points,
)

logger = get_logger(__name__)

VALID_DISASTER_TYPES = [
    "flood",
    "storm",
    "earthquake",
    "extreme temperature",
    "drought",
    "industrial accident",
    "transport",
]


def get_iso3_from_country_name(name):
    try:
        country = pycountry.countries.lookup(name)
        return country.alpha_3
    except LookupError:
        return None


def get_emdat_by_iso3(iso3_code):
    url = f"https://www.gdacs.org/gdacsapi/api/Emdat/getemdatbyiso3?iso3={iso3_code}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching EMDAT data for ISO3 code {iso3_code}: {e}")
        return None


def _normalize_disaster_type(disaster_type: str) -> str:
    t = (disaster_type or "").strip().lower()
    # common plurals
    if t.endswith("s") and t[:-1] in VALID_DISASTER_TYPES:
        t = t[:-1]

    # canonicalize aliases
    if "temperature" in t:
        return "extreme temperature"
    if "accident" in t:
        return "industrial accident"
    if "transport" in t:
        return "transport"
    return t


def _event_matches_disaster_type(event: dict, disaster_type: str) -> bool:
    t = _normalize_disaster_type(disaster_type)
    disastertype = str(event.get("disastertype", "") or "").lower()
    subgroup = str(event.get("subgroupname", "") or "").lower()

    # Special handling for subgroup-based types.
    if t == "industrial accident":
        return "industrial accident" in subgroup
    if t == "transport":
        return "transport" in subgroup

    # All other types are matched against disastertype.
    return t in disastertype


def filter_disasters_between_dates(
    events,
    start_date,
    end_date,
    disaster_type: str | list[str] = "flood",
):
    """Return events grouped by disaster type.

    Returns:
        dict[str, list[dict]] mapping requested disaster_type -> matching raw event dicts.
    """
    if isinstance(disaster_type, list):
        requested_types = [_normalize_disaster_type(x) for x in disaster_type if x]
    else:
        requested_types = (
            [_normalize_disaster_type(disaster_type)] if disaster_type else []
        )

    # Ensure deterministic keys and remove empties.
    requested_types = [t for t in requested_types if t]
    seen = set()
    requested_types = [t for t in requested_types if not (t in seen or seen.add(t))]

    filtered_by_type: dict[str, list[dict]] = {t: [] for t in requested_types}
    start_date = datetime.strptime(start_date, "%Y-%m-%d")
    end_date = datetime.strptime(end_date, "%Y-%m-%d")
    # Now you can get the date part
    start_date = start_date.date()
    end_date = end_date.date()
    for event in events:
        try:
            start_event = datetime(
                event.get("startyear", 0),
                event.get("startmonth", 0),
                event.get("startday", 0) or 1,
            ).date()
            end_event = datetime(
                event.get("endyear", 0) or event.get("startyear", 0),
                event.get("endmonth", 0) or event.get("startmonth", 0),
                event.get("endday", 0) or event.get("startday", 0) or 1,
            ).date()
        except Exception as e:
            logger.error(f"Error parsing event dates: {e}")
            continue
        logger.info(f"Event from {start_event} to {end_event}")
        logger.info(f"Filtering between {start_date} and {end_date}")
        if start_event <= end_date and end_event >= start_date:
            # add to every matching requested type
            for t in requested_types:
                if _event_matches_disaster_type(event, t):
                    filtered_by_type[t].append(event)
    return filtered_by_type


def _safe_float(x) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _infer_view_state(
    points: list[dict], *, coords: dict[str, float] | None = None
) -> dict:
    # Prefer an explicit coords (e.g., city/country extent) when available.
    if (
        isinstance(coords, dict)
        and coords.get("lat") is not None
        and coords.get("lon") is not None
    ):
        return view_state_from_bbox(coords, padding=0.18, min_zoom=4.0, max_zoom=9)
    return view_state_from_points(points or [], padding=0.18, min_zoom=4.0, max_zoom=9)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # Mean Earth radius in kilometers
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def _distance_point_to_bbox_km(lat: float, lon: float, bbox: list[float]) -> float:
    """Distance from a point to a lat/lon bbox (0 if inside).

    bbox: [min_lat, max_lat, min_lon, max_lon]
    """
    if not isinstance(bbox, list) or len(bbox) != 4:
        return float("inf")
    min_lat, max_lat, min_lon, max_lon = bbox
    clamped_lat = min(max(float(lat), float(min_lat)), float(max_lat))
    clamped_lon = min(max(float(lon), float(min_lon)), float(max_lon))
    return _haversine_km(float(lat), float(lon), clamped_lat, clamped_lon)


def _emoji_for_disaster_type(disaster_type: str) -> str:
    t = (disaster_type or "").strip().lower()
    if "flood" in t:
        return "🌊"
    if "storm" in t:
        return "🌪️"
    if "earthquake" in t:
        return "🏔️"
    if "extreme temperature" in t or "temperature" in t:
        return "🥵"
    if "drought" in t:
        return "🌵"
    if "industrial accident" in t or "accident" in t:
        return "🏭"
    if "transport" in t:
        return "✈️"
    return "❗"


def _color_for_disaster_type(disaster_type: str) -> list[int]:
    """Deterministic per-type color."""
    t = (disaster_type or "").strip().lower()
    if t == "flood":
        return [0, 0, 255, 200]
    if t == "storm":
        return [128, 0, 128, 200]
    if t == "earthquake":
        return [139, 69, 19, 200]
    if t == "extreme temperature" or t == "temperature":
        return [255, 69, 0, 200]
    if t == "drought":
        return [210, 180, 140, 200]
    if t == "industrial accident" or t == "accident":
        return [105, 105, 105, 200]
    if t == "transport":
        return [0, 128, 0, 200]
    # Default: hash to color
    return [100, 100, 100, 200]


@mcp.tool()
def query_disaster_events_tool(
    start_date: str,
    end_date: str | None,
    country_name: str,
    location: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    disaster_type: str | list[str] = "flood",
) -> ToolResponse:
    """
    Search for natural & technological disasters
    (flood, storm, earthquake, extreme temperature, drought,
    industrial accident, transport) in a country and for a given date or date range.
    start_date: YYYY-MM-DD
    end_date: YYYY-MM-DD (optional, if not provided, only start_date is used)
    location: Specific location within the country if available
    lat/lon: Optional coordinates for a location filter
    country_name: Name of the country (e.g., "France", "Japan"), if available else use location to infer country
    disaster_type: Type of disaster to search for (default "flood"). Valid types:
      - flood
      - storm
      - earthquake
      - extreme temperature
      - drought
      - industrial accident
      - transport
    example: query_disaster_events_tool("2023-06-01", "2023-06-30", "France", "flood")
    """
    if end_date is None or (isinstance(end_date, str) and not end_date.strip()):
        end_date = start_date

    # Normalize disaster types
    if isinstance(disaster_type, list):
        requested_types = [_normalize_disaster_type(x) for x in disaster_type if x]
    else:
        requested_types = (
            [_normalize_disaster_type(disaster_type)] if disaster_type else []
        )

    requested_types = [t for t in requested_types if t]
    if not requested_types:
        requested_types = ["flood"]

    seen = set()
    requested_types = [t for t in requested_types if not (t in seen or seen.add(t))]

    logger.debug(
        f"Query params: {country_name}, {start_date} to {end_date}, types: {requested_types}"
    )

    # -----------------------
    # Country ISO3 code
    # -----------------------
    if country_name is not None and country_name.strip():
        iso3 = get_iso3_from_country_name(country_name)
    else:
        iso3 = None
    if not iso3:
        return ToolResponse(
            tool_name="query_disaster_events_tool",
            message=f"Country '{country_name}' not recognized.",
            country=country_name,
            start_date=start_date,
            end_date=end_date,
            data={"disaster_type": disaster_type},
            error=True,
        )

    # -----------------------
    # Optional: location bbox filter (city/region within country)
    # -----------------------
    location_bbox: list[float] | None = None
    location_display: str | None = None
    location_coordinates: Optional[ToolCoordinates] = None
    radius_km = 100.0

    if lat is not None and lon is not None:
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except Exception:
            return ToolResponse(
                tool_name="query_disaster_events_tool",
                message="Invalid coordinates provided. lat/lon must be numeric.",
                country=country_name,
                start_date=start_date,
                end_date=end_date,
                error=True,
            )

        location_bbox = [lat_f, lat_f, lon_f, lon_f]
        location_coordinates = ToolCoordinates(lat=lat_f, lon=lon_f)
        location_display = location
        if not (isinstance(location, str) and location.strip()):
            try:
                rev = reverse_geocode(lat_f, lon_f)
                location_display = rev.get("city") or rev.get("country")
            except Exception:
                location_display = None
        if not location_display:
            location_display = f"{lat_f:.4f}, {lon_f:.4f}"
    elif isinstance(location, str) and location.strip():
        loc_norm = location.strip().lower()
        country_norm = (country_name or "").strip().lower()
        # Only activate bbox filtering if user gave a sub-location (not the country itself)
        if loc_norm != country_norm:
            query = f"{location.strip()}, {country_name}"
            candidates = get_city_candidates(query, limit=5)

            if len(candidates) > 1:
                return ToolResponse(
                    tool_name="query_disaster_events_tool",
                    message=f"I found multiple matches for '{location}'. Please confirm the correct location.",
                    country=country_name,
                    city=location,
                    start_date=start_date,
                    end_date=end_date,
                    data={
                        "needs_location_confirmation": True,
                        "location_query": location,
                        "candidates": candidates,
                        "resume_patch": {"field": "location"},
                    },
                    error=False,
                )

            if not candidates or not candidates[0].get("bbox"):
                return ToolResponse(
                    tool_name="query_disaster_events_tool",
                    message=f"Couldn't resolve '{location}' to a bounding box inside {country_name}.",
                    country=country_name,
                    city=location,
                    start_date=start_date,
                    end_date=end_date,
                    data={"location": location, "country": country_name},
                    error=True,
                )

            location_bbox = candidates[0].get("bbox")
            location_display = candidates[0].get("display_name") or location
            try:
                lat0 = candidates[0].get("lat")
                lon0 = candidates[0].get("lon")
                if lat0 is not None and lon0 is not None:
                    location_coordinates = ToolCoordinates(lat=lat0, lon=lon0)
            except Exception:
                location_coordinates = None

    # -----------------------
    # Country bbox (for country-wide framing)
    # -----------------------
    # If the user didn't specify a sub-location, try to frame the country itself.
    country_coords: Optional[ToolCoordinates] = None
    if location_bbox is None and isinstance(country_name, str) and country_name.strip():
        try:
            cands = get_city_candidates(country_name.strip(), limit=1)
            if cands and isinstance(cands[0], dict):
                lat_c = cands[0].get("lat")
                lon_c = cands[0].get("lon")
                if lat_c is not None and lon_c is not None:
                    country_coords = ToolCoordinates(lat=float(lat_c), lon=float(lon_c))
        except Exception:
            country_coords = None

    # -----------------------
    # Retrieve events
    # -----------------------
    events = get_emdat_by_iso3(iso3)
    if not events:
        human_text = f"No data found for country '{country_name}' (code {iso3})."
        return ToolResponse(
            tool_name="query_disaster_events_tool",
            message=human_text,
            country=country_name,
            start_date=start_date,
            end_date=end_date,
            data={"disaster_type": disaster_type, "iso3": iso3, "events": []},
            error=False,
        )
    filtered_by_type = filter_disasters_between_dates(
        events, start_date, end_date, requested_types
    )
    total_events = sum(len(v) for v in (filtered_by_type or {}).values())
    if not filtered_by_type or total_events == 0:
        human_text = (
            f"No {', '.join([repr(t) for t in requested_types])} events found in {country_name} "
            f"between {start_date} and {end_date}."
        )
        return ToolResponse(
            tool_name="query_disaster_events_tool",
            message=human_text,
            country=country_name,
            start_date=start_date,
            end_date=end_date,
            data={
                "disaster_types": requested_types,
                "iso3": iso3,
                "events_by_type": {t: [] for t in requested_types},
                "events": [],
            },
            error=False,
        )

    # Construction de la réponse
    #
    # Build event summaries grouped by requested disaster type
    events_by_type: dict[str, list[dict]] = {t: [] for t in requested_types}
    events_list: list[dict] = []  # backward-compatible flat list
    map_points: list[dict] = []
    geolocator = Nominatim(user_agent="disaster_mapper")
    geocode_attempts = 0
    geocode_success = 0
    for dtype_key, events_for_type in filtered_by_type.items():
        for e in events_for_type:
            lat = _safe_float(e.get("latitude"))
            lon = _safe_float(e.get("longitude"))

            if lat is None or lon is None:
                location_name = e.get("location")
                country_e = e.get("country", "")
                if isinstance(location_name, str) and location_name.strip():
                    places = [
                        p.strip() for p in re.split(",|;", location_name) if p.strip()
                    ]
                    for place in places:
                        geocode_attempts += 1
                        try:
                            loc = geolocator.geocode(
                                f"{place}, {country_e}", timeout=10
                            )
                            if loc:
                                lat = float(loc.latitude)
                                lon = float(loc.longitude)
                                geocode_success += 1
                                time.sleep(1)
                                break
                        except Exception as ex:
                            logger.warning(f"Geocoding error for {place}: {ex}")
                            continue

            # If user requested a city/region filter, only keep events within radius_km of the bbox.
            # If we can't determine coordinates, skip the event (can't prove it's close).
            if location_bbox is not None:
                if not (isinstance(lat, float) and isinstance(lon, float)):
                    continue
                if _distance_point_to_bbox_km(lat, lon, location_bbox) > radius_km:
                    continue

            event_payload = {
                "requested_disaster_type": dtype_key,
                "type": e.get("disastertype", e.get("subgroupname", "")),
                "country": e.get("country"),
                "location": e.get("location"),
                "start_date": f"{e.get('startyear', '?')}-{e.get('startmonth', '?')}-{e.get('startday', '?')}",
                "end_date": f"{e.get('endyear', e.get('startyear', '?'))}-{e.get('endmonth', e.get('startmonth', '?'))}-{e.get('endday', e.get('startday', '?'))}",
                "total_deaths": e.get("totaldeaths"),
                "total_affected": e.get("totalaffected"),
                "origin": e.get("origin"),
                "latitude": lat if isinstance(lat, float) else e.get("latitude"),
                "longitude": lon if isinstance(lon, float) else e.get("longitude"),
            }

            if isinstance(lat, float) and isinstance(lon, float):
                dtype = e.get("disastertype", e.get("subgroupname", ""))
                map_points.append(
                    {
                        "lat": lat,
                        "lon": lon,
                        "type": dtype,
                        "requested_disaster_type": dtype_key,
                        "country": e.get("country"),
                        "location": e.get("location"),
                        "start_date": event_payload["start_date"],
                        "end_date": event_payload["end_date"],
                        "total_deaths": e.get("totaldeaths"),
                        "total_affected": e.get("totalaffected"),
                        "origin": e.get("origin"),
                        # Color/emoji are driven by the requested disaster type grouping
                        # so each type has a consistent style on the map.
                        "emoji": _emoji_for_disaster_type(str(dtype_key)),
                        "color": _color_for_disaster_type(str(dtype_key)),
                    }
                )

            events_by_type.setdefault(dtype_key, []).append(event_payload)
            events_list.append(event_payload)

    total_near_events = sum(len(v) for v in (events_by_type or {}).values())
    parts = [f"{t}: {len(events_by_type.get(t, []))}" for t in requested_types]
    human_text = (
        f"{total_events} event(s) found in {country_name} between {start_date} and {end_date}. "
        f"Breakdown: {', '.join(parts)}."
    )
    if location_bbox is not None:
        label = location_display or location
        human_text += f" Filtered to {total_near_events} event(s) within {int(radius_km)} km of {label}."
    if geocode_attempts:
        human_text += (
            f" Geocoded {geocode_success}/{geocode_attempts} missing locations."
        )

    artifacts = {"maps": [], "thumbnails": [], "urls": []}
    # Keep legacy behavior: don't render a map only when the *only* requested type is transport.
    only_transport = len(requested_types) == 1 and requested_types[0] == "transport"
    if not only_transport and map_points:
        artifacts["maps"].append(
            {
                "title": f"Disaster events in {country_name}",
                "view_state": _infer_view_state(
                    map_points,
                    coords=location_coordinates.model_dump()
                    if location_coordinates
                    else country_coords.model_dump()
                    if country_coords
                    else None,
                ),
                "tooltip": {
                    "text": "{emoji} {type}\n{location}, {country}\n{start_date} → {end_date}\nDeaths: {total_deaths}\nAffected: {total_affected}",
                },
                "layers": [
                    {
                        "type": "TextLayer",
                        "data": map_points,
                        "get_position": "[lon, lat]",
                        "get_text": "emoji",
                        "get_size": 18,
                        "get_color": "color",
                        "get_text_anchor": "middle",
                        "get_alignment_baseline": "center",
                        "opacity": 0.95,
                        "pickable": False,
                    },
                    {
                        "type": "ScatterplotLayer",
                        "data": map_points,
                        "get_position": "[lon, lat]",
                        "get_radius": 5,
                        "radius_units": "pixels",
                        "radius_min_pixels": 2,
                        "radius_max_pixels": 7,
                        "get_fill_color": "color",
                        "opacity": 0.6,
                        "pickable": True,
                    },
                ],
            }
        )

    return ToolResponse(
        tool_name="query_disaster_events_tool",
        message=human_text,
        artifacts=ToolArtifacts(
            maps=artifacts["maps"],
            thumbnails=artifacts["thumbnails"],
            urls=artifacts["urls"],
        ),
        country=country_name,
        city=location
        if isinstance(location, str) and location.strip() and location_bbox is not None
        else None,
        coordinates=location_coordinates if location_bbox is not None else None,
        start_date=start_date,
        end_date=end_date,
        data={
            "disaster_types": requested_types,
            "iso3": iso3,
            "events_by_type": events_by_type,
            "events": events_list,
            "location_filter": (
                {
                    "query": location,
                    "display_name": location_display,
                    "bbox": location_bbox,
                    "radius_km": radius_km,
                }
                if location_bbox is not None
                else None
            ),
        },
        error=False,
    )
