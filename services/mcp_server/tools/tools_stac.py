from datetime import datetime, timedelta
import requests
from mcp_singleton import mcp
from requests.exceptions import RequestException, Timeout
from utils.bbox_service import LocationAmbiguousError, get_city_bbox, reverse_geocode

from core.logger import get_logger
from utils.contracts import ToolArtifacts, ToolResponse

logger = get_logger(__name__)


STAC_API_URL = "https://earth-search.aws.element84.com/v1"
REQUEST_TIMEOUT = 10


def _bbox_from_point(lat: float, lon: float, span_deg: float = 0.2) -> list[float]:
    half = span_deg / 2
    min_lat = max(-90.0, lat - half)
    max_lat = min(90.0, lat + half)
    min_lon = max(-180.0, lon - half)
    max_lon = min(180.0, lon + half)
    return [min_lon, min_lat, max_lon, max_lat]


@mcp.tool()
def query_stac_catalog(
    *,
    city: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    collection: str = "sentinel-2-l2a",
    limit_per_day: int = 3,
) -> ToolResponse:
    """
    Query the STAC EarthSearch catalog to retrieve satellite images.

    Provide either:
    - `city` (name), or
    - `lat` + `lon` (coordinates).
    Dates are strings in YYYY-MM-DD. If end_date is omitted, it defaults to start_date.
    collection: Satellite data collection to query. Options include "sentinel-1", "sentinel-2", "modis", "viirs".
    Collection defaults to "sentinel-2-l2a".

    """
    try:
        collection_map = {
            "sentinel-1": "sentinel-1-grd",
            "sentinel 1": "sentinel-1-grd",
            "sentinel-2": "sentinel-2-l2a",
            "sentinel 2": "sentinel-2-l2a",
            "modis": "firms-modis-c6",
            "viirs": "firms-viirs-nrt",
        }

        collection_norm = (collection or "").strip()
        if collection_norm:
            key = collection_norm.lower()
            collection_norm = collection_map.get(key, collection_norm)
        else:
            collection_norm = "sentinel-2-l2a"

        if end_date is None and isinstance(start_date, str) and start_date.strip():
            end_date = start_date
        if not start_date:
            start_date = datetime.now().strftime("%Y-%m-%d")
        if not end_date:
            end_date = start_date

        city_name = None
        bbox_list = None

        if lat is not None and lon is not None:
            try:
                lat_f = float(lat)
                lon_f = float(lon)
            except Exception:
                return ToolResponse(
                    tool_name="query_stac_catalog",
                    message="Invalid coordinates provided. lat/lon must be numeric.",
                    start_date=start_date,
                    end_date=end_date,
                    error=True,
                )

            bbox_list = _bbox_from_point(lat_f, lon_f)
            if isinstance(city, str) and city.strip():
                city_name = city.strip()
            else:
                try:
                    rev = reverse_geocode(lat_f, lon_f)
                    city_name = rev.get("city") or rev.get("country")
                except Exception:
                    city_name = None
            if not city_name:
                city_name = f"{lat_f:.4f}, {lon_f:.4f}"
        else:
            if not isinstance(city, str) or not city.strip():
                return ToolResponse(
                    tool_name="query_stac_catalog",
                    message="Missing required location: provide either city or lat/lon.",
                    start_date=start_date,
                    end_date=end_date,
                    error=True,
                )
            try:
                bbox_city, lat, lon, city_name_final = get_city_bbox(
                    city.strip(), require_confirmation=True
                )
            except LocationAmbiguousError as e:
                return ToolResponse(
                    tool_name="query_stac_catalog",
                    message=f"I found multiple matches for '{e.query}'. Please confirm the correct location.",
                    city=city.strip(),
                    start_date=start_date,
                    end_date=end_date,
                    data={
                        "needs_location_confirmation": True,
                        "location_query": e.query,
                        "candidates": e.candidates,
                        "resume_patch": {"field": "city"},
                    },
                    error=False,
                )
            city_name = city_name_final or city.strip()
            if not bbox_city:
                return ToolResponse(
                    tool_name="query_stac_catalog",
                    message=f"Location '{city_name}' not found or bbox unavailable.",
                    city=city_name,
                    start_date=start_date,
                    end_date=end_date,
                    error=True,
                )
            # get_city_bbox returns [min_lat, max_lat, min_lon, max_lon]
            try:
                min_lat = float(bbox_city[0])
                max_lat = float(bbox_city[1])
                min_lon = float(bbox_city[2])
                max_lon = float(bbox_city[3])
                bbox_list = [min_lon, min_lat, max_lon, max_lat]
            except Exception:
                return ToolResponse(
                    tool_name="query_stac_catalog",
                    message=f"Invalid bbox returned for '{city_name}'.",
                    city=city_name,
                    start_date=start_date,
                    end_date=end_date,
                    error=True,
                )

        bbox_str = ",".join([str(x) for x in bbox_list])

        date_format = "%Y-%m-%d"
        start = datetime.strptime(start_date, date_format)
        end = datetime.strptime(end_date, date_format)

        all_images = []
        current = start

        while current <= end:
            date_str = current.strftime(date_format)

            body = {
                "collections": [collection_norm],
                "bbox": bbox_list,
                "datetime": f"{date_str}T00:00:00Z/{date_str}T23:59:59Z",
                "limit": int(limit_per_day),
            }

            try:
                response = requests.post(
                    f"{STAC_API_URL}/search",
                    json=body,
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
            except Timeout:
                logger.error(f"STAC API timeout for collection {collection_norm}")
                return ToolResponse(
                    tool_name="query_stac_catalog",
                    message="Timeout while calling STAC API.",
                    city=city_name,
                    start_date=start_date,
                    end_date=end_date,
                    data={"collection": collection_norm, "bbox": bbox_str},
                    error=True,
                )
            except RequestException as exc:
                logger.error(f"STAC API request failed: {exc}")
                return ToolResponse(
                    tool_name="query_stac_catalog",
                    message=f"STAC network error: {exc}",
                    city=city_name,
                    start_date=start_date,
                    end_date=end_date,
                    data={"collection": collection_norm, "bbox": bbox_str},
                    error=True,
                )

            try:
                items = response.json().get("features", [])
            except ValueError as exc:
                logger.error(f"STAC JSON parsing error: {exc}")
                return ToolResponse(
                    tool_name="query_stac_catalog",
                    message=f"Invalid STAC response: {exc}",
                    city=city_name,
                    start_date=start_date,
                    end_date=end_date,
                    data={"collection": collection_norm, "bbox": bbox_str},
                    error=True,
                )

            if items:
                item = items[0]
                image_data = {
                    "date": date_str,
                    "cloud_cover": item.get("properties", {}).get(
                        "eo:cloud_cover", "N/A"
                    ),
                    "thumbnail": item.get("assets", {})
                    .get("thumbnail", {})
                    .get("href", ""),
                }
                all_images.append(image_data)

            current += timedelta(days=1)

        if not all_images:
            return ToolResponse(
                tool_name="query_stac_catalog",
                message=(
                    f"No images found for {collection_norm} between {start_date} and {end_date} "
                    f"for bbox {bbox_str}."
                ),
                start_date=start_date,
                end_date=end_date,
                city=city_name,
                data={
                    "collection": collection_norm,
                    "bbox": bbox_str,
                    "images": [],
                },
                error=False,
            )

        urls = [img["thumbnail"] for img in all_images if img.get("thumbnail")]
        details = "\n".join(
            [
                f"- {img['date']}: cloud_cover={img.get('cloud_cover', 'N/A')}% thumbnail={img.get('thumbnail', '')}"
                for img in all_images
            ]
        )

        return ToolResponse(
            tool_name="query_stac_catalog",
            message=(
                f"Found {len(all_images)} images for {collection_norm} between {start_date} and {end_date} "
                f"for bbox {bbox_str}.\n{details}"
            ),
            artifacts=ToolArtifacts(maps=[], thumbnails=urls, urls=urls),
            start_date=start_date,
            end_date=end_date,
            city=city_name,
            data={
                "collection": collection_norm,
                "bbox": bbox_str,
                "images": all_images,
            },
            error=False,
        )

    except Exception as exc:
        logger.error(f"STAC catalog error: {exc}", exc_info=True)
        return ToolResponse(
            tool_name="query_stac_catalog",
            message=f"Unexpected STAC error: {exc}",
            error=True,
        )
