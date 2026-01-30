"""
Infrastructure Query Tool for OpenStreetMap (OSM) on AWS Athena

Answers questions about types and counts of infrastructure near a location.
"""

import os
import math
import time
from typing import Optional, List

import boto3
from botocore.exceptions import ClientError

from mcp_singleton import mcp
from core.logger import get_logger
from config import get_config
from utils.bbox_service import LocationAmbiguousError, get_city_bbox, reverse_geocode
from utils.map_view_service import view_state_from_bbox, view_state_from_points
from utils.contracts import make_tool_response

logger = get_logger(__name__)


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

@mcp.tool()
def infrastructure_query_tool(
    *,
    location: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float | None = 50.0,
    infrastructure_types: Optional[List[str]] = None
) -> dict:
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
                return make_tool_response(
                    tool_name="infrastructure_query_tool",
                    message="Invalid coordinates provided. lat/lon must be numeric.",
                    error=True,
                )

            coords = {"lat": lat_f, "lon": lon_f }
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
                return make_tool_response(
                    tool_name="infrastructure_query_tool",
                    message="Please provide a location name or lat/lon coordinates.",
                    error=True,
                )

            bbox, lat_city, lon_city, city_name_final = get_city_bbox(
                location, require_confirmation=True
            )
            if lat_city is None or lon_city is None:
                return make_tool_response(
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
                return make_tool_response(
                    tool_name="infrastructure_query_tool",
                    message=(
                        f"Geocoding returned non-numeric coordinates for '{location}': "
                        f"lat={lat_city}, lon={lon_city}"
                    ),
                    city=location,
                    error=True,
                )

            coords = {"lat": lat_f, "lon": lon_f}
            resolved_name = city_name_final or location

        try:
            radius_km_f = float(radius_km)
        except Exception:
            radius_km_f = 50.0

        athena_db = (
            os.environ.get("ATHENA_DB")
            or getattr(config, "athena_db", None)
            or "default"
        )
        athena_output = os.environ.get("ATHENA_OUTPUT") or getattr(
            config, "athena_output", None
        )
        if not athena_output:
            athena_output = "s3://your-athena-query-results/"
        region = os.environ.get("AWS_REGION") or getattr(
            config, "aws_region", "us-east-1"
        )
        table = os.environ.get("ATHENA_OSM_TABLE", "planet")

        if not isinstance(athena_output, str) or not athena_output.strip():
            return make_tool_response(
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
            return make_tool_response(
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
            return make_tool_response(
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
            return make_tool_response(
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
                return make_tool_response(
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
            return make_tool_response(
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

        infra_filter = ""
        sanitized_types: list[str] = []
        if infrastructure_types:
            sanitized_types = [str(t).replace("'", "''") for t in infrastructure_types]
            infra_filter = " AND (" + " OR ".join(
                [
                    (
                        "tags['amenity'] = '{t}' OR "
                        "tags['building'] = '{t}' OR "
                        "tags['landuse'] = '{t}'"
                    ).format(t=t)
                    for t in sanitized_types
                ]
            ) + ")"

        query = f"""
        SELECT
            tags['amenity'] as amenity,
            tags['building'] as building,
            tags['landuse'] as landuse,
            COUNT(*) as count
        FROM {table}
        WHERE lat BETWEEN {min_lat} AND {max_lat}
          AND lon BETWEEN {min_lon} AND {max_lon}
          AND (
            tags['amenity'] IS NOT NULL
            OR tags['building'] IS NOT NULL
            OR tags['landuse'] IS NOT NULL
          )
          {infra_filter}
        GROUP BY tags['amenity'], tags['building'], tags['landuse']
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
                    return make_tool_response(
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
                    return make_tool_response(
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
                return make_tool_response(
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
            return make_tool_response(
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
                return make_tool_response(
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
        infra_list = []
        for row in results["ResultSet"]["Rows"][1:]:
            data = row["Data"]
            infra = {
                "amenity": data[0].get("VarCharValue", ""),
                "building": data[1].get("VarCharValue", ""),
                "landuse": data[2].get("VarCharValue", ""),
                "count": int(data[3].get("VarCharValue", "0")),
            }
            infra_list.append(infra)

        infra_counts = {}
        if infrastructure_types:
            for t in infrastructure_types:
                infra_counts[str(t)] = 0
            for row in infra_list:
                for key in ("amenity", "building", "landuse"):
                    value = row.get(key) or ""
                    if value in infra_counts:
                        infra_counts[value] += row.get("count", 0)

        message_details = ""
        if infra_counts:
            detail_parts = [
                f"{infra_type}: {infra_counts[infra_type]}"
                for infra_type in infra_counts
            ]
            message_details = " " + ", ".join(detail_parts) + "."

        if infra_list:
            if infrastructure_types:
                message = (
                    f"Found {len(infra_counts)} types of infrastructure within {radius_km_f} km of "
                    f"{resolved_name}.{message_details}"
                )
            else:
                message = (
                    f"Found {len(infra_list)} types of infrastructure within {radius_km_f} km of "
                    f"{resolved_name}."
                )
        else:
            message = f"No infrastructure found within {radius_km_f} km of {resolved_name}."

        map_types: list[str] = []
        if sanitized_types:
            map_types = sanitized_types
        else:
            for row in infra_list:
                for key in ("amenity", "building", "landuse"):
                    value = row.get(key) or ""
                    if value and value not in map_types:
                        map_types.append(value)
                    if len(map_types) >= 3:
                        break
                if len(map_types) >= 3:
                    break

        map_points: list[dict] = []
        if map_types:
            map_filter = " AND (" + " OR ".join(
                [
                    (
                        "tags['amenity'] = '{t}' OR "
                        "tags['building'] = '{t}' OR "
                        "tags['landuse'] = '{t}'"
                    ).format(t=t)
                    for t in map_types
                ]
            ) + ")"

            points_query = f"""
            SELECT
                lat,
                lon,
                tags['amenity'] as amenity,
                tags['building'] as building,
                tags['landuse'] as landuse,
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
                    name = data[5].get("VarCharValue", "")
                    if amenity:
                        kind, value = "amenity", amenity
                    elif building:
                        kind, value = "building", building
                    else:
                        kind, value = "landuse", landuse
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
        artifacts = {
            "maps": [
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
            "thumbnails": [],
            "urls": [],
        }

        return make_tool_response(
            tool_name="infrastructure_query_tool",
            message=message,
            artifacts=artifacts,
            city=resolved_name,
            coordinates=coords,
            data={
                "infrastructure": infra_list,
                "radius_km": radius_km_f,
                "infrastructure_types": infrastructure_types,
                "map_points": len(map_points),
                "map_types": map_types,
                "athena_db": athena_db_resolved,
            },
            error=False,
        )
    except LocationAmbiguousError as e:
        return make_tool_response(
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
        return make_tool_response(
            tool_name="infrastructure_query_tool",
            message=f"Error: {str(e)}",
            data={},
            error=True,
        )
