# disaster_detection.py
import requests
import pycountry 
from datetime import datetime
import hashlib
import colorsys
import re
from geopy.geocoders import Nominatim
import time
from langchain.tools import tool

from .contracts import make_tool_response
from typing import Optional

VALID_DISASTER_TYPES = [
    "flood", "storm", "earthquake",
    "extreme temperature", "drought",
    "industrial accident", "transport"
]

_MAX_GEOCODE_ATTEMPTS = 10

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
    except Exception:
        return None

def filter_disasters_between_dates(events, start_date, end_date, disaster_type="flood"):
    filtered = []
    start_date = datetime.strptime(start_date, "%Y-%m-%d")
    end_date = datetime.strptime(end_date, "%Y-%m-%d")
    # Now you can get the date part
    start_date = start_date.date()
    end_date = end_date.date()
    for event in events:
        #Gestion differente pour les  accidents industriels et transport
        if "industrial accident" in disaster_type:
            if "industrial accident" not in event.get("subgroupname", "").lower():
                continue
        elif "transport" in disaster_type:
            if "transport" not in event.get("subgroupname", "").lower():
                continue
        elif "extreme temperature" in disaster_type:
            if "extreme temperature" not in event.get("disastertype", "").lower():
                continue
        elif "drought" in disaster_type:
            if "drought" not in event.get("disastertype", "").lower():
                continue
        elif "storm" in disaster_type:
            if "storm" not in event.get("disastertype", "").lower():
                continue
        elif "earthquake" in disaster_type:
            if "earthquake" not in event.get("disastertype", "").lower():
                continue
        elif "flood" in disaster_type:
            if "flood" not in event.get("disastertype", "").lower():
                continue
        else:
            if disaster_type not in event.get("disastertype", "").lower():
                continue

        try:
            start_event = datetime(
                event.get("startyear", 0),
                event.get("startmonth", 0),
                event.get("startday", 0) or 1
            ).date()
            end_event = datetime(
                event.get("endyear", 0) or event.get("startyear", 0),
                event.get("endmonth", 0) or event.get("startmonth", 0),
                event.get("endday", 0) or event.get("startday", 0) or 1
            ).date()
        except Exception:
            continue
        print(f"Event from {start_event} to {end_event}")
        print(f"Filtering between {start_date} and {end_date}")
        if start_event <= end_date and end_event >= start_date:
            filtered.append(event)
    return filtered


def _safe_float(x) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _infer_view_state(points: list[dict]) -> dict:
    if not points:
        return {"latitude": 0.0, "longitude": 0.0, "zoom": 2}
    lats = [p.get("lat") for p in points if isinstance(p.get("lat"), (int, float))]
    lons = [p.get("lon") for p in points if isinstance(p.get("lon"), (int, float))]
    if not lats or not lons:
        return {"latitude": 0.0, "longitude": 0.0, "zoom": 2}
    return {
        "latitude": float(sum(lats) / len(lats)),
        "longitude": float(sum(lons) / len(lons)),
        "zoom": 3,
    }


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
    """Deterministic per-type color.
    """
    t = (disaster_type or "").strip().lower()
    if t=="flood":
        return [0, 0, 255, 200]
    if t=="storm":
        return [128, 0, 128, 200]
    if t=="earthquake":
        return [139, 69, 19, 200]
    if t=="extreme temperature" or t=="temperature":
        return [255, 69, 0, 200]
    if t=="drought":
        return [210, 180, 140, 200]
    if t=="industrial accident" or t=="accident":
        return [105, 105, 105, 200]
    if t=="transport":
        return [0, 128, 0, 200]
    # Default: hash to color
    return [100,100,100,200]  
    


