# fire_detection.py
from datetime import datetime, timedelta, date
import pandas as pd
import requests
import folium
import numpy as np
import os
import re
from dateparser.search import search_dates
from calendar import monthrange

MAP_KEY = 'f44596f0cc01c26985abd6bfff78ac92'
ARCHIVE_DIR = "/home/inesb/Metaplanet_llm-main_v1/Data"

# ARCHIVE_DIR = r"C:\MEPDev\LLM_Demo\langgraph_project\Data"

# Calculate the great-circle distance between two points on the Earth (Haversine formula)
def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi/2)**2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda/2)**2
    return 2 * R * np.arcsin(np.sqrt(a))

# Get latitude and longitude for a city name using OpenStreetMap Nominatim API
def get_city_coordinates(city_name):
    url = f'https://nominatim.openstreetmap.org/search?q={city_name}&format=json&limit=1'
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = response.json()
        if not data:
            return None, None
        return float(data[0]['lat']), float(data[0]['lon'])
    except:
        return None, None

# Find the archive file that contains data for the given date
def find_archive_file_for_range(start_date_obj, end_date_obj):
    for filename in sorted(os.listdir(ARCHIVE_DIR)):
        if filename.endswith(".csv") and "fire_archive_" in filename:
            try:
                parts = filename.replace(".csv","").split("_")
                start_year = int(parts[2])
                end_year   = int(parts[3])
                file_start = datetime(start_year,1,21).date()
                file_end   = datetime(end_year,1,20).date()

                # Check if ranges overlap
                if not (end_date_obj < file_start or start_date_obj > file_end):
                    return os.path.join(ARCHIVE_DIR, filename)
            except:
                continue

    return None


# Decide whether to use the API (for recent dates) or archives (for older dates)
def should_use_api(start_date, end_date):
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
    return end_date_obj >= (date.today() - timedelta(days=7))


# Detect fires near a city for a given date and radius (km)
def detect_fire_near_city(start_date, end_date, city_name, radius_km=100):
    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_date_obj   = datetime.strptime(end_date, "%Y-%m-%d").date()

    lat_city, lon_city = get_city_coordinates(city_name)
    if lat_city is None:
        return None

    use_api = should_use_api(start_date, end_date)

    if use_api:
        url = f'https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/VIIRS_NOAA20_NRT/world/3'
        df = pd.read_csv(url)
    else:
        file_path = find_archive_file_for_range(start_date_obj, end_date_obj)
        if not file_path:
            return None
        df = pd.read_csv(file_path)

    # Ensure date column exists
    if "acq_date" not in df.columns:
        return None

    df["acq_date"] = pd.to_datetime(df["acq_date"]).dt.date
    df = df[(df["acq_date"] >= start_date_obj) & (df["acq_date"] <= end_date_obj)].copy()
    if df.empty:
        return None

    df["distance"] = df.apply(lambda row: haversine(lat_city, lon_city, row["latitude"], row["longitude"]), axis=1)
    df_filtered = df[df["distance"] <= radius_km]

    m = folium.Map(location=[lat_city, lon_city], zoom_start=7)
    for _, row in df_filtered.iterrows():
        popup = f"Brightness: {row.get('brightness', row.get('bright_ti4', 'N/A'))}, Date: {row['acq_date']}, Time: {row['acq_time']}"
        folium.CircleMarker(
            location=[row['latitude'], row['longitude']],
            radius=5,
            color='red',
            fill=True,
            fill_color='red',
            fill_opacity=0.7,
            popup=popup
        ).add_to(m)

    filename = f"fires_{city_name.lower().replace(' ', '_')}_{start_date}_to_{end_date}.html"
    m.save(filename)
    return filename, len(df_filtered)


# Extract ISO date(s), city name, and radius (km) from natural language queries
from typing import Optional, Tuple
from dateparser.search import search_dates

