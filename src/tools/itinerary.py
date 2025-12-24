#itinerary.py
import requests
import folium
from pathlib import Path
from langchain.tools import tool

from .contracts import make_tool_response

# Geocoding via Nominatim (OpenStreetMap)
def geocode_place(place_name):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": place_name, "format": "json", "limit": 3}
    r = requests.get(url, params=params, headers={"User-Agent": "route-steps-app"})
    r.raise_for_status()
    data = r.json()
    if not data:
        return None, None
    return float(data[0]["lat"]), float(data[0]["lon"])


# Route via OSRM (driving)
def get_route(origin, destination):
    base = "http://router.project-osrm.org/route/v1/driving"
    url = f"{base}/{origin[1]},{origin[0]};{destination[1]},{destination[0]}"
    params = {
        "overview": "false",
        "steps": "true",
        "alternatives": "false",
        "geometries": "geojson"
    }
    r = requests.get(url, params=params, headers={"User-Agent": "route-steps-app"})
    r.raise_for_status()
    return r.json()


def human_distance(m):
    if m < 1000:
        return f"{int(round(m))} m"
    km = m / 1000.0
    return f"{km:.1f} km"

def human_duration(sec):
    minutes = int(round(sec / 60.0))
    if minutes < 60:
        return f"{minutes} min"
    h = minutes // 60
    m = minutes % 60
    return f"{h} h {m} min" if m else f"{h} h"

def modifier_en(mod):
    return {
        "left": "left",
        "right": "right",
        "slight left": "slight left",
        "slight right": "slight right",
        "sharp left": "sharp left",
        "sharp right": "sharp right",
        "straight": "straight",
        "uturn": "u-turn",
        None: ""
    }.get(mod, mod if mod else "")

def road_label(step):
    name = (step.get("name") or "").strip()
    ref = (step.get("ref") or "").strip()
    if name and ref:
        return f"{ref} ({name})"
    return ref or name

def format_step(step):
    man = step.get("maneuver", {})
    stype = man.get("type")
    mod = man.get("modifier")
    exit_no = man.get("exit")
    road = road_label(step)
    dist = human_distance(step.get("distance", 0))

    dir_txt = modifier_en(mod)
    on_road = f" sur {road}" if road else ""

    if stype == "depart":
        return f"Departure{on_road}."
    if stype == "arrive":
        return "You have arrived."
    if stype == "turn":
        return f"Turn {dir_txt}{on_road} ({dist})." if dir_txt else f"Turn{on_road} ({dist})."
    if stype == "continue":
        if dir_txt and dir_txt != "straight":
            return f"Continue {dir_txt}{on_road} ({dist})."
        return f"Continue{on_road} ({dist})."
    if stype == "new name":
        return f"Continue, the road becomes{on_road} ({dist})."
    if stype == "end of road":
        return f"At the end of the road, turn {dir_txt}{on_road} ({dist})." if dir_txt else f"At the end of the road, continue{on_road} ({dist})."
    if stype in ("merge",):
        return f"Merge{on_road} ({dist})."
    if stype in ("on ramp", "ramp"):
        return f"Take the ramp {dir_txt}{on_road} ({dist})." if dir_txt else f"Take the ramp{on_road} ({dist})."
    if stype in ("off ramp",):
        return f"Take the exit {dir_txt}{on_road} ({dist})." if dir_txt else f"Take the exit{on_road} ({dist})."
    if stype in ("fork",):
        return f"At the fork, take {dir_txt}{on_road} ({dist})." if dir_txt else f"At the fork, follow{on_road} ({dist})."
    if stype in ("roundabout", "rotary"):
        return f"At the roundabout, take exit {exit_no}{on_road} ({dist})." if exit_no else f"At the roundabout, continue{on_road} ({dist})."
    if stype == "uturn":
        return f"Make a u-turn{on_road} ({dist})."

    if dir_txt and road:
        return f"{stype.capitalize()} {dir_txt} on {road} ({dist})."
    if road:
        return f"{stype.capitalize()} on {road} ({dist})."
    return f"{stype.capitalize()} ({dist})."


# Map generation
# Map generation
MAPS_DIR = Path(__file__).resolve().parents[1] / "maps"
MAPS_DIR.mkdir(parents=True, exist_ok=True)


def create_map(lat1, lon1, lat2, lon2, route_data, start, end):
    m = folium.Map(location=[lat1, lon1], zoom_start=12)
    for leg in route_data.get("routes", []):
        for l in leg.get("legs", []):
            coords = []
            for step in l.get("steps", []):
                geom = step.get("geometry", {}).get("coordinates", [])
                coords.extend([(lat, lon) for lon, lat in geom])
            if coords:
                folium.PolyLine(coords, color="blue", weight=5, opacity=0.8).add_to(m)

    folium.Marker([lat1, lon1], tooltip=f"Departure: {start}", icon=folium.Icon(color="green")).add_to(m)
    folium.Marker([lat2, lon2], tooltip=f"Arrival: {end}", icon=folium.Icon(color="red")).add_to(m)

    file_path = MAPS_DIR / "itinerary.html"
    m.save(file_path)
    return file_path.name


@tool("get_route_info", return_direct=True)
def get_route_info(query: str) -> dict:
    """
    Compute a driving route between two places.
    Input format: "Start -> End"
    Example: "Paris -> Lyon"
    Output: a structured dict with route summary (distance, duration, steps) and a saved HTML map.
    """
    if "->" not in query:
        return make_tool_response(
            tool_name="get_route_info",
            message="Expected format: 'Start -> End'.",
            error=True,
        )

    start, end = [x.strip() for x in query.split("->")]

    lat1, lon1 = geocode_place(start)
    lat2, lon2 = geocode_place(end)
    if not lat1 or not lon1 or not lat2 or not lon2:
        return make_tool_response(
            tool_name="get_route_info",
            message=f"Location not found: {start} or {end}.",
            data={"start": start, "end": end},
            error=True,
        )

    try:
        data = get_route((lat1, lon1), (lat2, lon2))
    except requests.RequestException as e:
        return make_tool_response(
            tool_name="get_route_info",
            message=f"Network error: {e}",
            data={"start": start, "end": end},
            error=True,
        )

    if not data or data.get("code") != "Ok" or not data.get("routes"):
        return make_tool_response(
            tool_name="get_route_info",
            message="Unable to compute route.",
            data={"start": start, "end": end},
            error=True,
        )

    route = data["routes"][0]
    total_dist = human_distance(route["distance"])
    total_dur = human_duration(route["duration"])

    steps_txt = []
    step_index = 1
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            steps_txt.append(f"{step_index}. {format_step(step)}")
            step_index += 1

    file_name = create_map(lat1, lon1, lat2, lon2, data, start, end)

    steps_block = "\n".join(steps_txt)
    message = (
        f"Route from {start} to {end}: distance {total_dist}, duration {total_dur}.\n"
        f"Map: {file_name}.\n{steps_block}"
    )

    return make_tool_response(
        tool_name="get_route_info",
        message=message,
        artifacts={"maps": [file_name], "thumbnails": [], "urls": []},
        data={
            "start": start,
            "end": end,
            "start_coordinates": {"lat": lat1, "lon": lon1},
            "end_coordinates": {"lat": lat2, "lon": lon2},
            "distance_human": total_dist,
            "duration_human": total_dur,
            "steps": steps_txt,
        },
        error=False,
    )