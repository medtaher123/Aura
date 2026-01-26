"""
Hazard Detection Tool for MCP

Uses Data360 hazards data and bbox_service.
"""

from utils.bbox_service import LocationAmbiguousError, get_city_bbox
from utils.data360_hazards import get_hazards, normalize_location_to_iso3
from utils.contracts import make_tool_response
from core.logger import get_logger
from mcp_singleton import mcp

logger = get_logger(__name__)


def get_top_hazards_for_country(country: str, n: int = 5):
    """Get top N hazards for a country"""
    if normalize_location_to_iso3 is None or get_hazards is None:
        return []

    iso3 = normalize_location_to_iso3(country)
    if not iso3:
        return []

    hazards = get_hazards(iso3)
    if not hazards:
        return []

    # Sort hazards by score descending
    hazards_sorted = sorted(hazards, key=lambda h: h["score"], reverse=True)
    return hazards_sorted[:n]


@mcp.tool()
def query_hazards_tool(
    country: str, top_n: int = 5, location: str | None = None
) -> dict:
    """
    Returns the top hazards for a country based on Data360 hazards.

    Args:
        country: Country name (e.g., "Japan", "France").
        top_n: Number of hazards to return.
        location: Optional location string used only to provide best-effort coordinates for UI context.
    """
    if not isinstance(country, str) or not country.strip():
        logger.error("Country parameter is missing or invalid.")
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
    location_query = location or country
    patch_field = (
        "location" if isinstance(location, str) and location.strip() else "country"
    )

    try:
        bbox, lat, lon, city_name_final = get_city_bbox(
            location_query, require_confirmation=True
        )
    except LocationAmbiguousError as e:
        logger.error(f"LocationAmbiguousError for query '{e.query}': {e.candidates}")
        return make_tool_response(
            tool_name="query_hazards_tool",
            message=f"I found multiple matches for '{e.query}'. Please confirm the correct location.",
            city=location_query,
            country=country,
            data={
                "needs_location_confirmation": True,
                "location_query": e.query,
                "candidates": e.candidates,
                "resume_patch": {"field": patch_field},
            },
            error=False,
        )

    try:
        if lat is not None and lon is not None:
            coords = {"lat": float(lat), "lon": float(lon)}
    except Exception:
        coords = None

    clean_address = city_name_final or (location or country)

    # Get hazards
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

    # Format output
    output = [f"🌍 **Location:** {clean_address}", f"🔢 **Top {n} hazards:**"]

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
