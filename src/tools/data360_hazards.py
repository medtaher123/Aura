# data360_hazards.py
import requests
from geopy.geocoders import Nominatim
import pycountry

DATA360_BASE = "https://data360api.worldbank.org"
THINK_DB_ID = "WB_THINK_HAZARD"

# Liste officielle d’indicateurs ThinkHazard provenant de Data360
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
    "WB_THINK_HAZARD_VA_LEVEL": "Volcanic activity"
}


# ----------------------------------------------------------
# 1. Convertir le score (1–4) en "Low/Medium/High"
# ----------------------------------------------------------

def rank_to_level(rank: float) -> str:
    if rank >= 4:
        return "High"
    elif rank >= 3:
        return "Medium"
    elif rank >= 2:
        return "Low"
    return "Low"


# ----------------------------------------------------------
# 2. Ville → Pays ISO3
# ----------------------------------------------------------

def city_to_country_code(city: str) -> str | None:
    try:
        geolocator = Nominatim(user_agent="hazard_app")
        loc = geolocator.geocode(city)
        if not loc:
            return None

        country_name = loc.address.split(",")[-1].strip()

        # Conversion nom → ISO3
        try:
            return pycountry.countries.get(name=country_name).alpha_3
        except:
            return pycountry.countries.search_fuzzy(country_name)[0].alpha_3

    except Exception:
        return None


def normalize_location_to_iso3(location: str) -> str | None:
    """
    Convertit un input (ville, pays ou ISO2/ISO3) → code ISO3
    """
    loc = location.strip()

    # direct ISO3
    if len(loc) == 3 and loc.isalpha():
        return loc.upper()

    # si c'est une ville
    iso_from_city = city_to_country_code(loc)
    if iso_from_city:
        return iso_from_city

    # si c'est un pays en toutes lettres
    try:
        return pycountry.countries.search_fuzzy(loc)[0].alpha_3
    except:
        return None


# ----------------------------------------------------------
# 3. Récupérer un indicateur ThinkHazard pour un pays
# ----------------------------------------------------------

def get_latest_value(indicator_id: str, country_code: str) -> float | None:
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

        # Prendre la dernière année disponible
        rows.sort(key=lambda x: int(x.get("TIME_PERIOD", 0)))
        latest = rows[-1]

        val = latest.get("OBS_VALUE")
        if val is None:
            return None

        return float(val)

    except Exception:
        return None


# ----------------------------------------------------------
# 4. Récupérer tous les hazards pour un pays ISO3
# ----------------------------------------------------------

def get_hazards_for_country(country_code: str):
    results = []

    for indicator_id, hazard_name in THINKHAZARD_INDICATORS.items():
        score = get_latest_value(indicator_id, country_code)
        if score is None:
            continue

        level = rank_to_level(score)

        results.append({
            "hazard": hazard_name,
            "level": level,
            "score": score
        })

    return results


def count_hazards(country_code: str) -> int:
    hazards = get_hazards_for_country(country_code)
    return sum(1 for h in hazards if h["score"] >= 2)


# ----------------------------------------------------------
# 5. Fonction principale : à partir d'un input utilisateur
# ----------------------------------------------------------

def get_hazards(location: str):
    iso3 = normalize_location_to_iso3(location)
    if not iso3:
        return None
    return get_hazards_for_country(iso3)


def count_hazards_for(location: str):
    iso3 = normalize_location_to_iso3(location)
    if not iso3:
        return 0
    return count_hazards(iso3)


# ----------------------------------------------------------
# 6. Test manuel
# ----------------------------------------------------------

if __name__ == "__main__":
    print("=== Test: Paris ===")
    hazards = get_hazards("Paris")
    for h in hazards:
        print(f"{h['hazard']}: {h['level']} (score={h['score']})")

    print("\nTotal:", count_hazards_for("Paris"))

    print("\n=== Test: Tokyo ===")
    hazards = get_hazards("Tokyo")
    for h in hazards:
        print(f"{h['hazard']}: {h['level']} (score={h['score']})")

    print("\nTotal:", count_hazards_for("Tokyo"))