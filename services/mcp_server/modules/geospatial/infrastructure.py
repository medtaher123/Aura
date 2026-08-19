"""
Infrastructure Query Tool for OpenStreetMap (OSM) on AWS Athena

Answers questions about types and counts of infrastructure near a location.
Uses osm_infra_categories.json (and optional type_to_tag_keys.json) to resolve
query types to OSM tag keys and values.
"""

import json
import os
import math
import time
from pathlib import Path
from typing import Optional, List

import boto3
from botocore.exceptions import ClientError

from core.logger import get_logger
from config import get_config
from utils.bbox_service import LocationAmbiguousError, get_city_bbox, reverse_geocode
from utils.map_view_service import view_state_from_bbox, view_state_from_points
from utils.contracts import ToolArtifacts, ToolCoordinates, ToolResponse

logger = get_logger(__name__)

# Default tag keys when no config is loaded
DEFAULT_INFRA_TAG_KEYS = ("amenity", "building", "landuse", "industrial")

# Fallback if JSON not found (keep same behavior as before)
INFRASTRUCTURE_GROUPS: dict[str, list[str]] = {
    "healthcare": [
        "hospital", "clinic", "doctors", "dentist", "pharmacy", "nursing_home", "healthcare",
    ],
    "education": [
        "school", "college", "university", "kindergarten", "language_school", "music_school", "driving_school",
    ],
    "emergency": [
        "police", "fire_station", "ambulance_station", "emergency_service",
    ],
    "transport": [
        "bus_station", "ferry_terminal", "taxi", "parking", "fuel", "charging_station",
    ],
    "industrial": [
        "industrial", "factory", "warehouse", "manufacture", "works", "depot",
    ],
}
INFRASTRUCTURE_GROUP_ALIASES: dict[str, str] = {
    "health": "healthcare", "medical": "healthcare",
    "education_facilities": "education", "educational": "education", "schools": "education",
    "emergency_services": "emergency",
    "transportation": "transport",
    "industry": "industrial", "manufacturing": "industrial",
    "shops": "shop", "retail": "shop", "offices": "office", "religious": "religion", "worship": "religion",
}

_OSM_INFRA_CONFIG: dict | None = None

def _load_osm_infra_config() -> dict:
    """Load osm_infra_categories.json and optional type_to_tag_keys.json from utils. Cached."""
    global _OSM_INFRA_CONFIG
    if _OSM_INFRA_CONFIG is not None:
        return _OSM_INFRA_CONFIG
    utils_dir = Path(__file__).resolve().parents[2] / "utils"
    categories_path = utils_dir / "osm_infra_categories.json"
    type_to_keys_path = utils_dir / "type_to_tag_keys.json"
    config: dict = {
        "infra_tag_keys": list(DEFAULT_INFRA_TAG_KEYS),
        "semantic_categories": {},
        "aliases": dict(INFRASTRUCTURE_GROUP_ALIASES),
        "type_to_tag_keys": {},
    }
    if categories_path.is_file():
        try:
            with open(categories_path, encoding="utf-8") as f:
                data = json.load(f)
            config["infra_tag_keys"] = data.get("infra_tag_keys", config["infra_tag_keys"])
            config["semantic_categories"] = data.get("semantic_categories", {})
            config["aliases"] = {k.lower(): v.lower() for k, v in data.get("aliases", config["aliases"]).items()}
        except Exception as e:
            logger.warning("Could not load osm_infra_categories.json: %s", e)
    if type_to_keys_path.is_file():
        try:
            with open(type_to_keys_path, encoding="utf-8") as f:
                config["type_to_tag_keys"] = json.load(f)
        except Exception as e:
            logger.warning("Could not load type_to_tag_keys.json: %s", e)
    _OSM_INFRA_CONFIG = config
    return config

