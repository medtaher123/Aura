"""
Data360 Hazards Module for MCP

Provides functions to query World Bank ThinkHazard data.
"""

import requests
from geopy.geocoders import Nominatim
import pycountry
from core.logger import get_logger

logger = get_logger(__name__)

DATA360_BASE = "https://data360api.worldbank.org"
THINK_DB_ID = "WB_THINK_HAZARD"

# Official ThinkHazard indicators from Data360
THINKHAZARD_INDICATORS = {
    "WB_THINK_HAZARD_DG_LEVEL": "Drought",
    "WB_THINK_HAZARD_CF_LEVEL": "Coastal flood",
    "WB_THINK_HAZARD_EH_LEVEL": "Extreme heat",
    "WB_THINK_HAZARD_UF_LEVEL": "Urban flood",
    "WB_THINK_HAZARD_FL_LEVEL": "River flood",
    "WB_THINK_HAZARD_WF_LEVEL": "Wildfire",
    "WB_THINK_HAZARD_EQ_LEVEL": "Earthquake",
    "WB_THINK_HAZARD_LS_LEVEL": "Landslide",
    "WB_THINK_HAZARD_TS_LEVEL": "Tsunami",
    "WB_THINK_HAZARD_CY_LEVEL": "Cyclone / Storm",
    "WB_THINK_HAZARD_VA_LEVEL": "Volcanic activity",
}


def rank_to_level(rank: float) -> str:
    """Convert numeric score (1-4) to risk level"""
    if rank >= 4:
        return "High"
    elif rank >= 3:
        return "Medium"
    elif rank >= 2:
        return "Low"
    return "Low"


def city_to_country_code(city: str) -> str | None:
    """Convert city name to ISO3 country code"""
    try:
        geolocator = Nominatim(user_agent="hazard_app")
        loc = geolocator.geocode(city)
        if not loc:
            return None

        country_name = loc.address.split(",")[-1].strip()

        # Convert name to ISO3
        try:
            return pycountry.countries.get(name=country_name).alpha_3
        except Exception:
            return pycountry.countries.search_fuzzy(country_name)[0].alpha_3

    except Exception as e:
        logger.warning(f"Could not find ISO3 code for country '{country_name}': {e}")
        return None


def normalize_location_to_iso3(location: str) -> str | None:
    """
    Convert location input (city, country, or ISO2/ISO3) to ISO3 code
    """
    loc = location.strip()

    # Direct ISO3
    if len(loc) == 3 and loc.isalpha():
        return loc.upper()

    # Try as city
    iso_from_city = city_to_country_code(loc)
    if iso_from_city:
        return iso_from_city

    # Try as country name
    try:
        return pycountry.countries.search_fuzzy(loc)[0].alpha_3
    except Exception:
        return None


def get_latest_value(indicator_id: str, country_code: str) -> float | None:
    """Get latest ThinkHazard indicator value for a country"""
    url = f"{DATA360_BASE}/data360/data"

    params = {
        "DATABASE_ID": THINK_DB_ID,
        "INDICATOR": indicator_id,
        "REF_AREA": country_code,
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return None

        data = r.json()
        rows = data.get("value", [])
        if not rows:
            return None

        # Get latest year available
        rows.sort(key=lambda x: int(x.get("TIME_PERIOD", 0)))
        latest = rows[-1]

        val = latest.get("OBS_VALUE")
        if val is None:
            return None

        return float(val)

    except Exception:
        return None


def get_hazards_for_country(country_code: str):
    """Get all hazards for a country ISO3 code"""
    results = []

    for indicator_id, hazard_name in THINKHAZARD_INDICATORS.items():
        score = get_latest_value(indicator_id, country_code)
        if score is None:
            continue

        level = rank_to_level(score)

        results.append({"hazard": hazard_name, "level": level, "score": score})

    return results


def count_hazards(country_code: str) -> int:
    """Count significant hazards for a country"""
    hazards = get_hazards_for_country(country_code)
    return sum(1 for h in hazards if h["score"] >= 2)


def get_hazards(location: str):
    """Get hazards for a location (city or country name)"""
    iso3 = normalize_location_to_iso3(location)
    if not iso3:
        return None
    return get_hazards_for_country(iso3)


def count_hazards_for(location: str):
    """Count hazards for a location"""
    iso3 = normalize_location_to_iso3(location)
    if not iso3:
        return 0
    return count_hazards(iso3)
