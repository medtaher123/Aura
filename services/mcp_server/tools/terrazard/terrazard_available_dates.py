from datetime import datetime
from core.logger import get_logger
from tools.terrazard.utils import execute_read_query
from utils.bbox_service import LocationAmbiguousError, get_city_bbox, reverse_geocode
from utils.map_view_service import view_state_from_bbox
from mcp_singleton import mcp
from utils.contracts import ToolArtifacts, ToolCoordinates, ToolResponse

logger = get_logger(__name__)

class TerrazardDataError(RuntimeError):
    pass

def _build_date_range_query() -> str:
    return """
        SELECT observation_date, COUNT(*) as polygon_count
        FROM hazard_masks
        WHERE observation_date >= :start_date 
          AND observation_date <= :end_date
          AND ST_Intersects(
              geometry, 
              ST_Transform(ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326), ST_SRID(geometry))
          )
        GROUP BY observation_date
        ORDER BY observation_date ASC;
    """


def _resolve_from_lat_lon(lat: float, lon: float) -> tuple[ToolCoordinates, list[float], str]:
    """Gère la géolocalisation inversée à partir de coordonnées brutes."""
    lat_f, lon_f = float(lat), float(lon)
    coords = ToolCoordinates(lat=lat_f, lon=lon_f)
    
    try:
        rev = reverse_geocode(lat_f, lon_f)
        resolved_name = rev.get("city") or rev.get("country") or f"{lat_f:.4f}, {lon_f:.4f}"
    except Exception as e:
        logger.error(f"Error reverse geocoding: {e}")
        resolved_name = f"{lat_f:.4f}, {lon_f:.4f}"
        
    # Bounding box par défaut autour du point
    bbox_norm = [lat_f - 0.25, lat_f + 0.25, lon_f - 0.25, lon_f + 0.25]
    return coords, bbox_norm, resolved_name


def _resolve_from_location(location: str) -> tuple[ToolCoordinates, list[float], str]:
    """Gère l'extraction de Bbox à partir du nom d'une ville."""
    bbox, lat_city, lon_city, city_name_final = get_city_bbox(
        location, require_confirmation=True
    )
    
    if lat_city is None or lon_city is None:
        raise TerrazardDataError(f"Could not geocode location '{location}'.")

    coords = ToolCoordinates(lat=float(lat_city), lon=float(lon_city))
    resolved_name = city_name_final or location

    if not isinstance(bbox, list) or len(bbox) != 4:
        raise TerrazardDataError("Valid bounding box could not be extracted.")
        
    south, north, west, east = (float(x) for x in bbox)
    bbox_norm = [min(south, north), max(south, north), min(west, east), max(west, east)]
    
    return coords, bbox_norm, resolved_name



def _fetch_terrazard_date_counts(bbox: list[float], start_date: str, end_date: str) -> list[dict]:
    """Exécute la requête PostGIS et formate les résultats."""
    query = _build_date_range_query() # Ta requête SQL d'origine
    params = {
        "start_date": start_date, "end_date": end_date,
        "min_lon": bbox[2], "min_lat": bbox[0],
        "max_lon": bbox[3], "max_lat": bbox[1],
    }
    
    raw_rows = execute_read_query(query, params)
    return [
        {
            "date": row["observation_date"],
            "polygon_count": row["polygon_count"],
            "status": "Data available" if row["polygon_count"] > 0 else "No data"
        }
        for row in raw_rows
    ]


def _build_terrazard_map_artifact(coords: ToolCoordinates, bbox: list[float], name: str) -> ToolArtifacts:
    """Génère l'artefact visuel (la carte) pour l'interface de chat."""
    view_state = view_state_from_bbox(coords, padding=0.18, min_zoom=5.0, max_zoom=10.5)
    
    if not view_state:
        return ToolArtifacts()
        
    return ToolArtifacts(maps=[{
        "title": f"Terrazar Observations Area: {name}",
        "view_state": view_state,
    }])



def _validate_dates(start_date: str | None, end_date: str | None) -> None:
    """Vérifie la validité des paramètres de date."""
    if not start_date or not end_date:
        raise TerrazardDataError("Please specify both a start_date and an end_date (YYYYMMDD).")

def _resolve_spatial_context(
    location: str | None, lat: float | None, lon: float | None
) -> tuple[ToolCoordinates, list[float], str]:
    """Aiguille vers la bonne méthode de résolution géographique selon les paramètres fournis."""
    if lat is not None and lon is not None:
        return _resolve_from_lat_lon(lat, lon)
    if location:
        return _resolve_from_location(location)
    raise TerrazardDataError("Please specify a location or lat/lon coordinates.")


def _build_success_response(
    start_date: str, 
    end_date: str,
    coords: ToolCoordinates, 
    bbox: list[float], 
    name: str,
    available_days: list[dict]
) -> ToolResponse:
    """Assemble l'objet de réponse finale en cas de succès de la recherche."""
    message = f"Found {len(available_days)} observation date(s) for {name} between {start_date} and {end_date}."
    
    return ToolResponse(
        tool_name="get_terrazard_available_dates_tool",
        message=message,
        artifacts=_build_terrazard_map_artifact(coords, bbox, name),
        start_date=start_date,
        end_date=end_date,
        city=name,
        coordinates=coords,
        data={"available_days": available_days, "bbox": bbox},
        error=False,
    )

def _handle_tool_error(
    e: Exception, 
    location: str | None, 
    start_date: str, 
    end_date: str
) -> ToolResponse:
    """Mappe les exceptions capturées vers les bons formats de ToolResponse."""
    if isinstance(e, LocationAmbiguousError):
        return ToolResponse(
            tool_name="get_terrazard_available_dates_tool",
            message=f"I found multiple matches for '{e.query}'. Please confirm the correct location.",
            city=location,
            start_date=start_date,
            end_date=end_date,
            data={
                "needs_location_confirmation": True,
                "location_query": e.query,
                "candidates": e.candidates,
                "resume_patch": {"field": "location"},
            },
            error=False,
        )
    
    if isinstance(e, TerrazardDataError):
        return ToolResponse(
            tool_name="get_terrazard_available_dates_tool", 
            message=str(e), 
            error=True
        )
        
    logger.error(f"Unexpected error in Terrazar dates tool: {e}")
    return ToolResponse(
        tool_name="get_terrazard_available_dates_tool",
        message=f"Internal error accessing Terrazar data: {str(e)}",
        error=True,
    )


@mcp.tool()
def get_terrazard_available_dates_tool(
    start_date: str,
    end_date: str,
    location: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> ToolResponse:
    """
    Tool to retrieve available satellite observation dates and water polygon counts 
    for a specific location and date range in the Terrazar system.
    """
    try:
        _validate_dates(start_date, end_date)
        
        coords, bbox_norm, resolved_name = _resolve_spatial_context(location, lat, lon)
        
        available_days = _fetch_terrazard_date_counts(bbox_norm, start_date, end_date)
        
        return _build_success_response(
            start_date, end_date, coords, bbox_norm, resolved_name, available_days
        )

    except Exception as e:
        return _handle_tool_error(e, location, start_date, end_date)
