"""Geocoding helpers (Nominatim) used across tools.

Supports city geocoding via `get_city_bbox(city_name)` and disambiguation
via `LocationAmbiguousError`.

"""

import time
from dataclasses import dataclass
from typing import Any

import requests

from core.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class LocationCandidate:
    display_name: str
    name: str
    lat: float | None
    lon: float | None
    bbox: list[float] | None  # [min_lat, max_lat, min_lon, max_lon]


class LocationAmbiguousError(RuntimeError):
    def __init__(self, query: str, candidates: list[dict[str, Any]]):
        super().__init__(f"Ambiguous location: {query}")
        self.query = query
        self.candidates = candidates


def _parse_bbox(raw_bbox: Any) -> list[float] | None:
    # Nominatim returns boundingbox as [south, north, west, east] (strings).
    if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
        return None
    try:
        south, north, west, east = (float(x) for x in raw_bbox)
    except Exception:
        return None
    return [min(south, north), max(south, north), min(west, east), max(west, east)]


def _normalize_candidate(item: dict[str, Any], fallback_name: str) -> dict[str, Any]:
    display_name = str(item.get("display_name") or fallback_name)
    name = display_name.split(",")[0].strip() or fallback_name
    place_id = item.get("place_id")
    osm_id = item.get("osm_id")
    osm_type = item.get("osm_type")
    lat_raw = item.get("lat")
    lon_raw = item.get("lon")
    try:
        lat = float(lat_raw) if lat_raw is not None else None
    except Exception:
        lat = None
    try:
        lon = float(lon_raw) if lon_raw is not None else None
    except Exception:
        lon = None
    bbox = _parse_bbox(item.get("boundingbox"))
    return {
        "display_name": display_name,
        "name": name,
        "lat": lat,
        "lon": lon,
        "bbox": bbox,
        "place_id": int(place_id) if place_id is not None else None,
        "osm_id": int(osm_id) if osm_id is not None else None,
        "osm_type": str(osm_type) if osm_type is not None else None,
    }


