# flood.py
import requests
import pycountry
import dateparser
from dateparser.search import search_dates
from datetime import datetime
from typing import Optional
import folium
import re
from geopy.geocoders import Nominatim
import time
from langchain.tools import tool
from calendar import monthrange

VALID_DISASTER_TYPES = [
    "flood", "storm", "earthquake",
    "extreme temperature", "drought",
    "industrial accident", "transport"
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
    except Exception:
        return None

def filter_disasters_between_dates(events, start_date, end_date, disaster_type="flood"):
    filtered = []
    for event in events:
        #Gestion differente pour les  accidents industriels et transport
        if disaster_type == "industrial accident":
            if event.get("subgroupname", "").lower() != "industrial accident":
                continue
        elif disaster_type == "transport":
            if event.get("subgroupname", "").lower() != "transport":
                continue
        else:
            if event.get("disastertype", "").lower() != disaster_type:
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

def extract_dates_from_text(date_text: str) -> Optional[tuple[datetime.date, datetime.date]]:
    """
    Extract a start_date and end_date from free text using only search_dates.

    Rules:
    - Use `search_dates` to detect date expressions in the text.
    - If multiple dates are detected, start_date = min(date) and end_date = max(date).
    - If a single date expression is detected:
      - If the matched phrase looks like a four-digit year (e.g. "2024"), treat as full year
        (start_date = YYYY-01-01, end_date = YYYY-12-31).
      - If the matched phrase contains a month but no day, treat as that full month
        (start_date = first day of month, end_date = last day of month).
      - Otherwise treat as a single-day period (start_date == end_date).
    - If nothing is found, return None.
    """
    date_text = (date_text or "").strip()
    try:
        parsed = search_dates(date_text, languages=["fr", "en"], settings={"DATE_ORDER": "DMY"})
    except Exception:
        parsed = None

    if not parsed:
        return None

    # parsed: list of (matched_text, datetime)
    tuples = [(m[0].strip(), m[1]) for m in parsed if m and isinstance(m[1], datetime)]
    if not tuples:
        return None

    # If multiple detected -> take min/max
    if len(tuples) >= 2:
        dates = sorted([t[1] for t in tuples])
        return dates[0].date(), dates[-1].date()

    # Single match: examine the matched phrase and the datetime to decide range handling
    match_text, dt = tuples[0]
    # If the matched text is just a 4-digit year use the full year
    mt = match_text.strip()
    if mt.isdigit() and len(mt) == 4:
        year = int(mt)
        start = datetime(year, 1, 1).date()
        end = datetime(year, 12, 31).date()
        return start, end

    # Check for month-only (no explicit day). We decide this by checking for a day token
    # (a numeric token representing a day like '1' or '01' or '1er'). If absent and dt.day == 1,
    # we treat the expression as month-year and set the end to the month last day.
    tokens = [t.strip().lower() for t in mt.replace(',', ' ').split() if t.strip()]
    has_day_token = False
    for token in tokens:
        # simple digit
        if token.isdigit():
            try:
                val = int(token)
                if 1 <= val <= 31:
                    has_day_token = True
                    break
            except Exception:
                pass
        # french ordinal like '1er'
        if token.endswith('er') and token[:-2].isdigit():
            has_day_token = True
            break

        if not has_day_token and dt.month and dt.year:
            # month-only: end = last day of the month
            _, last_day = monthrange(dt.year, dt.month)
            start = datetime(dt.year, dt.month, 1).date()
            end = datetime(dt.year, dt.month, last_day).date()
            return start, end

    # Default single day
    return dt.date(), dt.date()

def generate_disaster_map(events, disaster_type="flood", country="Unknown", start_date=None, map_filename=None):
    # Always force the map filename to 'map.html'
    map_filename = "map.html"

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
    return map_filename


@tool
def query_disaster_events_tool(params: str) -> dict:
    """
    Search for natural & technological disasters
    (flood, storm, earthquake, extreme temperature, drought,
    industrial accident, transport) in a country and for a given date or date range.
    
    params : free text like "France 2015-06-29 temperature"
    """

    words = params.split()
    if not words:
        return {"message": "Empty input.", "error": True}

    country_name = words[0]  # first word = country
    rest = ' '.join(words[1:])
    # Use search_dates to extract date(s) from the rest

    disaster_words = [w for w in rest.split() if w.strip()]
    disaster_type = ' '.join(disaster_words).lower() or 'flood'

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
        return {"message": f"Country '{country_name}' not recognized.", "error": True}

    # -----------------------
    # Date extraction
    # -----------------------
    dates = extract_dates_from_text(params)
    if not dates:
        return {"message": f"Unable to interpret the date or date range", "error": True}
    start_date, end_date = dates

    # -----------------------
    # Retrieve events
    # -----------------------
    events = get_emdat_by_iso3(iso3)
    if not events:
        return {"message": f"No data found for country '{country_name}' (code {iso3}).", "error": True}

    filtered = filter_disasters_between_dates(events, start_date, end_date, disaster_type)
    if not filtered:
        return {
            "message": f"No '{disaster_type}' events found in {country_name} between {start_date} and {end_date}.",
            "downstream_task": "disaster_events",
            "start_date": start_date.strftime('%d-%m-%Y'),
            "end_date": end_date.strftime('%d-%m-%Y'),
            "location": {"country": country_name, "state": "", "city": ""},
            "events": [],
            "error": False,
        }

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

    return {
        "message": human_text,
        "downstream_task": "disaster_events",
        "start_date": start_date.strftime('%d-%m-%Y'),
        "end_date": end_date.strftime('%d-%m-%Y'),
        "location": {"country": country_name, "state": "", "city": ""},
        "events": events_list,
        "map_file": map_file,
        "error": False,
    }