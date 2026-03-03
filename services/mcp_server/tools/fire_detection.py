# fire_detection.py
from datetime import datetime, timedelta, date
from pathlib import Path
import io
from core.logger import get_logger
from config import get_config
from utils.bbox_service import LocationAmbiguousError, get_city_bbox, reverse_geocode

from utils.map_view_service import (
    view_state_from_bbox,
    view_state_from_points,
)
from mcp_singleton import mcp
from utils.contracts import ToolArtifacts, ToolCoordinates, ToolResponse

logger = get_logger(__name__)
config = get_config()

# Use centralized config for API key and archive directory
MAP_KEY = config.map_key
ARCHIVE_DIR = config.fire_archive_dir
MAPS_DIR = Path(__file__).resolve().parents[1] / "maps"
MAPS_DIR.mkdir(parents=True, exist_ok=True)

# ARCHIVE_DIR = r"C:\MEPDev\LLM_Demo\langgraph_project\Data"


class FireArchiveMissingError(RuntimeError):
    pass


class FireDataUnavailableError(RuntimeError):
    pass


def _is_s3_path(path: str) -> bool:
    return isinstance(path, str) and path.startswith("s3://")


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    stripped = uri.replace("s3://", "", 1)
    if "/" not in stripped:
        return stripped, ""
    bucket, prefix = stripped.split("/", 1)
    return bucket, prefix


def _s3_object_exists(bucket: str, key: str) -> bool:
    import boto3

    s3 = boto3.client("s3")
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def _read_s3_csv(s3_uri: str):
    import boto3
    import pandas as pd

    bucket, key = _parse_s3_uri(s3_uri)
    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=bucket, Key=key)
    body = obj["Body"].read()
    return pd.read_csv(io.BytesIO(body))


# Calculate the great-circle distance between two points on the Earth (Haversine formula)
def haversine(lat1, lon1, lat2, lon2):
    """Great-circle distance (km) using the Haversine formula.

    Accepts scalars or numpy arrays/Series. Inputs are coerced to float.
    """
    import numpy as np

    lat1 = np.asarray(lat1, dtype="float64")
    lon1 = np.asarray(lon1, dtype="float64")
    lat2 = np.asarray(lat2, dtype="float64")
    lon2 = np.asarray(lon2, dtype="float64")

    R = 6371.0
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


class GeocodingError(RuntimeError):
    pass


# Find the archive file(s) that contain data for the given date range
def find_archive_files_for_range(start_date_obj, end_date_obj):
    if not _is_s3_path(ARCHIVE_DIR):
        raise FireArchiveMissingError(
            "FIRE_ARCHIVE_DIR must be set to an S3 URI (e.g., s3://bucket/prefix)."
        )

    bucket, prefix = _parse_s3_uri(ARCHIVE_DIR)
    prefix = prefix.rstrip("/")

    start_year = start_date_obj.year
    end_year = end_date_obj.year

    s3_uris = []
    for year in range(start_year, end_year + 1):
        filename = f"{year}.csv"
        key = f"{prefix}/{filename}" if prefix else filename
        s3_uri = f"s3://{bucket}/{key}"
        print("Checking archive file:", s3_uri)
        if _s3_object_exists(bucket, key):
            s3_uris.append(s3_uri)

    return s3_uris


# Decide whether to use the API (for recent dates) or archives (for older dates)
def should_use_api(start_date, end_date):
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
    return end_date_obj >= (date.today() - timedelta(days=7))