@tool(return_direct=True)
def query_disaster_events_tool(
    start_date: str,
    end_date: str | None,
    country_name: str,
    location: str | None = None,
    disaster_type: str = "flood",
) -> dict:
    """
    Search for natural & technological disasters
    (flood, storm, earthquake, extreme temperature, drought,
    industrial accident, transport) in a country and for a given date or date range.
    start_date: YYYY-MM-DD
    end_date: YYYY-MM-DD (optional, if not provided, only start_date is used)
    location: Specific location within the country if available
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

    print(f"Extracted params - start_date: {start_date}, end_date: {end_date}, country: {country_name}, disaster_type: {disaster_type}")
    if not disaster_type:
        disaster_type = "flood"  # default
    # Ajustements pour certains types
    if "temperature" in disaster_type:
        disaster_type = "extreme temperature"
    elif "accident" in disaster_type:
        disaster_type = "industrial accident"
    elif "transport" in disaster_type:
        disaster_type = "transport"

    # -----------------------
    # Country ISO3 code
    # -----------------------
    iso3 = get_iso3_from_country_name(country_name)
    if not iso3:
        return make_tool_response(
            tool_name="query_disaster_events_tool",
            message=f"Country '{country_name}' not recognized.",
            country=country_name,
            start_date=start_date,
            end_date=end_date,
            data={"disaster_type": disaster_type},
            error=True,
        )

    # -----------------------
    # Retrieve events
    # -----------------------
    events = get_emdat_by_iso3(iso3)
    if not events:
        human_text = f"No data found for country '{country_name}' (code {iso3})."
        return make_tool_response(
            tool_name="query_disaster_events_tool",
            message=human_text,
            country=country_name,
            start_date=start_date,
            end_date=end_date,
            data={"disaster_type": disaster_type, "iso3": iso3, "events": []},
            error=False,
        )
    filtered = filter_disasters_between_dates(events, start_date, end_date, disaster_type)
    if not filtered:
        human_text = f"No '{disaster_type}' events found in {country_name} between {start_date} and {end_date}."
        return make_tool_response(
            tool_name="query_disaster_events_tool",
            message=human_text,
            country=country_name,
            start_date=start_date,
            end_date=end_date,
            data={"disaster_type": disaster_type, "iso3": iso3, "events": []},
            error=False,
        )

    # Construction de la réponse
    # 
    # Build event summaries and raw events list
    events_list = []
    map_points: list[dict] = []
    geolocator = Nominatim(user_agent="disaster_mapper")
    geocode_attempts = 0
    geocode_success = 0
    for e in filtered:
        lat = _safe_float(e.get("latitude"))
        lon = _safe_float(e.get("longitude"))

        if (lat is None or lon is None) and geocode_attempts < _MAX_GEOCODE_ATTEMPTS:
            location_name = e.get("location")
            country_e = e.get("country", "")
            if isinstance(location_name, str) and location_name.strip():
                places = [p.strip() for p in re.split(',|;', location_name) if p.strip()]
                for place in places:
                    geocode_attempts += 1
                    try:
                        loc = geolocator.geocode(f"{place}, {country_e}", timeout=10)
                        if loc:
                            lat = float(loc.latitude)
                            lon = float(loc.longitude)
                            geocode_success += 1
                            time.sleep(1)
                            break
                    except Exception as ex:
                        print(f"Geocoding error for {place}: {ex}")
                        continue

        if isinstance(lat, float) and isinstance(lon, float):
            dtype = e.get('disastertype', e.get('subgroupname', ''))
            map_points.append(
                {
                    "lat": lat,
                    "lon": lon,
                    "type": dtype,
                    "country": e.get('country'),
                    "location": e.get('location'),
                    "start_date": f"{e.get('startyear', '?')}-{e.get('startmonth', '?')}-{e.get('startday', '?')}",
                    "end_date": f"{e.get('endyear', e.get('startyear', '?'))}-{e.get('endmonth', e.get('startmonth', '?'))}-{e.get('endday', e.get('startday', '?'))}",
                    "total_deaths": e.get('totaldeaths'),
                    "total_affected": e.get('totalaffected'),
                    "origin": e.get('origin'),
                    "emoji": _emoji_for_disaster_type(str(dtype)),
                    "color": _color_for_disaster_type(str(dtype)),
                }
            )

        events_list.append({
            "type": e.get('disastertype', e.get('subgroupname', '')),
            "country": e.get('country'),
            "location": e.get('location'),
            "start_date": f"{e.get('startyear', '?')}-{e.get('startmonth', '?')}-{e.get('startday', '?')}",
            "end_date": f"{e.get('endyear', e.get('startyear', '?'))}-{e.get('endmonth', e.get('startmonth', '?'))}-{e.get('endday', e.get('startday', '?'))}",
            "total_deaths": e.get('totaldeaths'),
            "total_affected": e.get('totalaffected'),
            "origin": e.get('origin'),
            "latitude": e.get('latitude'),
            "longitude": e.get('longitude'),
        })

    human_text = f"{len(events_list)} '{disaster_type}' event(s) found in {country_name} between {start_date} and {end_date}."
    if geocode_attempts:
        human_text += f" Geocoded {geocode_success}/{geocode_attempts} missing locations."

    artifacts = {"maps": [], "thumbnails": [], "urls": []}
    if disaster_type != "transport" and map_points:
        artifacts["maps"].append(
            {
                "title": f"{disaster_type.capitalize()} events in {country_name}",
                "view_state": _infer_view_state(map_points),
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

    return make_tool_response(
        tool_name="query_disaster_events_tool",
        message=human_text,
        artifacts=artifacts,
        country=country_name,
        start_date=start_date,
        end_date=end_date,
        data={
            "disaster_type": disaster_type,
            "iso3": iso3,
            "events": events_list,
        },
        error=False,
    )
