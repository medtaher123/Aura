# fire_detection.py
from datetime import datetime, timedelta, date
import time
import pandas as pd
import requests
import folium
import numpy as np
import os
from pathlib import Path
from langchain_ollama import OllamaLLM

MAP_KEY = "f44596f0cc01c26985abd6bfff78ac92"
ARCHIVE_DIR = "./Data"
MAPS_DIR = Path(__file__).resolve().parents[1] / "maps"
MAPS_DIR.mkdir(parents=True, exist_ok=True)

# ARCHIVE_DIR = r"C:\MEPDev\LLM_Demo\langgraph_project\Data"


# Calculate the great-circle distance between two points on the Earth (Haversine formula)
def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


# Get latitude and longitude for a city name using OpenStreetMap Nominatim API
def get_city_coordinates(city_name):
    print("Getting coordinates for city:", city_name)
    url = (
        f"https://nominatim.openstreetmap.org/search?q={city_name}&format=json&limit=1"
    )
    for attempt in range(5):
        try:
            print('trying to get city coordinates, attempt', attempt + 1)
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            data = response.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])         
        except Exception:
            if attempt < 4:
                print("Retrying...")
                time.sleep(1)
                continue
            return None, None


# Find the archive file that contains data for the given date
def find_archive_file_for_range(start_date_obj, end_date_obj):
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
            full_path = os.path.join(ARCHIVE_DIR, sf["filename"])
            print("Using special file:", full_path)
            if os.path.exists(full_path):
                return full_path

    # ---- DEFAULT LOGIC FOR ALL OTHER ARCHIVE FILES ----
    for filename in sorted(os.listdir(ARCHIVE_DIR)):
        print("Checking archive file:", filename)
        if filename.endswith(".csv") and "fire_archive_" in filename:
            try:
                parts = filename.replace(".csv", "").split("_")
                start_year = int(parts[2])
                end_year = int(parts[3])

                file_start = datetime(start_year, 1, 21).date()
                file_end = datetime(end_year, 1, 20).date()

                # Check overlap
                if not (end_date_obj < file_start or start_date_obj > file_end):
                    return os.path.join(ARCHIVE_DIR, filename)

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

    lat_city, lon_city = get_city_coordinates(city_name)
    print("City coordinates:", lat_city, lon_city)
    if lat_city is None:
        return None

    use_api = should_use_api(start_date, end_date)

    if use_api:
        print("Using API for fire data")
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/VIIRS_NOAA20_NRT/world/3"
        df = pd.read_csv(url)
    else:
        file_path = find_archive_file_for_range(start_date_obj, end_date_obj)
        print("Using archive file for fire data:", file_path)
        if not file_path:
            print("No archive file found for the given date range.")
            return None
        df = pd.read_csv(file_path)

    # Ensure date column exists
    if "acq_date" not in df.columns:
        print("Date column 'acq_date' not found in data.")
        return None

    df["acq_date"] = pd.to_datetime(df["acq_date"]).dt.date
    df = df[
        (df["acq_date"] >= start_date_obj) & (df["acq_date"] <= end_date_obj)
    ].copy()
    if df.empty:
        return None

    df["distance"] = df.apply(
        lambda row: haversine(lat_city, lon_city, row["latitude"], row["longitude"]),
        axis=1,
    )
    df_filtered = df[df["distance"] <= radius_km]

    m = folium.Map(location=[lat_city, lon_city], zoom_start=7)
    for _, row in df_filtered.iterrows():
        popup = f"Brightness: {row.get('brightness', row.get('bright_ti4', 'N/A'))}, Date: {row['acq_date']}, Time: {row['acq_time']}"
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=5,
            color="red",
            fill=True,
            fill_color="red",
            fill_opacity=0.7,
            popup=popup,
        ).add_to(m)

    filename = MAPS_DIR / "Fires.html"
    m.save(filename)
    return filename.name, len(df_filtered)


