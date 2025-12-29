# fire_detection.py
from datetime import datetime, timedelta, date
import pandas as pd
import numpy as np
import os
from pathlib import Path
from src.services.bbox_service import get_city_bbox
from langchain.tools import tool
from .contracts import make_tool_response

MAP_KEY = "f44596f0cc01c26985abd6bfff78ac92"
_DEFAULT_ARCHIVE_DIR = "/home/inesb/Metaplanet_llm-main_v1/Data"
ARCHIVE_DIR = os.getenv("FIRE_ARCHIVE_DIR", str(_DEFAULT_ARCHIVE_DIR))
MAPS_DIR = Path(__file__).resolve().parents[1] / "maps"
MAPS_DIR.mkdir(parents=True, exist_ok=True)

# ARCHIVE_DIR = r"C:\MEPDev\LLM_Demo\langgraph_project\Data"


class FireArchiveMissingError(RuntimeError):
    pass


class FireDataUnavailableError(RuntimeError):
    pass


# Calculate the great-circle distance between two points on the Earth (Haversine formula)
def haversine(lat1, lon1, lat2, lon2):
    """Great-circle distance (km) using the Haversine formula.

    Accepts scalars or numpy arrays/Series. Inputs are coerced to float.
    """
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

# Find the archive file that contains data for the given date
def find_archive_file_for_range(start_date_obj, end_date_obj):
    archive_dir = Path(ARCHIVE_DIR)
    if not archive_dir.exists() or not archive_dir.is_dir():
        raise FireArchiveMissingError(
            f"Fire archive folder not found: '{archive_dir}'. "
            "Create it and add FIRMS CSV archives, or set FIRE_ARCHIVE_DIR to the correct path."
        )

    # --- SPECIAL CASE FILES (explicit date ranges) ----
    SPECIAL_FILES = [
        {
            "filename": "fire_archive_SV-C2_673436.csv",
            "start": date(2024, 11, 1),
            "end": date(2025, 6, 30)
        },
        {
            "filename": "fire_nrt_SV-C2_673436.csv",
            "start": date(2025, 7, 1),
            "end": date(2025, 10, 14)
        }
    ]

    for sf in SPECIAL_FILES:
        if not (end_date_obj < sf["start"] or start_date_obj > sf["end"]):
            full_path = archive_dir / sf["filename"]
            print("Using special file:", full_path)
            if full_path.exists():
                return str(full_path)

    # ---- DEFAULT LOGIC FOR ALL OTHER ARCHIVE FILES ----
    for entry in sorted(archive_dir.iterdir()):
        filename = entry.name
        print("Checking archive file:", filename)
        if entry.is_file() and filename.endswith(".csv") and "fire_archive_" in filename:
            try:
                parts = filename.replace(".csv", "").split("_")
                start_year = int(parts[2])
                end_year = int(parts[3])

                file_start = datetime(start_year, 1, 21).date()
                file_end = datetime(end_year, 1, 20).date()

                # Check overlap
                if not (end_date_obj < file_start or start_date_obj > file_end):
                    return str(entry)

            except Exception:
                continue

    return None


# Decide whether to use the API (for recent dates) or archives (for older dates)
def should_use_api(start_date, end_date):
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
    return end_date_obj >= (date.today() - timedelta(days=7))


# Detect fires near a city for a given date and radius (km)
def detect_fire_near_city(start_date, end_date, city_name, radius_km=100):
    print("Detecting fires near city:", city_name)
    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()

    bbox, lat_city, lon_city, city_name_final = get_city_bbox(city_name)
    print("City coordinates:", lat_city, lon_city)
    if lat_city is None:
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

    use_api = should_use_api(start_date, end_date)

    if use_api:
        print("Using API for fire data")
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/VIIRS_NOAA20_NRT/world/3"
        df = pd.read_csv(url)
    else:
        file_path = find_archive_file_for_range(start_date_obj, end_date_obj)
        print("Using archive file for fire data:", file_path)
        if not file_path:
            raise FireDataUnavailableError(
                "No fire archive CSV found for the requested date range. "
                f"Checked folder: '{Path(ARCHIVE_DIR)}'. "
                "Add the required FIRMS archive CSV files there (or set FIRE_ARCHIVE_DIR)."
            )
        df = pd.read_csv(file_path)

    # Ensure date column exists
    if "acq_date" not in df.columns:
        print("Date column 'acq_date' not found in data.")
        return None

    # Ensure required coordinate columns exist and are numeric
    if "latitude" not in df.columns or "longitude" not in df.columns:
        print("Latitude/longitude columns not found in data.")
        return None

    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df.dropna(subset=["latitude", "longitude"]).copy()

    df["acq_date"] = pd.to_datetime(df["acq_date"]).dt.date
    df = df[
        (df["acq_date"] >= start_date_obj) & (df["acq_date"] <= end_date_obj)
    ].copy()
    if df.empty:
        return None

    df["distance"] = haversine(
        lat_city_f,
        lon_city_f,
        df["latitude"].to_numpy(),
        df["longitude"].to_numpy(),
    )
    df_filtered = df[df["distance"] <= radius_km]

    if df_filtered.empty:
        return None

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
    return points, len(df_filtered)





