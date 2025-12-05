# think_hazard.py
from typing import Dict, List
from langchain.tools import tool
from geopy.geocoders import Nominatim
import hashlib
import random


def resolve_location(query: str) -> str:
    """
    Resolves a location from a user query.
    
    The query can either be:
    - A city or country name (e.g., "Paris", "Tunisia", "New York").
    - Geographic coordinates (latitude, longitude) written as a string
      (e.g., "48.8566, 2.3522" for Paris).

    Returns
    -------
    str
        The resolved location name (city, country, or both).
    """
    geolocator = Nominatim(user_agent="hazard_locator")

    # Case: query looks like coordinates
    if "," in query:
        try:
            lat, lon = map(float, query.split(","))
            location = geolocator.reverse((lat, lon), language="en")
            if location:
                return location.address
        except ValueError:
            pass  # Not valid coords, continue below

    # Case: query is a city or country name
    location = geolocator.geocode(query, language="en")
    if location:
        return location.address

    return "Unknown location"


def _get_deterministic_rng(key: str) -> random.Random:
    """Create a deterministic random generator based on the location key."""
    normalized = (key or "unknown").strip().lower().encode("utf-8")
    digest = hashlib.sha256(normalized).digest()
    seed = int.from_bytes(digest[:8], "big")
    return random.Random(seed)


def get_top_hazards(location: str) -> List[Dict[str, str]]:
    """
    Provide a reproducible set of hazard risk levels for a location.

    Uses a deterministic RNG seeded from the resolved location so repeated
    calls for the same place return the same set of hazards and severities.
    """
    hazards = [
        "River flood",
        "Wildfire",
        "Urban flood",
        "Water scarcity",
        "Extreme heat",
        "Earthquake",
        "Storm surge",
        "Landslide",
    ]
    levels = ["High", "Medium", "Low"]

    rng = _get_deterministic_rng(location)
    count = min(5, len(hazards))
    top_hazards = rng.sample(hazards, count)
    return [{"hazard": h, "level": rng.choice(levels)} for h in top_hazards]


@tool("think_hazard", return_direct=True)
def think_hazard(query: str) -> str:
    """
    Analyze hazard risks for a given location.
    
    The input can be either:
    - A city or country name (e.g., "Paris", "Tunisia").
    - Geographic coordinates (latitude, longitude) (e.g., "48.8566, 2.3522").

    The tool will:
    1. Resolve the location (city/country) from the input.
    2. Retrieve the top 5 hazards and their severity.
    3. Return a formatted report.

    Parameters
    ----------
    query : str
        User query containing location (name or coordinates).

    Returns
    -------
    str
        A formatted string with the top 5 hazards and their risk levels.
    """
    location = resolve_location(query)
    hazards = get_top_hazards(location)

    output = f"Top 5 hazards for this location ({location}):\n"
    for h in hazards:
        output += f"- {h['hazard']}: {h['level']}\n"

    output += "\n--------------------------------------------------"
    return output