def extract_dates_from_text(date_text: str) -> Optional[Tuple[str, str]]:
    """
    Extract a start_date and end_date from free text using only search_dates.
    Logic adapted from flood_detection.py.
    Returns (start_date, end_date) as YYYY-MM-DD strings, or (None, None) if not found.
    """
    iso_day = re.findall(r"\b(\d{4})-(\d{2})-(\d{2})\b", date_text)
    if iso_day:
        y, m, d = iso_day[0]
        return f"{y}-{m}-{d}", f"{y}-{m}-{d}"

    # detect YYYY-MM next
    iso_month = re.findall(r"\b(\d{4})-(\d{2})\b", date_text)
    if iso_month:
        y, m = iso_month[0]
        last = monthrange(int(y), int(m))[1]
        return f"{y}-{m}-01", f"{y}-{m}-{last:02d}"

    date_text = (date_text or "").strip()
    try:
        parsed = search_dates(date_text, languages=["fr", "en"], settings={"DATE_ORDER": "DMY"})
    except Exception:
        parsed = None

    if not parsed:
        return None, None

    tuples = [(m[0].strip(), m[1]) for m in parsed if m and isinstance(m[1], datetime)]
    if not tuples:
        return None, None

    if len(tuples) >= 2:
        dates = sorted([t[1] for t in tuples])
        return dates[0].strftime("%Y-%m-%d"), dates[-1].strftime("%Y-%m-%d")

    match_text, dt = tuples[0]
    mt = match_text.strip()
    if mt.isdigit() and len(mt) == 4:
        year = int(mt)
        start = datetime(year, 1, 1)
        end = datetime(year, 12, 31)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    tokens = [t.strip().lower() for t in mt.replace(',', ' ').split() if t.strip()]
    has_day_token = False
    for token in tokens:
        if token.isdigit():
            try:
                day = int(token)
                if 1 <= day <= 31:
                    has_day_token = True
                    break
            except Exception:
                pass
        if token.endswith('er') and token[:-2].isdigit():
            has_day_token = True
            break
    if not has_day_token and dt.month and dt.year:
        
        _, last_day = monthrange(dt.year, dt.month)
        start = datetime(dt.year, dt.month, 1)
        end = datetime(dt.year, dt.month, last_day)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    return dt.strftime("%Y-%m-%d"), dt.strftime("%Y-%m-%d")

def extract_params_from_text(text):
    """
    Extract start_date, end_date, city name, and radius (km) from natural language queries.
    """
    if not text:
        return None, None, None, 100

    cleaned_text = " ".join(text.split())
    lower_text = cleaned_text.lower()

    # Extract radius
    rayon_match = re.search(r"(\d+)\s?km", lower_text)
    rayon_km = int(rayon_match.group(1)) if rayon_match else 100

    # Extract city (keep logic, but can be improved)
    city = None
    city_patterns = [
        r"(?:\bà|\ba|\bau|\baux|\bdans|\bautour de|\bprès de|\bproche de|\bvers|\bsur)\s+([A-Za-zÀ-ÖØ-öø-ÿ'\-\s]+?)(?=(?:\s+(?:en|le|la|du|de|des|au|aux|pendant|pour|sur|vers|\d)|[\.,!?]|$))"
    ]
    for pattern in city_patterns:
        match = re.search(pattern, cleaned_text, flags=re.IGNORECASE)
        if match:
            city = match.group(1).strip()
            break
    if not city:
        # Fallback: try to find a capitalized word (likely a city)
        tokens = cleaned_text.split()
        for token in tokens:
            if token.istitle():
                city = token
                break
    if city:
        city = re.sub(r"[\.,!?]+$", "", city).strip()
        city = city.title()

    # Extract date(s) using the new logic
    print( "Extracting dates from text:", cleaned_text )
    start_date, end_date = extract_dates_from_text(cleaned_text)
    print( "Extracted dates:", start_date, end_date )
    return start_date, end_date, city, rayon_km

from langchain.tools import tool

@tool
def detect_fire_tool(query_text: str) -> dict:
    """
    Tool to detect fires from a natural language query.
    This function receives a sentence containing a city, a date (YYYY-MM-DD, month, or year),
    and optionally a radius in kilometers. It extracts this information and returns a JSON object with the result, following the required format.
    """
    try:
        start_date, end_date, city, radius_km = extract_params_from_text(query_text)

        if not start_date or not city:
            return {
                "message": "Please specify a city and a date (YYYY-MM-DD, month, or year) in your query.",
                "error": True
            }

        # Only support single-day queries for now
        if start_date != end_date:
            # Use the first day for detection
            date_str = start_date
        else:
            date_str = start_date

        result = detect_fire_near_city(start_date, end_date, city, radius_km)

        if not result:
            return {
                "message": f"No fire detected or there was a problem processing the request for {city} on {date_str}.",
                "downstream_task": "detect_fire_tool",
                "start_date": date_str[8:10] + '-' + date_str[5:7] + '-' + date_str[0:4],
                "end_date": date_str[8:10] + '-' + date_str[5:7] + '-' + date_str[0:4],
                "location": {
                    "country": "",
                    "state": "",
                    "city": city
                },
                "error": False
            }

        file_html, nb_fires = result
        message = f"{nb_fires} fire(s) detected near {city} on {date_str} within a radius of {radius_km} km.\nMap: {file_html}"
        return {
            "message": message,
            "downstream_task": "detect_fire_tool",
            "start_date": date_str[8:10] + '-' + date_str[5:7] + '-' + date_str[0:4],
            "end_date": date_str[8:10] + '-' + date_str[5:7] + '-' + date_str[0:4],
            "location": {
                "country": "",
                "state": "",
                "city": city
            },
            "error": False
        }

    except Exception as e:
        return {
            "message": f"Unexpected error during processing: {str(e)}",
            "error": True
        }