# Detect fires near a city for a given date and radius (km)
def detect_fire_near_city(
    start_date,
    end_date,
    city_name: str = "",
    radius_km: float = 100,
    lat=None,
    lon=None,
):
    city_name = str(city_name).strip() or ""
    logger.info(f"Detecting fires near city: {city_name}")
    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()

    bbox_norm = None
    if lat is not None and lon is not None:
        try:
            lat_city_f = float(lat)
            lon_city_f = float(lon)
        except (TypeError, ValueError):
            logger.error(f"Invalid coordinates: lat={lat}, lon={lon}")
            raise GeocodingError(f"Invalid coordinates: lat={lat}, lon={lon}")

        coords = ToolCoordinates(lat=lat_city_f, lon=lon_city_f)
        resolved_name = None
        if not isinstance(city_name, str) or not city_name.strip():
            try:
                rev = reverse_geocode(lat_city_f, lon_city_f)
                resolved_name = rev.get("city") or rev.get("country")
            except Exception as e:
                logger.error(f"Error reverse geocoding: {e}")
                resolved_name = None
        resolved_name = (
            resolved_name or city_name or f"{lat_city_f:.4f}, {lon_city_f:.4f}"
        )
    else:
        bbox, lat_city, lon_city, city_name_final = get_city_bbox(
            city_name, require_confirmation=True
        )
        print("City bbox:", bbox)
        print("City coordinates:", lat_city, lon_city)
        if lat_city is None or lon_city is None:
            raise GeocodingError(
                f"Could not geocode location '{city_name}'. Try a more specific place name (e.g. 'Paris, France')."
            )

        try:
            lat_city_f = float(lat_city)
            lon_city_f = float(lon_city)
        except (TypeError, ValueError):
            raise GeocodingError(
                f"Geocoding returned non-numeric coordinates for '{city_name}': lat={lat_city}, lon={lon_city}"
            )

        coords = ToolCoordinates(lat=lat_city_f, lon=lon_city_f)
        resolved_name = city_name_final or city_name

        if isinstance(bbox, list) and len(bbox) == 4:
            try:
                south, north, west, east = (float(x) for x in bbox)
                bbox_norm = [
                    min(south, north),
                    max(south, north),
                    min(west, east),
                    max(west, east),
                ]
            except Exception as e:
                logger.error(f"Error parsing bbox: {e}")
                bbox_norm = None

    use_api = should_use_api(start_date, end_date)

    import pandas as pd

    if use_api:
        print("Using API for fire data")
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/VIIRS_NOAA20_NRT/world/3"
        df = pd.read_csv(url)
    else:
        file_paths = find_archive_files_for_range(start_date_obj, end_date_obj)
        logger.info(f"Using archive files for fire data: {', '.join(file_paths)}")
        if not file_paths:
            logger.error("No fire archive CSV found for the requested date range.")
            raise FireDataUnavailableError(
                "No fire archive CSV found for the requested date range. "
                f"Checked location: '{ARCHIVE_DIR}'. "
                "Add the required FIRMS archive CSV files there (or set FIRE_ARCHIVE_DIR)."
            )
        frames = [_read_s3_csv(path) for path in file_paths]
        df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]

    # Ensure date column exists
    if "acq_date" not in df.columns:
        logger.error("Date column 'acq_date' not found in data.")
        logger.error(df.columns)
        return {
            "points": [],
            "nb_fires": 0,
            "coords": coords,
            "location_name": resolved_name,
            "bbox": bbox_norm,
        }

    # Ensure required coordinate columns exist and are numeric
    if "latitude" not in df.columns or "longitude" not in df.columns:
        print("Latitude/longitude columns not found in data.")
        return {
            "points": [],
            "nb_fires": 0,
            "coords": coords,
            "location_name": resolved_name,
            "bbox": bbox_norm,
        }

    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df.dropna(subset=["latitude", "longitude"]).copy()

    df["acq_date"] = pd.to_datetime(df["acq_date"]).dt.date
    df = df[
        (df["acq_date"] >= start_date_obj) & (df["acq_date"] <= end_date_obj)
    ].copy()
    if df.empty:
        return {
            "points": [],
            "nb_fires": 0,
            "coords": coords,
            "location_name": resolved_name,
            "bbox": bbox_norm,
        }

    df["distance"] = haversine(
        lat_city_f,
        lon_city_f,
        df["latitude"].to_numpy(),
        df["longitude"].to_numpy(),
    )
    df_filtered = df[df["distance"] <= radius_km]

    if df_filtered.empty:
        return {
            "points": [],
            "nb_fires": 0,
            "coords": coords,
            "location_name": resolved_name,
            "bbox": bbox_norm,
        }

    points = [
        {
            "lat": float(row["latitude"]),
            "lon": float(row["longitude"]),
            "brightness": float(row.get("brightness", row.get("bright_ti4", 0)) or 0),
            "acq_date": str(row["acq_date"]),
            "acq_time": str(row.get("acq_time", "")),
        }
        for _, row in df_filtered.iterrows()
    ]
    return {
        "points": points,
        "nb_fires": len(df_filtered),
        "coords": coords,
        "location_name": resolved_name,
        "bbox": bbox_norm,
    }


