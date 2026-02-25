"""
Flood Damage City Tool for MCP

Estimates total flood damage for a city by:
1. Getting flood damage per m² from the global depth-damage dataset (by country/year/depth)
2. Querying Daylight OSM for building areas within the city polygon
3. Mapping OSM building types to asset classes and summing: area × cost per m²
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from config import get_config
from core.logger import get_logger
from mcp_singleton import mcp
from utils.contracts import ToolResponse

from tools.flood_depth_damage import (
    GLOBAL_MULTIPLIER,
    _as_float,
    _interpolate_damage,
    _load_dataset,
    _normalize_asset_class,
    _normalize_continent,
    _normalize_country,
    _normalize_text,
    _resolve_country_name,
    _resolve_year,
)

logger = get_logger(__name__)

# Daylight OSM is in us-west-2
DAYLIGHT_REGION = "us-west-2"
DAYLIGHT_RELEASE = os.environ.get("DAYLIGHT_RELEASE", "v1.58")

# Map OSM building=* values to flood asset classes (residential, commercial, industrial)
OSM_BUILDING_TO_ASSET: Dict[str, str] = {
    "residential": "residential",
    "house": "residential",
    "apartments": "residential",
    "apartment": "residential",
    "detached": "residential",
    "semidetached_house": "residential",
    "terrace": "residential",
    "dormitory": "residential",
    "bungalow": "residential",
    "cabin": "residential",
    "hotel": "residential",  # accommodation
    "commercial": "commercial",
    "retail": "commercial",
    "office": "commercial",
    "kiosk": "commercial",
    "supermarket": "commercial",
    "mall": "commercial",
    "school": "commercial",
    "university": "commercial",
    "college": "commercial",
    "hospital": "commercial",
    "kindergarten": "commercial",
    "industrial": "industrial",
    "warehouse": "industrial",
    "factory": "industrial",
    "manufacture": "industrial",
    "silo": "industrial",
    "agricultural": "industrial",
}

# Map semantic categories from osm_infra_categories.json to flood asset classes
_CATEGORY_TO_FLOOD_ASSET: Dict[str, str] = {
    "residential": "residential",
    "industrial": "industrial",
    "commercial": "commercial",
    "shop": "commercial",
    "office": "commercial",
    "healthcare": "commercial",
    "education": "commercial",
    "emergency": "commercial",
    "transport": "commercial",
    "leisure": "commercial",
    "tourism": "commercial",
    "government": "commercial",
    "religion": "commercial",
    "critical_infrastructure": "industrial",
}


def _load_osm_infra_categories() -> Dict[str, Any]:
    """Load osm_infra_categories.json from utils. Returns semantic_categories and infra_tag_keys."""
    utils_dir = Path(__file__).resolve().parent.parent / "utils"
    path = utils_dir / "osm_infra_categories.json"
    if not path.is_file():
        return {"semantic_categories": {}, "infra_tag_keys": ["building", "amenity", "landuse", "industrial"]}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {
            "semantic_categories": data.get("semantic_categories", {}),
            "infra_tag_keys": data.get("infra_tag_keys", ["building", "amenity", "landuse", "industrial"]),
        }
    except Exception as e:
        logger.warning("Could not load osm_infra_categories.json: %s", e)
        return {"semantic_categories": {}, "infra_tag_keys": ["building", "amenity", "landuse", "industrial"]}


def _build_tag_to_asset_case_parts(filter_asset: Optional[str]) -> List[str]:
    """
    Build ordered WHEN clauses for Athena CASE: (tag_key, value) -> asset.
    Priority: building (explicit values), then amenity, shop, office, tourism, landuse, industrial.
    Uses OSM_BUILDING_TO_ASSET first, then osm_infra_categories semantic_categories.
    """
    whens: List[str] = []
    infra = _load_osm_infra_categories()
    semantic = infra.get("semantic_categories", {})

    def add_when(asset: str, tag_key: str, values: Optional[List[str]], any_ok: bool = False) -> None:
        if filter_asset and asset != filter_asset:
            return
        # Athena: tags['key'] for map access
        key_sql = f"tags['{tag_key}']"
        if values:
            for v in values:
                v_safe = (v or "").replace("'", "''").lower()
                if not v_safe:
                    continue
                whens.append(
                    f"WHEN LOWER(TRIM(COALESCE({key_sql}, ''))) = '{v_safe}' THEN '{asset}'"
                )
        elif any_ok:
            whens.append(
                f"WHEN {key_sql} IS NOT NULL AND LOWER(TRIM(COALESCE({key_sql}, ''))) <> '' THEN '{asset}'"
            )

    # 1) building=* (explicit map)
    for osm_val, asset in OSM_BUILDING_TO_ASSET.items():
        if filter_asset and asset != filter_asset:
            continue
        osm_safe = osm_val.replace("'", "''")
        whens.append(
            f"WHEN LOWER(TRIM(COALESCE(tags['building'], 'yes'))) = '{osm_safe}' THEN '{asset}'"
        )

    # 2) amenity, shop, office, tourism, landuse, industrial from semantic_categories
    MAX_VALUES_PER_TAG = 50  # above this, use single "any value" WHEN to keep query size bounded
    for cat_name, tag_to_values in semantic.items():
        flood_asset = _CATEGORY_TO_FLOOD_ASSET.get(cat_name)
        if not flood_asset:
            continue
        for tag_key, values in tag_to_values.items():
            if tag_key == "building":
                continue  # already covered
            val_list = values if isinstance(values, list) else None
            any_ok = val_list is not None and len(val_list) == 0
            if val_list and len(val_list) > MAX_VALUES_PER_TAG:
                any_ok = True
                val_list = None
            add_when(flood_asset, tag_key, val_list if (val_list and len(val_list) > 0) else None, any_ok=any_ok)

    # 3) landuse=residential (often no building tag)
    add_when("residential", "landuse", ["residential"])

    return whens


def _geojson_polygon_to_wkt(geojson: Any) -> Optional[str]:
    """Convert GeoJSON polygon/multipolygon to WKT for Athena ST_GEOMETRYFROMTEXT."""
    if not geojson or not isinstance(geojson, dict):
        return None
    gtype = geojson.get("type")
    coords = geojson.get("coordinates")
    if not coords:
        return None

    def ring_to_wkt(ring: List) -> str:
        parts = []
        for pt in ring:
            if len(pt) >= 2:
                parts.append(f"{pt[0]} {pt[1]}")
        return "(" + ", ".join(parts) + ")"

    if gtype == "Polygon":
        outer = coords[0] if coords else []
        return f"POLYGON({ring_to_wkt(outer)})"
    if gtype == "MultiPolygon":
        poly_parts = []
        for poly in coords:
            if poly and len(poly) > 0:
                poly_parts.append("(" + ring_to_wkt(poly[0]) + ")")
        if not poly_parts:
            return None
        return "MULTIPOLYGON(" + ", ".join(poly_parts) + ")"
    return None


def _get_city_polygon_and_country(city_name: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Fetch city polygon (WKT) and country from Nominatim.
    Returns (polygon_wkt, country_name, display_name).
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": city_name, "format": "json", "limit": 1, "polygon_geojson": 1}
    try:
        resp = requests.get(url, params=params, headers={"User-Agent": "FloodDamageCityTool"}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not data or not isinstance(data, list) or not data[0]:
            return None, None, None
        item = data[0]
        geojson = item.get("geojson")
        address = item.get("address", {}) if isinstance(item.get("address"), dict) else {}
        country = address.get("country") or item.get("display_name", "").split(",")[-1].strip()
        display = item.get("display_name", city_name)
        wkt = _geojson_polygon_to_wkt(geojson)
        return wkt, country, display
    except Exception as e:
        logger.warning("Nominatim geocode failed for %s: %s", city_name, e)
        return None, None, None




def _get_damage_per_m2(
    country: str,
    asset_class: str,
    depth_m: float,
    year: int,
    continent: Optional[str],
    basis: str,
) -> Optional[float]:
    """Return estimated flood damage per m² (EUR) for given params, or None if not found."""
    dataset = _load_dataset()
    curves = dataset["curves"]
    iso_map = dataset["iso_map"]
    max_damage = dataset["max_damage"]

    curve_set = curves.get(asset_class, {})
    if not curve_set:
        return None
    cont = _normalize_continent(continent) if continent else "global"
    curve = curve_set.get(cont) or curve_set.get("global")
    if not curve:
        return None

    try:
        frac = _interpolate_damage(depth_m, curve)
    except Exception:
        return None

    resolved = _resolve_country_name(country, iso_map) or country
    max_table = max_damage.get(asset_class, {})
    max_vals = max_table.get(_normalize_country(resolved))
    if not max_vals:
        return None

    mult = GLOBAL_MULTIPLIER.get(year, 1.0)
    if asset_class in {"residential", "commercial", "industrial"}:
        max_val = max_vals.get(basis or "building_total")
    else:
        max_val = max_vals.get("max_damage")
    if max_val is None:
        return None

    return frac * max_val * mult


def _query_daylight_building_areas(
    polygon_wkt: str,
    filter_asset: Optional[str],
    athena_output: str,
    athena_db: str,
    region: str = DAYLIGHT_REGION,
) -> Tuple[Dict[str, float], Optional[str]]:
    """
    Query Daylight OSM for building areas within polygon, grouped by asset class.
    Returns (areas_by_asset: {asset_class: total_sqm}, error_message or None).
    """
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        return {}, "boto3 required for Daylight Athena queries."

    # Escape single quotes in WKT for SQL
    safe_wkt = polygon_wkt.replace("'", "''")

    # Build CASE from building=* map + osm_infra_categories (amenity, shop, office, tourism, landuse, industrial)
    whens = _build_tag_to_asset_case_parts(filter_asset)
    case_expr = "CASE " + " ".join(whens) + " ELSE 'residential' END"

    filter_clause = f" AND asset_class = '{filter_asset}'" if filter_asset else ""

    query = f"""
    SELECT asset_class, COALESCE(SUM(square_meters), 0) AS total_sqm
    FROM (
      SELECT
        {case_expr} AS asset_class,
        square_meters
      FROM daylight_osm_features
      WHERE release = '{DAYLIGHT_RELEASE}'
        AND type = 'way'
        AND square_meters > 0
        AND (
          (tags['building'] IS NOT NULL AND tags['building'] <> 'no')
          OR tags['amenity'] IS NOT NULL
          OR tags['shop'] IS NOT NULL
          OR tags['office'] IS NOT NULL
          OR tags['tourism'] IS NOT NULL
          OR tags['landuse'] IS NOT NULL
          OR tags['industrial'] IS NOT NULL
        )
        AND ST_Contains(
              ST_GeometryFromText('{safe_wkt}'),
              ST_GeometryFromText(wkt)
            )
    ) t
    WHERE 1=1{filter_clause}
    GROUP BY asset_class
    """
    client = boto3.client("athena", region_name=region)
    try:
        exec_resp = client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={"Database": athena_db},
            ResultConfiguration={"OutputLocation": athena_output.rstrip("/") + "/"},
        )
        qid = exec_resp["QueryExecutionId"]
    except ClientError as e:
        return {}, f"Athena start_query failed: {e}"

    for _ in range(60):
        status = client.get_query_execution(QueryExecutionId=qid)
        state = status["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            reason = status["QueryExecution"]["Status"].get("StateChangeReason", "")
            return {}, f"Athena query {state}: {reason}"
        time.sleep(2)

    try:
        results = client.get_query_results(QueryExecutionId=qid)
        rows = results.get("ResultSet", {}).get("Rows", [])
    except ClientError as e:
        return {}, f"Athena get_results failed: {e}"

    areas: Dict[str, float] = {}
    cols = [c.get("VarCharValue", "").strip() for c in rows[0]["Data"]] if rows else []
    for row in rows[1:]:
        data = row.get("Data", [])
        if len(data) < 2:
            continue
        asset = (data[0].get("VarCharValue") or "").strip()
        sqm_str = (data[1].get("VarCharValue") or "0").strip()
        try:
            sqm = float(sqm_str)
        except (TypeError, ValueError):
            sqm = 0
        if asset:
            areas[asset] = areas.get(asset, 0) + sqm

    return areas, None


def _ensure_daylight_table(athena_db: str, athena_output: str, region: str) -> Optional[str]:
    """Create daylight_osm_features table if missing. Returns error message or None."""
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        return "boto3 required"

    create_sql = f"""
    CREATE EXTERNAL TABLE IF NOT EXISTS daylight_osm_features (
      id BIGINT,
      version INT,
      changeset BIGINT,
      created_at TIMESTAMP,
      tags MAP<STRING,STRING>,
      wkt STRING,
      min_lon DOUBLE,
      max_lon DOUBLE,
      min_lat DOUBLE,
      max_lat DOUBLE,
      quadkey STRING,
      linear_meters DOUBLE,
      square_meters DOUBLE
    )
    PARTITIONED BY (release STRING, type STRING)
    STORED AS PARQUET
    LOCATION 's3://daylight-openstreetmap/parquet/osm_features/'
    """
    client = boto3.client("athena", region_name=region)
    try:
        client.start_query_execution(
            QueryString=create_sql,
            QueryExecutionContext={"Database": athena_db},
            ResultConfiguration={"OutputLocation": athena_output.rstrip("/") + "/"},
        )
        time.sleep(3)
        client.start_query_execution(
            QueryString="MSCK REPAIR TABLE daylight_osm_features",
            QueryExecutionContext={"Database": athena_db},
            ResultConfiguration={"OutputLocation": athena_output.rstrip("/") + "/"},
        )
    except ClientError as e:
        err_msg = str(e)
        if "S3 location" in err_msg and "invalid" in err_msg.lower():
            err_msg += " The results bucket must be in the same region as Athena: us-west-2. Create an S3 bucket in us-west-2 and set DAYLIGHT_ATHENA_OUTPUT to s3://that-bucket/."
        return err_msg
    return None


@mcp.tool()
def flood_damage_city_tool(
    city: str,
    depth_m: float,
    year: Optional[int] = None,
    asset_class: Optional[str] = None,
    continent: Optional[str] = None,
) -> ToolResponse:
    """
    Estimate total flood damage for a city by combining flood damage per m²
    (from the global depth-damage dataset) with building areas from Daylight OSM.

    Args:
        city: City name (e.g., "Paris", "Lyon, France").
        depth_m: Flood depth in meters (e.g., 1, 2, 3).
        year: Year for cost multiplier (defaults to current year).
        asset_class: If set, only include this building type (residential, commercial, industrial).
        continent: Continent for damage curve (e.g., Europe); defaults from country.


    """
    if not isinstance(city, str) or not city.strip():
        return ToolResponse(
            tool_name="flood_damage_city_tool",
            message="Please provide a city name.",
            error=True,
        )
    try:
        depth_val = float(depth_m)
    except Exception:
        return ToolResponse(
            tool_name="flood_damage_city_tool",
            message="Depth must be a numeric value in meters.",
            error=True,
        )
    try:
        resolved_year = _resolve_year(year)
    except Exception as exc:
        return ToolResponse(
            tool_name="flood_damage_city_tool",
            message=str(exc),
            error=True,
        )

    polygon_wkt, country, display_name = _get_city_polygon_and_country(city.strip())
    if not polygon_wkt or not country:
        return ToolResponse(
            tool_name="flood_damage_city_tool",
            message=f"Could not geocode city '{city}' or retrieve boundary polygon. Try a more specific name (e.g. 'Paris, France').",
            error=True,
        )

    filter_asset = None
    if asset_class:
        filter_asset = _normalize_asset_class(asset_class)
        if not filter_asset:
            return ToolResponse(
                tool_name="flood_damage_city_tool",
                message=f"Unsupported asset_class '{asset_class}'. Use residential, commercial, or industrial.",
                error=True,
            )
        if filter_asset not in {"residential", "commercial", "industrial"}:
            return ToolResponse(
                tool_name="flood_damage_city_tool",
                message="City damage tool supports residential, commercial, industrial only.",
                error=True,
            )

    athena_output = (
        get_config().daylight_athena_output
        or os.environ.get("DAYLIGHT_ATHENA_OUTPUT")
        or ""
    ).strip()
    if not athena_output or athena_output.startswith("s3://your-"):
        return ToolResponse(
            tool_name="flood_damage_city_tool",
            message="DAYLIGHT_ATHENA_OUTPUT must be set to an S3 URI in us-west-2 (e.g. s3://your-bucket/daylight/). The bucket must be in us-west-2 because Athena runs there for Daylight OSM.",
            data={"city": display_name, "country": country},
            city=display_name,
            country=country,
            error=True,
        )

    athena_db = os.environ.get("ATHENA_DB") or get_config().athena_db or "default"

    err = _ensure_daylight_table(athena_db, athena_output, DAYLIGHT_REGION)
    if err:
        logger.warning("Daylight table ensure: %s", err)

    areas, query_err = _query_daylight_building_areas(
        polygon_wkt, filter_asset, athena_output, athena_db, DAYLIGHT_REGION
    )
    if query_err:
        return ToolResponse(
            tool_name="flood_damage_city_tool",
            message=f"Daylight OSM query failed: {query_err}",
            data={"city": display_name, "country": country},
            city=display_name,
            country=country,
            error=True,
        )

    if not areas:
        return ToolResponse(
            tool_name="flood_damage_city_tool",
            message=f"No buildings found within {display_name}.",
            data={"city": display_name, "country": country, "depth_m": depth_val},
            city=display_name,
            country=country,
            error=False,
        )

    cont = _normalize_continent(continent) or "europe"  # default for European cities
    basis = "building_total"
    cost_per_m2: Dict[str, float] = {}
    for ac in areas:
        cp = _get_damage_per_m2(country, ac, depth_val, resolved_year, cont, basis)
        if cp is not None:
            cost_per_m2[ac] = cp

    breakdown: List[Dict[str, Any]] = []
    total_cost = 0.0
    total_area = 0.0

    for ac, sqm in areas.items():
        cp = cost_per_m2.get(ac)
        if cp is None:
            continue
        cost = sqm * cp
        total_cost += cost
        total_area += sqm
        breakdown.append({
            "asset_class": ac,
            "area_m2": round(sqm, 2),
            "cost_per_m2_eur": round(cp, 2),
            "estimated_damage_eur": round(cost, 2),
        })

    message = (
        f"Estimated total flood damage for {display_name}: {total_cost:,.0f} EUR "
        f"at {depth_val} m depth (year {resolved_year}). "
        f"Total building area: {total_area:,.0f} m². "
        f"Breakdown by type: " + "; ".join(
            f"{b['asset_class']}: {b['area_m2']:,.0f} m² → {b['estimated_damage_eur']:,.0f} EUR"
            for b in breakdown
        ) + "."
    )

    return ToolResponse(
        tool_name="flood_damage_city_tool",
        message=message,
        city=display_name,
        country=country,
        data={
            "city": display_name,
            "country": country,
            "depth_m": depth_val,
            "year": resolved_year,
            "total_area_m2": round(total_area, 2),
            "total_estimated_damage_eur": round(total_cost, 2),
            "breakdown": breakdown,
            "unit": "EUR",
        },
        error=False,
    )
