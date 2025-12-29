#itinerary.py
import requests
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


def _build_route_path(route_data: dict) -> list[list[float]]:
    # PathLayer expects a list of [lon, lat] pairs
    coords: list[list[float]] = []
    for route in route_data.get("routes", []) or []:
        for leg in route.get("legs", []) or []:
            for step in leg.get("steps", []) or []:
                geom = (step.get("geometry") or {}).get("coordinates") or []
                for pair in geom:
                    try:
                        lon, lat = pair
                        coords.append([float(lon), float(lat)])
                    except Exception:
                        continue
    # Deduplicate adjacent duplicates
    cleaned: list[list[float]] = []
    for p in coords:
        if not cleaned or cleaned[-1] != p:
            cleaned.append(p)
    return cleaned


@tool("get_route_info", return_direct=True)
def get_route_info(source: str | None = None, destination: str | None = None, query: str | None = None) -> dict:
    """
    Compute a driving route between two places.
    Preferred inputs:
    - source: "Paris"
    - destination: "Lyon"

    Backward-compatible input:
    - query: "Paris -> Lyon"

    Output: a structured dict with route summary (distance, duration, steps) and a saved HTML map.
    """
    start = (source or "").strip()
    end = (destination or "").strip()

    if (not start or not end) and isinstance(query, str) and query.strip():
        if "->" not in query:
            return make_tool_response(
                tool_name="get_route_info",
                message="Expected either (source, destination) or query formatted as 'Start -> End'.",
                data={"source": source, "destination": destination, "query": query},
                error=True,
            )
        start, end = [x.strip() for x in query.split("->", 1)]

    if not start or not end:
        return make_tool_response(
            tool_name="get_route_info",
            message="Please provide both 'source' and 'destination'.",
            data={"source": source, "destination": destination, "query": query},
            error=True,
        )

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

    path = _build_route_path(data)

    steps_block = "\n".join(steps_txt)
    message = (
        f"Route from {start} to {end}: distance {total_dist}, duration {total_dur}.\n"
        f"{steps_block}"
    )

    view_state = {
        "latitude": float((lat1 + lat2) / 2.0),
        "longitude": float((lon1 + lon2) / 2.0),
        "zoom": 9,
    }

    map_spec = {
        "title": f"Route: {start} → {end}",
        "view_state": view_state,
        "tooltip": {"text": ""},
        "layers": [
            {
                "type": "PathLayer",
                "data": [{"name": "route", "path": path}],
                "get_path": "path",
                "get_color": [0, 120, 255, 200],
                "width_min_pixels": 3,
                "pickable": False,
            },
            {
                "type": "ScatterplotLayer",
                "data": [{"lat": float(lat1), "lon": float(lon1), "label": f"Departure: {start}"}],
                "get_position": "[lon, lat]",
                "get_radius": 5,
                "radius_units": "pixels",
                "radius_min_pixels": 6,
                "radius_max_pixels": 7,
                "get_fill_color": [0, 200, 0, 200],
                "pickable": True,
            },
            {
                "type": "ScatterplotLayer",
                "data": [{"lat": float(lat2), "lon": float(lon2), "label": f"Arrival: {end}"}],
                "get_position": "[lon, lat]",
                "get_radius": 5,
                "radius_units": "pixels",
                "radius_min_pixels": 6,
                "radius_max_pixels": 7,
                "get_fill_color": [220, 0, 0, 200],
                "pickable": True,
            },
        ],
    }

    return make_tool_response(
        tool_name="get_route_info",
        message=message,
        artifacts={"maps": [map_spec], "thumbnails": [], "urls": []},
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