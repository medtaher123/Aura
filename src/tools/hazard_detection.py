"""Hazard tool.

This tool mirrors the structure of other tools in this repo:
- Query hazard data (Data360 hazards via `data360_hazards`).
- Return a standardized `make_tool_response` dict.
"""

from langchain.tools import tool

from src.services.bbox_service import get_city_bbox

from .contracts import make_tool_response
from .data360_hazards import get_hazards, normalize_location_to_iso3



# ----------------------------------------------------------
# 3. Extraction des hazards Data360
# ----------------------------------------------------------

def get_top_hazards_for_country(country: str, n: int = 5):
    if normalize_location_to_iso3 is None or get_hazards is None:
        return []

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
# 4. TOOL LangChain : query_hazards_tool
# ----------------------------------------------------------

@tool("query_hazards_tool", return_direct=True)
def query_hazards_tool(country: str, top_n: int = 5, location: str | None = None) -> dict:
    """
    Returns the top hazards for a country based on Data360 hazards.

    Args:
        country: Country name (e.g., "Japan", "France").
        top_n: Number of hazards to return.
        location: Optional location string used only to provide best-effort coordinates for UI context.
    """

    if normalize_location_to_iso3 is None or get_hazards is None:
        return make_tool_response(
            tool_name="query_hazards_tool",
            message=(
                "Hazards feature is not available because the optional dependency "
                "'data360_hazards' is not installed.\n\n"
                "To enable it, install the package in the same environment you run Streamlit from, e.g.:\n"
                "- `pip install data360_hazards` (if published), or\n"
                "- `pip install -e /path/to/data360_hazards` (if it\'s a local module).\n\n"
                "You can still use the rest of the chatbot without this tool."
            ),
            data={"missing_dependency": "data360_hazards"},
            error=True,
        )

    if not isinstance(country, str) or not country.strip():
        return make_tool_response(
            tool_name="query_hazards_tool",
            message="Please specify a country (or a location that implies a country) in your query.",
            city=location,
            country=country,
            error=True,
        )
    country = country.strip()
    try:
        n = int(top_n)
    except Exception:
        n = 5
    if n <= 0:
        n = 5

    # Best-effort coordinates for UI context
    coords = None
    bbox, lat, lon, city_name_final = get_city_bbox((location or country))
    try:
        if lat is not None and lon is not None:
            coords = {"lat": float(lat), "lon": float(lon)}
    except Exception:
        coords = None

    clean_address = city_name_final or (location or country)

    # --------------------------
    # 3) Obtenir les hazards
    # --------------------------
    hazards = get_top_hazards_for_country(country, n=n)
    if not hazards:
        return make_tool_response(
            tool_name="query_hazards_tool",
            message=f"No hazards found for this location ({clean_address}).",
            city=location or clean_address,
            country=country,
            coordinates=coords,
            data={"top_n": n, "hazards": []},
            error=False,
        )

    # --------------------------
    # 4) Nouveau format d’affichage
    # --------------------------
    output = [
        f"🌍 **Location:** {clean_address}",
        f"🔢 **Top {n} hazards:**"
    ]

    for i, h in enumerate(hazards, start=1):
        output.append(f"{i}. **{h['hazard']}** — {h['level']}")

    return make_tool_response(
        tool_name="query_hazards_tool",
        message="\n".join(output),
        city=location or clean_address,
        country=country,
        coordinates=coords,
        data={"top_n": n, "hazards": hazards},
        error=False,
    )