def _resolve_type_to_tag_filters(
    normalized_type: str,
    config: dict,
) -> list[tuple[str, list[str] | None]]:
    """
    Resolve a requested type (e.g. 'healthcare', 'shop') to (tag_key, values).
    values is a list of values to match, or None for 'any non-null'.
    """
    aliases = config.get("aliases", {})
    semantic = config.get("semantic_categories", {})
    type_to_keys = config.get("type_to_tag_keys", {})
    infra_keys = set(config.get("infra_tag_keys", DEFAULT_INFRA_TAG_KEYS))

    resolved = aliases.get(normalized_type, normalized_type)

    # Semantic category: e.g. healthcare -> { amenity: [hospital, clinic, ...] }
    if resolved in semantic:
        out: list[tuple[str, list[str] | None]] = []
        for tag_key, values in semantic[resolved].items():
            if tag_key not in infra_keys:
                continue
            out.append((tag_key, values if values else None))
        if out:
            return out

    # Type is a tag key name: e.g. shop -> (shop, any)
    if resolved in infra_keys:
        return [(resolved, None)]

    # Type from type_to_tag_keys: e.g. "address" -> [addr:city, addr:street, ...]
    if resolved in type_to_keys:
        keys = type_to_keys[resolved]
        return [(k, None) for k in keys if k in infra_keys]

    # Single value type (legacy): treat as value to search in default keys
    return [(k, [resolved]) for k in DEFAULT_INFRA_TAG_KEYS]

def _normalize_infra_type(value: str) -> str:
    return str(value).strip().lower()

def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            output.append(value)
            seen.add(value)
    return output

def _parse_s3_bucket(s3_uri: str) -> str | None:
    if not isinstance(s3_uri, str):
        return None
    if not s3_uri.startswith("s3://"):
        return None
    remainder = s3_uri.replace("s3://", "", 1)
    bucket = remainder.split("/", 1)[0].strip()
    return bucket or None

def _list_athena_databases(client, catalog_name: str = "AwsDataCatalog") -> list[str]:
    paginator = client.get_paginator("list_databases")
    databases: list[str] = []
    for page in paginator.paginate(CatalogName=catalog_name):
        for db in page.get("DatabaseList", []):
            name = db.get("Name")
            if name:
                databases.append(name)
    return databases

def _database_has_table(
    client,
    db_name: str,
    table_name: str,
    catalog_name: str = "AwsDataCatalog",
) -> bool:
    paginator = client.get_paginator("list_table_metadata")
    for page in paginator.paginate(CatalogName=catalog_name, DatabaseName=db_name):
        for table in page.get("TableMetadataList", []):
            if table.get("Name") == table_name:
                return True
    return False

def _resolve_athena_db(
    client, preferred_db: str, table: str, catalog_name: str = "AwsDataCatalog"
) -> tuple[str, str | None]:
    """
    Resolve a usable Athena database name.
    Returns (resolved_db, note) where note is a human-readable message when a fallback is used.
    """
    try:
        databases = _list_athena_databases(client, catalog_name=catalog_name)
    except Exception:
        return preferred_db, None

    if preferred_db in databases:
        return preferred_db, None

    if table:
        for candidate in databases:
            try:
                if _database_has_table(
                    client, candidate, table, catalog_name=catalog_name
                ):
                    return (
                        candidate,
                        f"ATHENA_DB '{preferred_db}' not found; using '{candidate}' which contains '{table}'.",
                    )
            except Exception:
                continue

    if "default" in databases:
        return (
            "default",
            f"ATHENA_DB '{preferred_db}' not found; using 'default' database.",
        )

    return preferred_db, None