def _lookup_by_place_id(place_id: int) -> dict[str, Any] | None:
    url = "https://nominatim.openstreetmap.org/lookup"
    params = {"place_ids": str(int(place_id)), "format": "json"}
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(
                url,
                params=params,
                headers={"User-Agent": "geocode-tool"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list) or not data:
                return None
            item = data[0]
            if not isinstance(item, dict):
                return None
            return item
        except Exception as e:
            last_exc = e
            if attempt < 2:
                time.sleep(1)
                continue
            break
    if last_exc:
        logger.error(f"Failed to lookup place_id={place_id}: {last_exc}")
    return None


def _lookup_by_osm_ids(osm_ids: str) -> dict[str, Any] | None:
    url = "https://nominatim.openstreetmap.org/lookup"
    params = {"osm_ids": osm_ids, "format": "json"}
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(
                url,
                params=params,
                headers={"User-Agent": "geocode-tool"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list) or not data:
                return None
            item = data[0]
            if not isinstance(item, dict):
                return None
            return item
        except Exception as e:
            last_exc = e
            if attempt < 2:
                time.sleep(1)
                continue
            break
    if last_exc:
        logger.error(f"Failed to lookup osm_ids={osm_ids}: {last_exc}")
    return None


def _parse_lookup_token(query: str) -> tuple[str, str] | None:
    """Parse special lookup tokens.

    Supported:
    - @place_id:<int>
    - @osm_id:<R|W|N><int>  (Nominatim osm_ids format)
    """
    if not isinstance(query, str):
        return None
    if query.startswith("@place_id:"):
        return ("place_id", query.split(":", 1)[1].strip())
    if query.startswith("@osm_id:"):
        return ("osm_id", query.split(":", 1)[1].strip())
    return None


def get_city_candidates(city_name: str, *, limit: int = 10) -> list[dict[str, Any]]:
    """Return multiple plausible matches for a location query."""
    tok = _parse_lookup_token(city_name)
    if tok:
        kind, value = tok
        item = None
        if kind == "place_id":
            try:
                item = _lookup_by_place_id(int(value))
            except Exception:
                item = None
        elif kind == "osm_id":
            if value:
                item = _lookup_by_osm_ids(value)
        if item:
            c = _normalize_candidate(item, city_name)
            if c.get("lat") is not None and c.get("lon") is not None:
                return [c]
        return []

    url = "https://nominatim.openstreetmap.org/search"
    geo_params = {"q": city_name, "format": "json", "limit": int(limit)}

    last_exc: Exception | None = None
    for attempt in range(5):
        try:
            response = requests.get(
                url,
                params=geo_params,
                headers={"User-Agent": "geocode-tool"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list) or not data:
                return []

            candidates = [_normalize_candidate(item, city_name) for item in data]
            # Keep only candidates that at least have coordinates.
            return [
                c
                for c in candidates
                if c.get("lat") is not None and c.get("lon") is not None
            ]
        except Exception as e:
            last_exc = e
            if attempt < 4:
                time.sleep(1)
                continue
            break

    if last_exc:
        logger.error(f"Failed to get candidates for '{city_name}': {last_exc}")
    return []


def get_city_bbox(
    city_name: str,
    *,
    require_confirmation: bool = False,
    limit: int = 10,
):
    """Legacy helper returning (bbox, lat, lon, name).

    - bbox: list[str] from Nominatim (kept for backward compatibility)
    - lat/lon: strings or None
    - name: short label
    """

    tok = _parse_lookup_token(city_name)
    if tok:
        kind, value = tok
        item = None
        if kind == "place_id":
            try:
                item = _lookup_by_place_id(int(value))
            except Exception:
                item = None
        elif kind == "osm_id":
            if value:
                item = _lookup_by_osm_ids(value)
        if item:
            bbox = item.get("boundingbox", None)
            lat = item.get("lat", None)
            lon = item.get("lon", None)
            display_name = item.get("display_name", city_name)
            # For token-based lookups, prefer the full display name so tools/UI
            # don't surface opaque tokens like "@osm_id:..." to the user.
            name = str(display_name)
            return bbox, lat, lon, name
        return None, None, None, city_name

    url = "https://nominatim.openstreetmap.org/search"
    geo_params = {"q": city_name, "format": "json", "limit": int(limit)}

    last_exc: Exception | None = None
    for attempt in range(5):
        try:
            response = requests.get(
                url,
                params=geo_params,
                headers={"User-Agent": "geocode-tool"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            if not isinstance(data, list) or not data:
                if attempt < 4:
                    time.sleep(1)
                    continue
                return None, None, None, city_name

            if require_confirmation and len(data) > 1:
                candidates = [_normalize_candidate(item, city_name) for item in data]
                raise LocationAmbiguousError(query=city_name, candidates=candidates)

            bbox = data[0].get("boundingbox", None)
            lat = data[0].get("lat", None)
            lon = data[0].get("lon", None)
            if bbox and lat and lon:
                display_name = data[0].get("display_name", city_name)
                name = display_name.split(",")[0]
                return bbox, lat, lon, name
        except LocationAmbiguousError:
            raise
        except Exception as e:
            last_exc = e
            if attempt < 4:
                time.sleep(1)
                continue
            if last_exc:
                logger.error(f"Failed to get bbox from Nominatim: {last_exc}")
            return None, None, None, city_name
    return None, None, None, city_name

def reverse_geocode(lat: float, lon: float):
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {"lat": lat, "lon": lon, "format": "json", "zoom": 10, "addressdetails": 1}
    r = requests.get(url, params=params, headers={"User-Agent": "SurfaceIngressTool"})
    data = r.json()
    address = data.get("address", {})
    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("hamlet")
    )
    country = address.get("country")
    country_code = address.get("country_code")
    return {
        "city": city,
        "country": country,
        "country_iso": country_code.upper() if country_code else None,
    }
