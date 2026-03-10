"""BDTOPO road/regulation intersection checks."""

from __future__ import annotations

from core.logger import get_logger
from mcp_singleton import mcp
from tools.bdtopo_common import (
    build_map_artifacts,
    distance_summary,
    normalize_rows,
    run_query,
    top_values,
)
from utils.contracts import BDTOPOIntersectionInputMode, ToolCoordinates, ToolResponse

logger = get_logger(__name__)


@mcp.tool()
def bdtopo_intersection_tool(
    input_mode: BDTOPOIntersectionInputMode = "point",
    lat: float | None = None,
    lon: float | None = None,
    radius_m: int = 5000,
    road_name: str | None = None,
    admin_hint: str | None = None,
    limit: int = 20,
) -> ToolResponse:
    """
    Check intersections between roads and regulated/zoning areas.

    input_mode:
      - point: uses lat/lon and radius_m
      - road_name: uses road_name (+ optional admin_hint)
    """
    safe_limit = min(max(int(limit or 20), 1), 100)
    safe_radius = max(int(radius_m or 1), 1)
    coords = ToolCoordinates(lat=float(lat or 0.0), lon=float(lon or 0.0))

    try:
        if input_mode == "point":
            if lat is None or lon is None:
                return ToolResponse(
                    tool_name="bdtopo_intersection_tool",
                    message="Point mode requires lat and lon.",
                    error=True,
                )
            coords = ToolCoordinates(lat=float(lat), lon=float(lon))
            rows = normalize_rows(
                run_query(
                    """
                    WITH roads AS (
                        SELECT
                            r.cleabs AS road_id,
                            COALESCE(
                                NULLIF(BTRIM(r.nom_voie_ban_gauche), ''),
                                NULLIF(BTRIM(r.nom_voie_ban_droite), ''),
                                NULLIF(BTRIM(r.cpx_toponyme_route_nommee), ''),
                                r.cleabs
                            ) AS road_label,
                            r.nature AS road_nature,
                            r.geometrie AS road_geom
                        FROM bdtopo_raw.troncon_de_route r
                        WHERE ST_DWithin(
                            r.geometrie::geography,
                            ST_SetSRID(ST_Point(%s, %s), 4326)::geography,
                            %s
                        )
                    ),
                    zones AS (
                        SELECT
                            'parc_ou_reserve'::text AS zone_source,
                            p.cleabs::text AS zone_id,
                            COALESCE(NULLIF(BTRIM(p.toponyme), ''), p.cleabs) AS zone_label,
                            COALESCE(NULLIF(BTRIM(p.nature_detaillee), ''), NULLIF(BTRIM(p.nature), '')) AS regulation_type,
                            p.geometrie AS zone_geom
                        FROM bdtopo_raw.parc_ou_reserve p
                        WHERE ST_DWithin(
                            p.geometrie::geography,
                            ST_SetSRID(ST_Point(%s, %s), 4326)::geography,
                            %s
                        )
                        UNION ALL
                        SELECT
                            'zone_d_activite_ou_d_interet'::text AS zone_source,
                            z.cleabs::text AS zone_id,
                            COALESCE(NULLIF(BTRIM(z.toponyme), ''), z.cleabs) AS zone_label,
                            COALESCE(NULLIF(BTRIM(z.nature_detaillee), ''), NULLIF(BTRIM(z.nature), '')) AS regulation_type,
                            z.geometrie AS zone_geom
                        FROM bdtopo_raw.zone_d_activite_ou_d_interet z
                        WHERE ST_DWithin(
                            z.geometrie::geography,
                            ST_SetSRID(ST_Point(%s, %s), 4326)::geography,
                            %s
                        )
                    )
                    SELECT
                        r.road_id,
                        r.road_label,
                        r.road_nature,
                        z.zone_source,
                        z.zone_id,
                        z.zone_label,
                        z.regulation_type,
                        ROUND(
                            ST_Distance(
                                ST_PointOnSurface(ST_Intersection(r.road_geom, z.zone_geom))::geography,
                                ST_SetSRID(ST_Point(%s, %s), 4326)::geography
                            )::numeric,
                            1
                        ) AS distance_m,
                        ST_Y(ST_PointOnSurface(ST_Intersection(r.road_geom, z.zone_geom))) AS feature_lat,
                        ST_X(ST_PointOnSurface(ST_Intersection(r.road_geom, z.zone_geom))) AS feature_lon,
                        ST_AsGeoJSON(
                            ST_SimplifyPreserveTopology(
                                ST_Intersection(r.road_geom, z.zone_geom),
                                0.00002
                            )
                        ) AS geom_geojson
                    FROM roads r
                    JOIN zones z
                      ON ST_Intersects(r.road_geom, z.zone_geom)
                    ORDER BY distance_m
                    LIMIT %s
                    """,
                    (
                        lon,
                        lat,
                        safe_radius,
                        lon,
                        lat,
                        safe_radius,
                        lon,
                        lat,
                        safe_radius,
                        lon,
                        lat,
                        safe_limit,
                    ),
                )
            )
            summary = distance_summary(rows)
            summary["top_regulation_types"] = top_values(rows, "regulation_type")
            summary["top_road_natures"] = top_values(rows, "road_nature")
            return ToolResponse(
                tool_name="bdtopo_intersection_tool",
                message=f"Found {len(rows)} road/regulation intersections within {safe_radius} m.",
                coordinates=coords,
                artifacts=build_map_artifacts(
                    title="BDTOPO intersections (point mode)",
                    coords=coords,
                    radius_m=safe_radius,
                    rows=rows,
                    fill_color=[239, 83, 80, 110],
                ),
                data={
                    "input_mode": "point",
                    "radius_m": safe_radius,
                    "matches": rows,
                    "summary": summary,
                    "prompt_hints": [
                        "Give me intersections with regulation type breakdown.",
                        "Rank intersections by nearest distance to the query point.",
                    ],
                },
                error=False,
            )

        if input_mode == "road_name":
            if not road_name or not road_name.strip():
                return ToolResponse(
                    tool_name="bdtopo_intersection_tool",
                    message="road_name mode requires a non-empty road_name.",
                    error=True,
                )
            like_pattern = f"%{road_name.strip()}%"
            admin_pattern = (
                f"%{admin_hint.strip()}%" if admin_hint and admin_hint.strip() else ""
            )
            rows = normalize_rows(
                run_query(
                    """
                    WITH candidate_roads AS (
                        SELECT
                            r.cleabs AS road_id,
                            COALESCE(
                                NULLIF(BTRIM(r.nom_voie_ban_gauche), ''),
                                NULLIF(BTRIM(r.nom_voie_ban_droite), ''),
                                NULLIF(BTRIM(r.cpx_toponyme_route_nommee), ''),
                                r.cleabs
                            ) AS road_label,
                            r.nature AS road_nature,
                            r.geometrie AS road_geom
                        FROM bdtopo_raw.troncon_de_route r
                        WHERE COALESCE(
                            NULLIF(BTRIM(r.nom_voie_ban_gauche), ''),
                            NULLIF(BTRIM(r.nom_voie_ban_droite), ''),
                            NULLIF(BTRIM(r.cpx_toponyme_route_nommee), '')
                        ) ILIKE %s
                          AND (
                            %s = ''
                            OR EXISTS (
                                SELECT 1
                                FROM bdtopo_raw.commune c
                                WHERE c.code_insee IN (r.insee_commune_gauche, r.insee_commune_droite)
                                  AND c.nom_officiel ILIKE %s
                            )
                          )
                        LIMIT 300
                    ),
                    zones AS (
                        SELECT
                            'parc_ou_reserve'::text AS zone_source,
                            p.cleabs::text AS zone_id,
                            COALESCE(NULLIF(BTRIM(p.toponyme), ''), p.cleabs) AS zone_label,
                            COALESCE(NULLIF(BTRIM(p.nature_detaillee), ''), NULLIF(BTRIM(p.nature), '')) AS regulation_type,
                            p.geometrie AS zone_geom
                        FROM bdtopo_raw.parc_ou_reserve p
                        UNION ALL
                        SELECT
                            'zone_d_activite_ou_d_interet'::text AS zone_source,
                            z.cleabs::text AS zone_id,
                            COALESCE(NULLIF(BTRIM(z.toponyme), ''), z.cleabs) AS zone_label,
                            COALESCE(NULLIF(BTRIM(z.nature_detaillee), ''), NULLIF(BTRIM(z.nature), '')) AS regulation_type,
                            z.geometrie AS zone_geom
                        FROM bdtopo_raw.zone_d_activite_ou_d_interet z
                    )
                    SELECT
                        r.road_id,
                        r.road_label,
                        r.road_nature,
                        z.zone_source,
                        z.zone_id,
                        z.zone_label,
                        z.regulation_type,
                        ST_Y(ST_PointOnSurface(ST_Intersection(r.road_geom, z.zone_geom))) AS feature_lat,
                        ST_X(ST_PointOnSurface(ST_Intersection(r.road_geom, z.zone_geom))) AS feature_lon,
                        ST_AsGeoJSON(
                            ST_SimplifyPreserveTopology(
                                ST_Intersection(r.road_geom, z.zone_geom),
                                0.00002
                            )
                        ) AS geom_geojson
                    FROM candidate_roads r
                    JOIN zones z
                      ON ST_Intersects(r.road_geom, z.zone_geom)
                    LIMIT %s
                    """,
                    (like_pattern, admin_pattern, admin_pattern, safe_limit),
                )
            )
            if rows:
                first = rows[0]
                if (
                    first.get("feature_lat") is not None
                    and first.get("feature_lon") is not None
                ):
                    coords = ToolCoordinates(
                        lat=float(first["feature_lat"]),
                        lon=float(first["feature_lon"]),
                    )
            summary = {
                "intersection_count": len(rows),
                "unique_roads": len(
                    {row.get("road_id") for row in rows if row.get("road_id")}
                ),
                "unique_zones": len(
                    {row.get("zone_id") for row in rows if row.get("zone_id")}
                ),
                "top_regulation_types": top_values(rows, "regulation_type"),
                "top_road_natures": top_values(rows, "road_nature"),
            }
            return ToolResponse(
                tool_name="bdtopo_intersection_tool",
                message=f"Found {len(rows)} intersections for roads matching '{road_name.strip()}'.",
                coordinates=coords,
                artifacts=build_map_artifacts(
                    title="BDTOPO intersections (road-name mode)",
                    coords=coords,
                    radius_m=None,
                    rows=rows,
                    fill_color=[156, 39, 176, 110],
                ),
                data={
                    "input_mode": "road_name",
                    "road_name": road_name.strip(),
                    "admin_hint": admin_hint,
                    "matches": rows,
                    "summary": summary,
                    "prompt_hints": [
                        "Disambiguate with admin_hint if too many road-name matches are returned.",
                        "Ask for nearest intersections if you can provide a reference point.",
                    ],
                },
                error=False,
            )

        return ToolResponse(
            tool_name="bdtopo_intersection_tool",
            message="Unsupported input_mode. Use one of: point, road_name.",
            error=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("bdtopo_intersection_tool failed: %s", exc)
        return ToolResponse(
            tool_name="bdtopo_intersection_tool",
            message=f"BDTOPO intersection query failed: {exc}",
            coordinates=coords,
            error=True,
        )