def infrastructure_query_tool(
    *,
    location: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float | None = 50.0,
    infrastructure_types: Optional[List[str]] = None
) -> ToolResponse:
    """
    Query OSM data on Athena to find infrastructure near a location.
    Args:
        location (str, optional): Location name (e.g., city) to geocode.
        lat (float, optional): Latitude of the center point.
        lon (float, optional): Longitude of the center point.
        radius_km (float, optional): Search radius in kilometers. Default is 50.0 km.
        infrastructure_types (list, optional): List of OSM 'amenity', 'building', or 'landuse' types to filter (e.g., ['hospital', 'school']).
    Returns:
        dict: Infrastructure types and counts found within the area.
    """
    try:
        config = get_config()
        if lat is not None and lon is not None:
            try:
                lat_f = float(lat)
                lon_f = float(lon)
            except Exception:
                return ToolResponse(
                    tool_name="infrastructure_query_tool",
                    message="Invalid coordinates provided. lat/lon must be numeric.",
                    error=True,
                )

            coords = ToolCoordinates(lat=lat_f, lon=lon_f)
            resolved_name = None
            if not (isinstance(location, str) and location.strip()):
                try:
                    rev = reverse_geocode(lat_f, lon_f)
                    resolved_name = rev.get("city") or rev.get("country")
                except Exception:
                    resolved_name = None
            resolved_name = resolved_name or location or f"{lat_f:.4f}, {lon_f:.4f}"
        else:
            if not isinstance(location, str) or not location.strip():
                return ToolResponse(
                    tool_name="infrastructure_query_tool",
                    message="Please provide a location name or lat/lon coordinates.",
                    error=True,
                )

            bbox, lat_city, lon_city, city_name_final = get_city_bbox(
                location, require_confirmation=True
            )
            if lat_city is None or lon_city is None:
                return ToolResponse(
                    tool_name="infrastructure_query_tool",
                    message=(
                        f"Could not geocode location '{location}'. "
                        "Try a more specific place name (e.g. 'Paris, France')."
                    ),
                    city=location,
                    error=True,
                )
            try:
                lat_f = float(lat_city)
                lon_f = float(lon_city)
            except Exception:
                return ToolResponse(
                    tool_name="infrastructure_query_tool",
                    message=(
                        f"Geocoding returned non-numeric coordinates for '{location}': "
                        f"lat={lat_city}, lon={lon_city}"
                    ),
                    city=location,
                    error=True,
                )

            coords = ToolCoordinates(lat=lat_f, lon=lon_f)
            resolved_name = city_name_final or location

        radius_km_f = float(radius_km or 50.0)

        athena_db = (
            os.environ.get("ATHENA_DB")
            or getattr(config, "athena_db", None)
            or "default"
        )
        athena_output = os.environ.get("ATHENA_OUTPUT") or getattr(
            config, "athena_output", None
        )
        region = "us-east-1"
        table = os.environ.get("ATHENA_OSM_TABLE", "planet")

        if not isinstance(athena_output, str) or not athena_output.strip():
            return ToolResponse(
                tool_name="infrastructure_query_tool",
                message="ATHENA_OUTPUT is not set. Provide an S3 output bucket (e.g. s3://my-athena-results/).",
                city=resolved_name,
                coordinates=coords,
                data={
                    "radius_km": radius_km_f,
                    "infrastructure_types": infrastructure_types,
                },
                error=True,
            )
        if athena_output.strip().startswith("s3://your-athena-query-results"):
            return ToolResponse(
                tool_name="infrastructure_query_tool",
                message=(
                    "ATHENA_OUTPUT is still set to the placeholder "
                    "'s3://your-athena-query-results/'. Set it to a real S3 bucket URI."
                ),
                city=resolved_name,
                coordinates=coords,
                data={
                    "radius_km": radius_km_f,
                    "infrastructure_types": infrastructure_types,
                },
                error=True,
            )
        if not athena_output.strip().startswith("s3://"):
            return ToolResponse(
                tool_name="infrastructure_query_tool",
                message="ATHENA_OUTPUT must be an S3 URI (e.g. s3://my-athena-results/).",
                city=resolved_name,
                coordinates=coords,
                data={
                    "radius_km": radius_km_f,
                    "infrastructure_types": infrastructure_types,
                },
                error=True,
            )

        bucket = _parse_s3_bucket(athena_output.strip())
        if not bucket:
            return ToolResponse(
                tool_name="infrastructure_query_tool",
                message="ATHENA_OUTPUT S3 URI is invalid. Expected format: s3://bucket/prefix",
                city=resolved_name,
                coordinates=coords,
                data={
                    "radius_km": radius_km_f,
                    "infrastructure_types": infrastructure_types,
                },
                error=True,
            )

        try:
            s3_client = boto3.client("s3", region_name=region)
            loc = s3_client.get_bucket_location(Bucket=bucket)
            bucket_region = loc.get("LocationConstraint") or "us-east-1"
            if bucket_region != region:
                return ToolResponse(
                    tool_name="infrastructure_query_tool",
                    message=(
                        f"ATHENA_OUTPUT bucket region mismatch. Bucket '{bucket}' is in "
                        f"{bucket_region}, but AWS_REGION is {region}. "
                        f"Set AWS_REGION={bucket_region} or use a bucket in {region}."
                    ),
                    city=resolved_name,
                    coordinates=coords,
                    data={
                        "radius_km": radius_km_f,
                        "infrastructure_types": infrastructure_types,
                        "athena_output": athena_output,
                        "aws_region": region,
                        "bucket_region": bucket_region,
                    },
                    error=True,
                )
        except ClientError as e:
            return ToolResponse(
                tool_name="infrastructure_query_tool",
                message=f"Unable to access ATHENA_OUTPUT bucket '{bucket}': {str(e)}",
                city=resolved_name,
                coordinates=coords,
                data={
                    "radius_km": radius_km_f,
                    "infrastructure_types": infrastructure_types,
                    "athena_output": athena_output,
                    "aws_region": region,
                },
                error=True,
            )

        delta_lat = radius_km_f / 111.0
        delta_lon = radius_km_f / (111.0 * abs(math.cos(math.radians(lat_f))) + 1e-6)
        min_lat = lat_f - delta_lat
        max_lat = lat_f + delta_lat
        min_lon = lon_f - delta_lon
        max_lon = lon_f + delta_lon

        config = _load_osm_infra_config()
        infra_tag_keys = config.get("infra_tag_keys", list(DEFAULT_INFRA_TAG_KEYS))
        default_keys = list(DEFAULT_INFRA_TAG_KEYS)

        # Resolve each requested type to (tag_key, values or None for any)
        tag_filters: list[tuple[str, list[str] | None]] = []
        expanded_types: list[str] = []
        group_expansions: dict[str, list[str]] = {}
        if infrastructure_types:
            for raw_type in infrastructure_types:
                if raw_type is None:
                    continue
                raw_str = str(raw_type).strip()
                if not raw_str:
                    continue
                normalized = _normalize_infra_type(raw_str)
                resolved = _resolve_type_to_tag_filters(normalized, config)
                for tag_key, values in resolved:
                    tag_filters.append((tag_key, values))
                    if values:
                        expanded_types.extend(values)
                        group_expansions.setdefault(raw_str, []).extend(values)
                    else:
                        expanded_types.append(raw_str)
            expanded_types = _unique_preserve_order(expanded_types)
            for k in group_expansions:
                group_expansions[k] = _unique_preserve_order(group_expansions[k])

        # Tag keys to use in SELECT/GROUP BY: default 4 + any key that appears in filters
        keys_in_filters = {k for k, _ in tag_filters}
        query_tag_keys = _unique_preserve_order(
            [k for k in default_keys if k in infra_tag_keys]
            + [k for k in infra_tag_keys if k in keys_in_filters and k not in default_keys]
        )
        if not query_tag_keys:
            query_tag_keys = list(default_keys)

        # WHERE: (tags[key] IN (...) OR tags[key] IS NOT NULL OR ...)
        filter_parts: list[str] = []
        for tag_key, values in tag_filters:
            safe_key = str(tag_key).replace("'", "''").replace("\\", "\\\\")
            if values:
                safe_vals = [str(v).replace("'", "''") for v in values]
                filter_parts.append(f"tags['{safe_key}'] IN (" + ", ".join(f"'{v}'" for v in safe_vals) + ")")
            else:
                filter_parts.append(f"tags['{safe_key}'] IS NOT NULL")
        if filter_parts:
            infra_filter = " AND (" + " OR ".join(filter_parts) + ")"
        else:
            default_key_conds = " OR ".join(
                f"tags['{k}'] IS NOT NULL" for k in default_keys if k in infra_tag_keys
            )
            infra_filter = f" AND ({default_key_conds})" if default_key_conds else ""

        select_cols = ", ".join(f"tags['{k}'] as {k}" for k in query_tag_keys)
        group_by_cols = ", ".join(f"tags['{k}']" for k in query_tag_keys)

        query = f"""
        SELECT
            {select_cols},
            COUNT(*) as count
        FROM {table}
        WHERE lat BETWEEN {min_lat} AND {max_lat}
          AND lon BETWEEN {min_lon} AND {max_lon}
          AND tags IS NOT NULL
          AND cardinality(tags) > 0
          {infra_filter}
        GROUP BY {group_by_cols}
        ORDER BY count DESC
        LIMIT 50
        """

        client = boto3.client("athena", region_name=region)
        databases = None
        try:
            databases = _list_athena_databases(client)
        except Exception:
            databases = None

        def _run_ddl(ddl: str, database_name: str) -> None:
            response = client.start_query_execution(
                QueryString=ddl,
                QueryExecutionContext={"Database": database_name},
                ResultConfiguration={"OutputLocation": athena_output},
            )
            query_execution_id = response["QueryExecutionId"]
            while True:
                result = client.get_query_execution(
                    QueryExecutionId=query_execution_id
                )
                state = result["QueryExecution"]["Status"]["State"]
                if state in ["SUCCEEDED", "FAILED", "CANCELLED"]:
                    if state != "SUCCEEDED":
                        reason = result["QueryExecution"]["Status"].get(
                            "StateChangeReason"
                        )
                        raise RuntimeError(
                            f"Athena DDL failed ({state}). {reason or ''}".strip()
                        )
                    return
                time.sleep(2)

        if databases == []:
            bootstrap = os.environ.get("ATHENA_BOOTSTRAP", "true").lower()
            if bootstrap in {"1", "true", "yes", "y"}:
                bootstrap_db = athena_db or "osm"
                create_db = f"CREATE DATABASE IF NOT EXISTS {bootstrap_db}"
                try:
                    _run_ddl(create_db, "default")
                except Exception as e:
                    return ToolResponse(
                        tool_name="infrastructure_query_tool",
                        message=(
                            "Unable to create Athena database. Ensure the IAM role/user "
                            "allows athena:StartQueryExecution and has access to "
                            f"ATHENA_OUTPUT. Error: {str(e)}"
                        ),
                        city=resolved_name,
                        coordinates=coords,
                        data={
                            "radius_km": radius_km_f,
                            "infrastructure_types": infrastructure_types,
                            "athena_db": athena_db,
                            "aws_region": region,
                        },
                        error=True,
                    )

                create_table = (
                    "CREATE EXTERNAL TABLE IF NOT EXISTS planet (\n"
                    "  id BIGINT,\n"
                    "  type STRING,\n"
                    "  tags MAP<STRING,STRING>,\n"
                    "  lat DECIMAL(9,7),\n"
                    "  lon DECIMAL(10,7),\n"
                    "  nds ARRAY<STRUCT<ref: BIGINT>>,\n"
                    "  members ARRAY<STRUCT<type: STRING, ref: BIGINT, role: STRING>>,\n"
                    "  changeset BIGINT,\n"
                    "  timestamp TIMESTAMP,\n"
                    "  uid BIGINT,\n"
                    "  user STRING,\n"
                    "  version BIGINT\n"
                    ")\n"
                    "STORED AS ORCFILE\n"
                    "LOCATION 's3://osm-pds/planet/';"
                )
                try:
                    _run_ddl(create_table, bootstrap_db)
                    table = "planet"
                    athena_db = bootstrap_db
                    databases = _list_athena_databases(client)
                except Exception as e:
                    return ToolResponse(
                        tool_name="infrastructure_query_tool",
                        message=(
                            "Unable to create OSM table in Athena. Ensure the IAM role/user "
                            "has permissions and that the AWS account/region can access "
                            f"s3://osm-pds/planet/. Error: {str(e)}"
                        ),
                        city=resolved_name,
                        coordinates=coords,
                        data={
                            "radius_km": radius_km_f,
                            "infrastructure_types": infrastructure_types,
                            "athena_db": athena_db,
                            "aws_region": region,
                        },
                        error=True,
                    )
            else:
                return ToolResponse(
                    tool_name="infrastructure_query_tool",
                    message=(
                        "No Athena databases found in AwsDataCatalog. Create a Glue/Athena "
                        "database for your OSM tables or set ATHENA_DB to an existing "
                        "database name in this account/region."
                    ),
                    city=resolved_name,
                    coordinates=coords,
                    data={
                        "radius_km": radius_km_f,
                        "infrastructure_types": infrastructure_types,
                        "athena_db": athena_db,
                        "aws_region": region,
                    },
                    error=True,
                )
        athena_db_resolved, db_note = _resolve_athena_db(client, athena_db, table)
        if db_note:
            logger.warning(db_note)

        def _execute_query(database_name: str) -> tuple[str, dict, str]:
            response = client.start_query_execution(
                QueryString=query,
                QueryExecutionContext={"Database": database_name},
                ResultConfiguration={"OutputLocation": athena_output},
            )
            query_execution_id = response["QueryExecutionId"]
            while True:
                result = client.get_query_execution(
                    QueryExecutionId=query_execution_id
                )
                state = result["QueryExecution"]["Status"]["State"]
                if state in ["SUCCEEDED", "FAILED", "CANCELLED"]:
                    return state, result, query_execution_id
                time.sleep(2)

        try:
            state, result, query_execution_id = _execute_query(athena_db_resolved)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code == "AccessDeniedException":
                message = (
                    "Athena access denied. Ensure the IAM role/user allows "
                    "athena:StartQueryExecution and S3 write access to ATHENA_OUTPUT."
                )
            elif code == "InvalidRequestException":
                message = (
                    "Athena request invalid. Verify ATHENA_OUTPUT points to a "
                    "valid, accessible S3 bucket."
                )
            else:
                message = f"Athena query failed: {str(e)}"
            return ToolResponse(
                tool_name="infrastructure_query_tool",
                message=message,
                city=resolved_name,
                coordinates=coords,
                data={
                    "radius_km": radius_km_f,
                    "infrastructure_types": infrastructure_types,
                    "athena_db": athena_db_resolved,
                },
                error=True,
            )

        if state != "SUCCEEDED":
            reason = result["QueryExecution"]["Status"].get("StateChangeReason")
            if (
                state == "FAILED"
                and reason
                and "SCHEMA_NOT_FOUND" in reason
                and athena_db_resolved != "default"
            ):
                try:
                    retry_state, retry_result, retry_id = _execute_query("default")
                except ClientError:
                    retry_state, retry_result, retry_id = state, result, query_execution_id

                if retry_state == "SUCCEEDED":
                    athena_db_resolved = "default"
                    state = retry_state
                    result = retry_result
                    query_execution_id = retry_id
                else:
                    state = retry_state
                    result = retry_result
                    query_execution_id = retry_id

            if state != "SUCCEEDED":
                reason = result["QueryExecution"]["Status"].get("StateChangeReason")
                message = f"Athena query failed ({state})."
                if reason:
                    message = f"{message} {reason}"
                logger.error(message)
                return ToolResponse(
                    tool_name="infrastructure_query_tool",
                    message=message,
                    city=resolved_name,
                    coordinates=coords,
                    data={
                        "radius_km": radius_km_f,
                        "infrastructure_types": infrastructure_types,
                        "athena_db": athena_db_resolved,
                    },
                    error=True,
                )

        results = client.get_query_results(QueryExecutionId=query_execution_id)
        rows = results["ResultSet"]["Rows"]
        infra_list = []
        if rows:
            header = rows[0]["Data"]
            col_names = [c.get("VarCharValue", "").strip() for c in header]
            for row in rows[1:]:
                data = row["Data"]
                infra = {
                    col_names[i]: data[i].get("VarCharValue", "") if i < len(data) else ""
                    for i in range(len(col_names))
                }
                raw_count = infra.get("count", "1")
                try:
                    infra["count"] = int(float(raw_count)) if raw_count else 1
                except (TypeError, ValueError):
                    infra["count"] = 1
                infra_list.append(infra)

        infra_counts = {}
        group_breakdown: dict[str, dict[str, int]] = {}
        if infrastructure_types:
            for t in infrastructure_types:
                if t is None:
                    continue
                raw_str = str(t).strip()
                if not raw_str:
                    continue
                infra_counts[raw_str] = 0
                if raw_str in group_expansions:
                    group_breakdown[raw_str] = {
                        subtype: 0 for subtype in group_expansions[raw_str]
                    }
            tag_keys_for_counts = query_tag_keys
            for row in infra_list:
                row_count = row.get("count", 0)
                for key in tag_keys_for_counts:
                    value = row.get(key) or ""
                    if not value:
                        continue
                    if value in infra_counts:
                        infra_counts[value] += row_count
                    for group_name, subtypes in group_expansions.items():
                        if value in subtypes:
                            infra_counts[group_name] += row_count
                            if group_name in group_breakdown:
                                group_breakdown[group_name][value] += row_count

        def _fmt(n: int) -> str:
            return f"{n:,}" if n >= 0 else str(n)

        message_details = ""
        if infra_counts:
            detail_parts = [
                f"{infra_type}: {_fmt(infra_counts[infra_type])}"
                for infra_type in infra_counts
            ]
            message_details = " " + ", ".join(detail_parts) + "."

        # Build subcategory breakdown (e.g. hospital: 120, clinic: 250, ...) for each requested type
        breakdown_parts: list[str] = []
        if infrastructure_types and group_breakdown:
            for req_type in infrastructure_types:
                if req_type is None:
                    continue
                raw_str = str(req_type).strip()
                if raw_str not in group_breakdown:
                    continue
                subcounts = group_breakdown[raw_str]
                # Only include subtypes with count > 0, sorted by count descending
                sub_items = [
                    (st, c) for st, c in subcounts.items() if c > 0
                ]
                sub_items.sort(key=lambda x: -x[1])
                if sub_items:
                    sub_str = ", ".join(
                        f"{st}: {_fmt(c)}" for st, c in sub_items
                    )
                    breakdown_parts.append(
                        f"Breakdown for {raw_str}: {sub_str}."
                    )
        breakdown_text = " ".join(breakdown_parts)

        if infra_list:
            if infrastructure_types:
                total_count = sum(infra_counts.values())
                total_str = _fmt(total_count)
                type_label = infrastructure_types[0] if len(infrastructure_types) == 1 else "infrastructure"
                message = (
                    f"Found {total_str} {type_label} facilities within {radius_km_f} km of {resolved_name}."
                )
                if breakdown_text:
                    message += " " + breakdown_text
                elif message_details:
                    message += message_details
            else:
                message = (
                    f"Found {len(infra_list)} types of infrastructure within {radius_km_f} km of "
                    f"{resolved_name}."
                )
        else:
            message = f"No infrastructure found within {radius_km_f} km of {resolved_name}."

        map_types: list[str] = []
        if expanded_types:
            map_types = expanded_types[:10]
        else:
            for row in infra_list:
                for key in query_tag_keys:
                    value = row.get(key) or ""
                    if value and value not in map_types:
                        map_types.append(value)
                    if len(map_types) >= 10:
                        break
                if len(map_types) >= 10:
                    break

        map_points: list[dict] = []
        if map_types:
            map_filter_parts = [
                " OR ".join(
                    f"tags['{k}'] = '{str(t).replace(chr(39), chr(39)+chr(39))}'" for k in query_tag_keys
                )
                for t in map_types
            ]
            map_filter = " AND (" + " OR ".join(f"({p})" for p in map_filter_parts) + ")"

            points_query = f"""
            SELECT
                lat,
                lon,
                tags['amenity'] as amenity,
                tags['building'] as building,
                tags['landuse'] as landuse,
                tags['industrial'] as industrial,
                tags['name'] as name
            FROM {table}
            WHERE lat BETWEEN {min_lat} AND {max_lat}
              AND lon BETWEEN {min_lon} AND {max_lon}
              {map_filter}
            LIMIT 200
            """

            response = client.start_query_execution(
                QueryString=points_query,
                QueryExecutionContext={"Database": athena_db_resolved},
                ResultConfiguration={"OutputLocation": athena_output},
            )
            points_query_id = response["QueryExecutionId"]
            while True:
                result = client.get_query_execution(
                    QueryExecutionId=points_query_id
                )
                state = result["QueryExecution"]["Status"]["State"]
                if state in ["SUCCEEDED", "FAILED", "CANCELLED"]:
                    break
                time.sleep(2)

            if state == "SUCCEEDED":
                points_results = client.get_query_results(
                    QueryExecutionId=points_query_id
                )
                for row in points_results["ResultSet"]["Rows"][1:]:
                    data = row["Data"]
                    try:
                        lat_val = float(data[0].get("VarCharValue", "0"))
                        lon_val = float(data[1].get("VarCharValue", "0"))
                    except Exception:
                        continue
                    amenity = data[2].get("VarCharValue", "")
                    building = data[3].get("VarCharValue", "")
                    landuse = data[4].get("VarCharValue", "")
                    industrial = data[5].get("VarCharValue", "")
                    name = data[6].get("VarCharValue", "")
                    if amenity:
                        kind, value = "amenity", amenity
                    elif building:
                        kind, value = "building", building
                    elif landuse:
                        kind, value = "landuse", landuse
                    else:
                        kind, value = "industrial", industrial
                    map_points.append(
                        {
                            "lat": lat_val,
                            "lon": lon_val,
                            "name": name or value,
                            "kind": kind,
                            "value": value,
                        }
                    )

        view_state = (
            view_state_from_points(map_points, padding=0.18, min_zoom=5.0, max_zoom=10.5, radius=radius_km_f)
            if map_points
            else view_state_from_bbox(coords, padding=0.18, min_zoom=5.0, max_zoom=10.5, radius=radius_km_f)
        )
        artifacts = ToolArtifacts(
            maps= [
                {
                    "title": f"Infrastructure near {resolved_name}",
                    "points": map_points,
                    "view_state": view_state,
                    "tooltip": {"text": "{name}\n{kind}: {value}"},
                    "fill_color": [40, 120, 255, 160],
                    "radius": 6,
                    "radius_units": "pixels",
                    "radius_min_pixels": 2,
                    "radius_max_pixels": 8,
                }
            ],
            thumbnails= [],
            urls= [],
        )

        return ToolResponse(
            tool_name="infrastructure_query_tool",
            message=message,
            artifacts=artifacts,
            city=resolved_name,
            coordinates=coords,
            data={
                "infrastructure": infra_list,
                "radius_km": radius_km_f,
                "infrastructure_types": infrastructure_types,
                "expanded_infrastructure_types": expanded_types,
                "group_expansions": group_expansions,
                "group_breakdown": group_breakdown,
                "map_points": len(map_points),
                "map_types": map_types,
                "athena_db": athena_db_resolved,
            },
            error=False,
        )
    except LocationAmbiguousError as e:
        return ToolResponse(
            tool_name="infrastructure_query_tool",
            message=f"I found multiple matches for '{e.query}'. Please confirm the correct location.",
            city=location,
            data={
                "needs_location_confirmation": True,
                "location_query": e.query,
                "candidates": e.candidates,
                "resume_patch": {"field": "location"},
            },
            error=False,
        )
    except Exception as e:
        logger.error(f"Error in infrastructure_query_tool: {e}")
        return ToolResponse(
            tool_name="infrastructure_query_tool",
            message=f"Error: {str(e)}",
            data={},
            error=True,
        )
