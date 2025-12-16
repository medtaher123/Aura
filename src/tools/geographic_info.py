#geographic_info.py
import requests
from langchain.tools import tool

# --- Country Info ---
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
        "Currency": ", ".join([v.get("name") for v in data.get("currencies", {}).values()]),
        "Flag": data.get("flags", {}).get("png")
    }
    return info

# --- City Info (Nominatim + Wikidata) ---
def get_city_info(city_name: str):
    """Return main information about a city via Nominatim + Wikidata (population)."""
    url = f"https://nominatim.openstreetmap.org/search?city={city_name}&format=json&addressdetails=1&limit=1&extratags=1"
    headers = {"User-Agent": "GeoApp/1.0"}  # requis par Nominatim
    response = requests.get(url, headers=headers)
    if response.status_code != 200 or not response.json():
        return None
    data = response.json()[0]
    address = data.get("address", {})

    # population via Nominatim si dispo
    population = data.get("extratags", {}).get("population")

    # si pas trouvé → essayer Wikidata
    if not population:
        wikidata_id = data.get("extratags", {}).get("wikidata")
        if wikidata_id:
            wikidata_url = f"https://www.wikidata.org/wiki/Special:EntityData/{wikidata_id}.json"
            r = requests.get(wikidata_url)
            if r.status_code == 200:
                wd = r.json()
                entity = wd.get("entities", {}).get(wikidata_id, {})
                claims = entity.get("claims", {})
                pop_claims = claims.get("P1082")  # P1082 = population
                if pop_claims:
                    population = pop_claims[0].get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("amount")
                    if population:
                        population = int(population.replace("+", ""))

    info = {
        "Type": "City",
        "Name": data.get("display_name"),
        "Country": address.get("country"),
        "Region": address.get("state"),
        "Latitude": data.get("lat"),
        "Longitude": data.get("lon"),
        "Population": population if population else "Unknown"
    }
    return info


# --- TOOL LangChain ---
@tool
def geo_info_tool(name: str) -> str:
    """
    Retrieve geographic information about a country or a city.

    Parameters
    ----------
    name : str
        The name of the location (either a country or a city).
        Example: "France", "Tokyo", "Casablanca"

    Returns
    -------
    str
        A summary of the main information found (country or city).
    """
    # Try country
    info = get_country_info(name)

    # If not found => Try city
    if not info:
        info = get_city_info(name)

    if not info:
        return f"Final Answer: No results found for '{name}'."

    # Formater en texte lisible
    summary = "\n".join([f"{k} : {v}" for k, v in info.items()])
    return f"Final Answer:\n{summary}"