def extract_params_from_text(text: str):
    """
    Extracts start_date, end_date, city/location, and radius using a single LLM call.
    Returns: (start_date, end_date, location, radius_km)
    """
    if not text:
        return None, None, None, 100

    # --- Build LLM extraction prompt ---
    system_prompt = """
    You are an expert system that extracts structured data from natural language.
    Your job is to identify:
    - start_date (YYYY-MM-DD or null)
    - end_date (YYYY-MM-DD or null)
    - location (city, region, or country)
    - radius_km (integer or null)
    
    RULES:
    - If only one date is mentioned, set start_date = end_date.
    - If a year is mentioned alone (e.g. "in 2022"), return full year range.
    - If a month is mentioned ("in July 2023"), return first and last day.
    - If a season is mentioned (winter, summer, etc.), use:
        * winter: Dec 1 – Feb 28
        * spring: Mar 1 – May 31
        * summer: Jun 1 – Aug 31
        * autumn/fall: Sep 1 – Nov 30
    - If radius is not mentioned, return null.
    - ALWAYS answer with pure JSON. NO explanations.
    """

    few_shot = """
    Example 1:
    User input: "Marseille 2025-01 - 250"
    Response:
    {
      "start_date": "2025-01-01",
      "end_date": "2025-01-31",
      "location": "Marseille",
      "radius_km": 250
    }

    Example 2:
    User input: "Tunis summer 50"
    Response:
    {
      "start_date": "2024-06-01",
      "end_date": "2024-08-31",
      "location": "Tunis",
      "radius_km": 50
    }

    Example 3:
    User input: "Rome December 1st to December 10th 2023"
    Response:
    {
      "start_date": "2023-12-01",
      "end_date": "2023-12-10",
      "location": "Rome",
      "radius_km": null
    }

    Example 4:
    User input: "Morocco"
    Response:
    {
      "start_date": null,
      "end_date": null,
      "location": "Morocco",
      "radius_km": null
    }
    """

    # --- Invoke LLM ---
    llm = OllamaLLM(model="mistral", temperature=0.1, system_prompt=system_prompt)
    prompt = f'{few_shot}\nUser input: "{text}"\nReturn JSON:'
    llm_response = llm.invoke(prompt)

    import json

    try:
        data = json.loads(llm_response)
    except Exception:
        return {"error": f"❌ LLM returned invalid JSON: {llm_response}"}

    # --- Extract fields ---
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    location = data.get("location")
    radius_km = data.get("radius_km") or 100  # default radius

    return start_date, end_date, location, radius_km


from langchain.tools import tool


@tool(return_direct=True)
def detect_fire_tool(query_text: str) -> str:
    """
    Tool to detect fires from a natural language query.
    """
    try:
        print("Detecting fire with query:", query_text)
        start_date, end_date, city, radius_km = extract_params_from_text(query_text)
        print("Extracted parameters:", start_date, end_date, city, radius_km)

        if not start_date or not city:
            return (
                "ERROR: Please specify a city and a date (YYYY-MM-DD, month, or year) "
                "in your query."
            )

        result = detect_fire_near_city(start_date, end_date, city, radius_km)
        print("Detection result:", result)
        # NO FIRES FOUND
        if not result:
            if start_date == end_date:
                message = (
                    f"There were no fires detected near {city} on {start_date} "
                    f"within a radius of {radius_km} km."
                )
            else:
                message = (
                    f"There were no fires detected near {city} from {start_date} to {end_date} "
                    f"within a radius of {radius_km} km."
                )
            return f"Final Answer: {message}"

        # FIRES FOUND
        file_html, nb_fires = result

        if start_date == end_date:
            message = (
                f"{nb_fires} fire(s) detected near {city} on {start_date} "
                f"within a radius of {radius_km} km.\nMap: {file_html}"
            )
        else:
            message = (
                f"{nb_fires} fire(s) detected near {city} from {start_date} to {end_date} "
                f"within a radius of {radius_km} km.\nMap: {file_html}"
            )

        return f"Final Answer: {message}"

    except Exception as e:
        return f"ERROR: Unexpected error during processing: {str(e)}"
