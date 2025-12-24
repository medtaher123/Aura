# disaster_detection.py
import requests
import pycountry 
from datetime import datetime
import folium
import re
from geopy.geocoders import Nominatim
import time
from langchain.tools import tool
from src.services.params_extraction import extract_params_from_text

from .contracts import make_tool_response
from pathlib import Path

VALID_DISASTER_TYPES = [
    "flood", "storm", "earthquake",
    "extreme temperature", "drought",
    "industrial accident", "transport"
]

MAPS_DIR = Path(__file__).resolve().parents[1] / "maps"
MAPS_DIR.mkdir(parents=True, exist_ok=True)

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

def format_event_human_readable(event):
    start_date = f"{event.get('startday', '?')}/{event.get('startmonth', '?')}/{event.get('startyear', '?')}"
    end_date = f"{event.get('endday', '?')}/{event.get('endmonth', '?')}/{event.get('endyear', '?')}"

    disaster_emoji = {
        "flood": "🌊",
        "storm": "🌪️",
        "earthquake": "🏔️",
        "extreme temperature": "🥵",
        "drought": "🌵",
        "industrial accident": "🏭",
        "transport": "✈️"
    }.get(event.get("disastertype", "").lower(), "❗")

    return (
        f"{disaster_emoji} **{event.get('disastertype', event.get('subgroupname', '')).capitalize()} in {event.get('country', '?')} ({event.get('location', 'Unknown location')})**\n"
        f"📍 Location: {event.get('location', 'Unknown')}\n"
        f"📅 From {start_date} to {end_date}\n"
        f"☠️ Deaths: {event.get('totaldeaths', 'Not specified')}\n"
        f"👥 People affected: {event.get('totalaffected', 'Not specified')}\n"
        f"🧭 Origin: {event.get('origin', 'Not specified')}\n"
        "--------------------------------------------------"
    )

def generate_disaster_map(events, disaster_type="flood", country="Unknown", start_date=None, map_filename=None):
    # Always force the map filename to 'Map.html'
    map_filename = MAPS_DIR / "Map.html"

    map_ = folium.Map(location=[45, 10], zoom_start=4)
    geolocator = Nominatim(user_agent="disaster_mapper")

    for event in events:
        location_name = event.get("location")
        country_name = event.get("country", "")
        lat = event.get("latitude")
        lon = event.get("longitude")

        start = f"{event.get('startday', '?')}/{event.get('startmonth', '?')}/{event.get('startyear', '?')}"
        end = f"{event.get('endday', '?')}/{event.get('endmonth', '?')}/{event.get('endyear', '?')}"
        popup_text = f"{location_name or 'Unknown location'}, {country_name}<br>From {start} to {end}"

        icon_color = {
            "flood": "blue",
            "storm": "darkred",
            "earthquake": "green",
            "extreme temperature": "orange",
            "drought": "beige",
            "industrial accident": "black",
            "transport": "purple"
        }.get(disaster_type, "gray")

        if lat and lon:
            try:
                folium.Marker(
                    location=[float(lat), float(lon)],
                    popup=popup_text,
                    icon=folium.Icon(color=icon_color, icon='info-sign')
                ).add_to(map_)
                continue
            except:
                pass

        if location_name:
            places = [p.strip() for p in re.split(',|;', location_name) if p.strip()]
            for place in places:
                try:
                    loc = geolocator.geocode(f"{place}, {country_name}", timeout=10)
                    if loc:
                        folium.Marker(
                            location=[loc.latitude, loc.longitude],
                            popup=popup_text,
                            icon=folium.Icon(color=icon_color, icon='info-sign')
                        ).add_to(map_)
                        time.sleep(1)
                        break
                except Exception as e:
                    print(f"Geocoding error for {place}: {e}")
                    continue

    map_.save(map_filename)
    print(f"Map generated: {map_filename} (open it in a browser)")
    return map_filename.name


@tool(return_direct=True)
def query_disaster_events_tool(params: str) -> dict:
    """
    Search for natural & technological disasters
    (flood, storm, earthquake, extreme temperature, drought,
    industrial accident, transport) in a country and for a given date or date range.
    
    params : user_query "flood events in France in 2020", "industrial accidents in Germany in septembre 2019".
    """

    start_date, end_date, location, country_name, radius_km, disaster_type = extract_params_from_text(params)
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

    # Generating the map

    map_file = None
    if disaster_type != "transport":  # no map for transport
        map_file = generate_disaster_map(filtered, disaster_type, country_name, start_date)

    # Construction de la réponse
    # 
    # Build event summaries and raw events list
    events_list = []
    for e in filtered:
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
    if map_file:
        human_text += f" Map generated: {map_file}"

    artifacts = {"maps": [], "thumbnails": [], "urls": []}
    if isinstance(map_file, str) and map_file.endswith(".html"):
        artifacts["maps"].append(map_file)

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