@mcp.tool()
def detect_fire_tool(
    start_date: str,
    end_date: str | None,
    location: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float | None = 100,
) -> ToolResponse:
    """
    Tool to detect fires near a city/country for a given date range and radius.
    Provide either a location name or lat/lon coordinates.
    """
    try:
        if end_date is None or (isinstance(end_date, str) and not end_date.strip()):
            end_date = start_date

        print("Detecting fire with params:", start_date, end_date, location, radius_km)

        if not start_date or (
            not (isinstance(location, str) and location.strip())
            and not (lat is not None and lon is not None)
        ):
            return ToolResponse(
                tool_name="detect_fire_tool",
                message=(
                    "Please specify a city (location) or lat/lon coordinates and a start_date (YYYY-MM-DD)."
                ),
                start_date=start_date,
                end_date=end_date,
                error=True,
            )

        try:
            radius_km_f = float(radius_km or 100.0)
        except Exception:
            radius_km_f = 100.0

        result = detect_fire_near_city(
            start_date,
            end_date,
            location or "",
            radius_km_f,
            lat=lat,
            lon=lon,
        )
        print("Detection result:", result)
        points = result.get("points") if isinstance(result, dict) else None
        print("points:", points)
        nb_fires = result.get("nb_fires") if isinstance(result, dict) else None
        coords = result.get("coords") if isinstance(result, dict) else None
        location_name = (
            result.get("location_name") if isinstance(result, dict) else None
        )

        display_location = (
            location_name
            if isinstance(location_name, str) and location_name.strip()
            else location
        )

        # NO FIRES FOUND
        if not nb_fires:
            if start_date == end_date:
                message = (
                    f"There were no hotspots or possible fires detected near {display_location} on {start_date} "
                    f"within a radius of {radius_km_f} km."
                )
            else:
                message = (
                    f"There were no hotspots or possible fires detected near {display_location} from {start_date} to {end_date} "
                    f"within a radius of {radius_km_f} km."
                )
            return ToolResponse(
                tool_name="detect_fire_tool",
                message=message,
                start_date=start_date,
                end_date=end_date,
                city=display_location,
                coordinates=coords,
                data={"radius_km": radius_km_f, "nb_fires": 0},
                error=False,
            )

        # FIRES FOUND
        points = points or []
        nb_fires = int(nb_fires)

        if start_date == end_date:
            message = (
                f"{nb_fires} fire(s) or hotspot(s) detected near {display_location} on {start_date} "
                f"within a radius of {radius_km_f} km."
            )
        else:
            message = (
                f"{nb_fires} fire(s) or hotspot(s) detected near {display_location} from {start_date} to {end_date} "
                f"within a radius of {radius_km_f} km."
            )

        # Build a structured map spec that the UI can render with Pydeck.
        # Prefer bbox-based zoom when available (city/country extent), else fallback to points.
        bbox = result.get("bbox") if isinstance(result, dict) else None
        coords = result.get("coords") if isinstance(result, dict) else None
        view_state = (
            view_state_from_bbox(
                coords,
                padding=0.18,
                min_zoom=5.0,
                max_zoom=10.5,
                radius=radius_km_f,
            )
            if isinstance(bbox, list) and len(bbox) == 4 and coords is not None
            else view_state_from_points(
                points or [],
                padding=0.18,
                min_zoom=5.0,
                max_zoom=10.5,
                radius=radius_km_f,
            )
        )

        return ToolResponse(
            tool_name="detect_fire_tool",
            message=message,
            artifacts=ToolArtifacts(
                maps=[
                    {
                        "title": "Fires near city",
                        "points": points,
                        "view_state": view_state,
                        "tooltip": {
                            "text": "{acq_date} {acq_time}\nBrightness: {brightness}"
                        },
                        "fill_color": [255, 0, 0, 160],
                        "radius": 5,
                        "radius_units": "pixels",
                        "radius_min_pixels": 2,
                        "radius_max_pixels": 7,
                    }
                ],
                thumbnails=[],
                urls=[],
            ),
            start_date=start_date,
            end_date=end_date,
            city=display_location,
            coordinates=coords,
            data={"radius_km": radius_km_f, "nb_fires": nb_fires},
            error=False,
        )

    except GeocodingError as e:
        return ToolResponse(
            tool_name="detect_fire_tool",
            message=str(e),
            error=True,
        )
    except LocationAmbiguousError as e:
        return ToolResponse(
            tool_name="detect_fire_tool",
            message=f"I found multiple matches for '{e.query}'. Please confirm the correct location.",
            city=location,
            start_date=start_date,
            end_date=end_date,
            data={
                "needs_location_confirmation": True,
                "location_query": e.query,
                "candidates": e.candidates,
                "resume_patch": {"field": "location"},
            },
            error=False,
        )
    except Exception as e:
        import traceback

        logger.error(f"Unexpected error during processing: {e}")
        logger.error(traceback.format_exc())
        return ToolResponse(
            tool_name="detect_fire_tool",
            message=f"Unexpected error during processing: {str(e)}",
            error=True,
        )
