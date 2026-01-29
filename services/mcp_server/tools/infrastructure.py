"""
Infrastructure Query Tool for OpenStreetMap (OSM) on AWS Athena

Answers questions about types and counts of infrastructure near a location.
"""

import os
import math
import time
from typing import Optional, List
import boto3
from mcp_singleton import mcp
from core.logger import get_logger
from utils.contracts import make_tool_response

logger = get_logger(__name__)

@ mcp.tool()
def infrastructure_query_tool(
    *,
    lat: float,
    lon: float,
    radius_km: float = 1.0,
    infrastructure_types: Optional[List[str]] = None
) -> dict:
    """
    Query OSM data on Athena to find infrastructure near a location.
    Args:
        lat (float): Latitude of the center point.
        lon (float): Longitude of the center point.
        radius_km (float, optional): Search radius in kilometers. Default is 1.0 km.
        infrastructure_types (list, optional): List of OSM 'amenity', 'building', or 'landuse' types to filter (e.g., ['hospital', 'school']).
    Returns:
        dict: Infrastructure types and counts found within the area.
    """
    try:
        athena_db = os.environ.get("ATHENA_DB", "osm")
        athena_output = os.environ.get("ATHENA_OUTPUT", "s3://your-athena-query-results/")
        region = os.environ.get("AWS_REGION", "us-east-1")
        table = os.environ.get("ATHENA_OSM_TABLE", "planet_osm_point")

        delta_lat = radius_km / 111.0
        delta_lon = radius_km / (111.0 * abs(math.cos(math.radians(lat))) + 1e-6)
        min_lat = lat - delta_lat
        max_lat = lat + delta_lat
        min_lon = lon - delta_lon
        max_lon = lon + delta_lon

        infra_filter = ""
        if infrastructure_types:
            infra_filter = " AND (" + " OR ".join(
                [f"tags['amenity'] = '{t}' OR tags['building'] = '{t}' OR tags['landuse'] = '{t}'" for t in infrastructure_types]
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
          {infra_filter}
        GROUP BY tags['amenity'], tags['building'], tags['landuse']
        HAVING amenity IS NOT NULL OR building IS NOT NULL OR landuse IS NOT NULL
        ORDER BY count DESC
        LIMIT 50
        """

        client = boto3.client("athena", region_name=region)
        response = client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={"Database": athena_db},
            ResultConfiguration={"OutputLocation": athena_output},
        )
        query_execution_id = response["QueryExecutionId"]

        while True:
            result = client.get_query_execution(QueryExecutionId=query_execution_id)
            state = result["QueryExecution"]["Status"]["State"]
            if state in ["SUCCEEDED", "FAILED", "CANCELLED"]:
                break
            time.sleep(2)

        if state != "SUCCEEDED":
            logger.error(f"Athena query failed: {state}")
            return make_tool_response(
                tool_name="infrastructure_query_tool",
                message="Athena query failed.",
                data={},
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

        message = (
            f"Found {len(infra_list)} types of infrastructure within {radius_km} km of ({lat}, {lon})."
            if infra_list else "No infrastructure found in the specified area."
        )

        return make_tool_response(
            tool_name="infrastructure_query_tool",
            message=message,
            data={"infrastructure": infra_list},
            coordinates={"lat": lat, "lon": lon},
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