@tool(return_direct=True)
def detect_fire_tool(
    start_date: str,
    end_date: str | None,
    location: str,
    radius_km: float = 100,
) -> dict:
    """
    Tool to detect fires near a city/country for a given date range and radius.
    """
    try:
        if end_date is None or (isinstance(end_date, str) and not end_date.strip()):
            end_date = start_date

        print("Detecting fire with params:", start_date, end_date, location, radius_km)

        if not start_date or not location:
            return make_tool_response(
                tool_name="detect_fire_tool",
                message=(
                    "Please specify a city and a start_date (YYYY-MM-DD)."
                ),
                location=location,
                start_date=start_date,
                end_date=end_date,
                error=True,
            )

        try:
            radius_km_f = float(radius_km)
        except Exception:
            radius_km_f = 100.0

        result = detect_fire_near_city(start_date, end_date, location, radius_km_f)
        print("Detection result:", result)
        # NO FIRES FOUND
        if not result:
            if start_date == end_date:
                message = (
                    f"There were no fires detected near {location} on {start_date} "
                    f"within a radius of {radius_km_f} km."
                )
            else:
                message = (
                    f"There were no fires detected near {location} from {start_date} to {end_date} "
                    f"within a radius of {radius_km_f} km."
                )
            coords = None
            try:
                bbox, lat, lon, city_name_final = get_city_bbox(location)
                if lat is not None and lon is not None:
                    coords = {"lat": float(lat), "lon": float(lon)}
            except Exception:
                coords = None
            return make_tool_response(
                tool_name="detect_fire_tool",
                message=message,
                start_date=start_date,
                end_date=end_date,
                city=location,
                coordinates=coords,
                data={"radius_km": radius_km_f, "nb_fires": 0},
                error=False,
            )

        # FIRES FOUND
        points, nb_fires = result

        if start_date == end_date:
            message = (
                f"{nb_fires} fire(s) detected near {location} on {start_date} "
                f"within a radius of {radius_km_f} km."
            )
        else:
            message = (
                f"{nb_fires} fire(s) detected near {location} from {start_date} to {end_date} "
                f"within a radius of {radius_km_f} km."
            )

        coords = None
        try:
            bbox, lat, lon, city_name_final = get_city_bbox(location)
            if lat is not None and lon is not None:
                coords = {"lat": float(lat), "lon": float(lon)}
        except Exception:
            coords = None

        # Build a structured map spec that the UI can render with Pydeck.
        view_state = None
        if isinstance(coords, dict) and "lat" in coords and "lon" in coords:
            view_state = {"latitude": coords["lat"], "longitude": coords["lon"], "zoom": 7}
        elif points:
            try:
                view_state = {"latitude": float(points[0]["lat"]), "longitude": float(points[0]["lon"]), "zoom": 7}
            except Exception:
                view_state = {"latitude": 0.0, "longitude": 0.0, "zoom": 2}
        else:
            view_state = {"latitude": 0.0, "longitude": 0.0, "zoom": 2}

        return make_tool_response(
            tool_name="detect_fire_tool",
            message=message,
            artifacts={
                "maps": [
                    {
                        "title": "Fires near city",
                        "points": points,
                        "view_state": view_state,
                        "tooltip": {"text": "{acq_date} {acq_time}\nBrightness: {brightness}"},
                        "fill_color": [255, 0, 0, 160],
                        "radius": 5,
                        "radius_units": "pixels",
                        "radius_min_pixels": 2,
                        "radius_max_pixels": 7,
                    }
                ],
                "thumbnails": [],
                "urls": [],
            },
            start_date=start_date,
            end_date=end_date,
            city=location,
            coordinates=coords,
            data={"radius_km": radius_km_f, "nb_fires": nb_fires},
            error=False,
        )

    except GeocodingError as e:
        return make_tool_response(
            tool_name="detect_fire_tool",
            message=str(e),
            error=True,
        )
    except Exception as e:
        return make_tool_response(
            tool_name="detect_fire_tool",
            message=f"Unexpected error during processing: {str(e)}",
            error=True,
        )
