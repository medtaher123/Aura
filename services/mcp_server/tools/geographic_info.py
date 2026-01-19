"""
Geographic Info Tool for MCP Server

Retrieves information about countries and cities.
"""

import requests

from utils.bbox_service import get_city_candidates
from utils.contracts import make_tool_response
from mcp_singleton import mcp


def get_country_info(country_name: str):
    """Return main information about a country via the restcountries.com API."""
    url = f"https://restcountries.com/v3.1/name/{country_name}"
    response = requests.get(url)
    if response.status_code != 200:
        return None
    data = response.json()[0]
    info = {
        "Type": "Country",
        "Name": data.get("name", {}).get("common"),
        "Capital": data.get("capital", ["Unknown"])[0],
        "Population": data.get("population"),
        "Area (km²)": data.get("area"),
        "Region": data.get("region"),
        "Subregion": data.get("subregion"),
        "Languages": list(data.get("languages", {}).values()),
        "Currency": ", ".join(
            [v.get("name") for v in data.get("currencies", {}).values()]
        ),
        "Flag": data.get("flags", {}).get("png"),
    }
    return info


def get_city_info(city_name: str):
    """Return main information about a city via Nominatim + Wikidata."""
    url = f"https://nominatim.openstreetmap.org/search?city={city_name}&format=json&addressdetails=1&limit=1&extratags=1"
    headers = {"User-Agent": "GeoApp/1.0"}
    response = requests.get(url, headers=headers)
    if response.status_code != 200 or not response.json():
        return None
    data = response.json()[0]
    address = data.get("address", {})

    population = data.get("extratags", {}).get("population")
    if not population:
        wikidata_id = data.get("extratags", {}).get("wikidata")
        if wikidata_id:
            wikidata_url = (
                f"https://www.wikidata.org/wiki/Special:EntityData/{wikidata_id}.json"
            )
            r = requests.get(wikidata_url)
            if r.status_code == 200:
                wd = r.json()
                entity = wd.get("entities", {}).get(wikidata_id, {})
                claims = entity.get("claims", {})
                pop_claims = claims.get("P1082")
                if pop_claims:
                    population = (
                        pop_claims[0]
                        .get("mainsnak", {})
                        .get("datavalue", {})
                        .get("value", {})
                        .get("amount")
                    )
                    if population:
                        population = int(population.replace("+", ""))

    info = {
        "Type": "City",
        "Name": data.get("display_name"),
        "Country": address.get("country"),
        "Region": address.get("state"),
        "Latitude": data.get("lat"),
        "Longitude": data.get("lon"),
        "Population": population if population else "Unknown",
    }
    return info


@mcp.tool()
def geo_info_tool(name: str) -> dict:
    """Retrieve geographic information about a country or a city.

    Args:
        name: The name of the location (country or city)
    """
    location_name = name

    # Try country first
    info = get_country_info(location_name)

    # If not found, try city
    if not info:
        candidates = get_city_candidates(location_name)
        if len(candidates) > 1:
            return make_tool_response(
                tool_name="geo_info_tool",
                message=f"I found multiple matches for '{location_name}'. Please confirm the correct location.",
                city=location_name,
                data={
                    "needs_location_confirmation": True,
                    "location_query": location_name,
                    "candidates": candidates,
                    "resume_patch": {"field": "name"},
                },
                error=True,
            )

        if candidates:
            info = get_city_info(candidates[0].get("display_name") or location_name)
        else:
            info = get_city_info(location_name)

    if not info:
        return make_tool_response(
            tool_name="geo_info_tool",
            message=f"No results found for '{location_name}'.",
            city=location_name,
            error=True,
        )

    # Format as readable text
    summary = "\n".join([f"{k} : {v}" for k, v in info.items()])

    # Best-effort structured fields
    country = None
    city = None
    coordinates = None
    info_type = str(info.get("Type") or "").lower()
    if info_type == "country":
        country = info.get("Name")
    elif info_type == "city":
        city = location_name
        country = info.get("Country")
        try:
            lat = info.get("Latitude")
            lon = info.get("Longitude")
            if lat is not None and lon is not None:
                coordinates = {"lat": float(lat), "lon": float(lon)}
        except Exception:
            coordinates = None

    return make_tool_response(
        tool_name="geo_info_tool",
        message=summary,
        country=country,
        city=city,
        coordinates=coordinates,
        data={"info": info},
        error=False,
    )
