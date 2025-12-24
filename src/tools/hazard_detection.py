# think_hazard.py
import re
from geopy.geocoders import Nominatim
from langchain.tools import tool
from data360_hazards import (
    get_hazards,
    normalize_location_to_iso3
)


# ----------------------------------------------------------
# 1. RNG déterministe (pour tests PyTest)
# ----------------------------------------------------------

def _get_deterministic_rng(seed_str: str):
    import random
    seed = sum(ord(c) for c in seed_str)
    return random.Random(seed)


# ----------------------------------------------------------
# EXTRA : extraction propre du nombre
# ----------------------------------------------------------

def extract_n(query: str) -> int:
    """
    Détecte :
    - top 4
    - top     7
    - 4 hazards
    - 3 risks
    - Tunisia | 5
    - Paris, 3
    Sinon : 5 par défaut
    """
    # top 4
    m = re.search(r"top\s+(\d+)", query, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # 4 hazards
    m = re.search(r"(\d+)\s+(hazards|risks)", query, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # fallback nombre simple
    m = re.search(r"\b(\d+)\b", query)
    if m:
        return int(m.group(1))

    return 5


# ----------------------------------------------------------
# 2. Résolution d’adresse (ville, pays ou coordonnées)
# ----------------------------------------------------------

def resolve_location(query: str):
    geo = Nominatim(user_agent="hazard_app")

    # Coordonnées ?
    if re.match(r"^\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*$", query):
        lat, lon = map(float, query.split(","))
        try:
            loc = geo.reverse((lat, lon), language="en")
            return loc.address if loc else "Unknown location"
        except:
            return "Unknown location"

    # Ville ou pays
    try:
        loc = geo.geocode(query, language="en")
        return loc.address if loc else "Unknown location"
    except:
        return "Unknown location"

def get_iso3_from_country_name(name):
    try:
        country = pycountry.countries.lookup(name)
        return country.alpha_3
    except LookupError:
        return None

# ----------------------------------------------------------
# 3. Extraction des hazards Data360
# ----------------------------------------------------------

def get_top_hazards_for_country(country: str, n: int = 5):
    iso3 = normalize_location_to_iso3(country)
    if not iso3:
        return []

    hazards = get_hazards(iso3)
    if not hazards:
        return []

    # Trier les hazards par score décroissant
    hazards_sorted = sorted(hazards, key=lambda h: h["score"], reverse=True)
    return hazards_sorted[:n]


# ----------------------------------------------------------
# 4. TOOL LangChain : think_hazard
# ----------------------------------------------------------

@tool("think_hazard")
def think_hazard(query: str):
    """
    Exemples :
    - "Paris"
    - "Paris | 5"
    - "Paris, 3"
    - "What are the top 4 risks in Canada?"
    - "Tokyo | 7"
    """

    # --------------------------
    # 1) Extraire N proprement
    # --------------------------
    n = extract_n(query)

    # Nettoyer le query pour isoler le nom du lieu
    query_clean = re.sub(r"\b\d+\b", "", query)
    query_clean = query_clean.replace("|", "").replace(",", "").strip()

    # --------------------------
    # 2) Résoudre l'adresse
    # --------------------------
    resolved = resolve_location(query_clean)
    if resolved == "Unknown location":
        return "Unknown location"

    parts = resolved.split(",")
    clean_address = ", ".join([p.strip() for p in parts[:3]])
    country = parts[-1].strip()

    # --------------------------
    # 3) Obtenir les hazards
    # --------------------------
    hazards = get_top_hazards_for_country(country, n=n)
    if not hazards:
        return f"No hazards found for this location ({clean_address})."

    # --------------------------
    # 4) Nouveau format d’affichage
    # --------------------------
    output = [
        f"🌍 **Location:** {clean_address}",
        f"🔢 **Top {n} hazards:**"
    ]

    for i, h in enumerate(hazards, start=1):
        output.append(f"{i}. **{h['hazard']}** — {h['level']}")

    return "\n".join(output)


# ----------------------------------------------------------
# Tests manuels
# ----------------------------------------------------------

if __name__ == "__main__":
    print(think_hazard.run("Paris"))
    print()
    print(think_hazard.run("Paris | 3"))
    print()
    print(think_hazard.run("48.8566, 2.3522"))
    print()
    print(think_hazard.run("What are the top 4 risks in Canada?"))
    print()
    print(think_hazard.run("Tokyo | 7"))
