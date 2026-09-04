"""BDTOPO spatial query tool backed by PostGIS curated views."""

from __future__ import annotations

from typing import Any

from config import get_config
from core.logger import get_logger
from modules.geospatial.bdtopo_common import (
    build_map_artifacts,
    distance_summary as _distance_summary,
    map_urls as _map_urls,
    normalize_rows as _normalize_rows,
    run_query as _run_query,
    top_values as _top_values,
)
from utils.contracts import BDTOPOQueryType, ToolArtifacts, ToolCoordinates, ToolResponse

logger = get_logger(__name__)

SUPPORTED_QUERY_TYPES = (
    "admin_lookup",
    "nearest_transport",
    "regulated_zones",
    "named_places",
)
PROMPT_TEMPLATES: dict[str, list[str]] = {
    "admin_lookup": [
        "At lat={lat}, lon={lon}, return commune name, INSEE code, population, and postal code.",
        "What administrative entity contains this point and what are its key demographics?",
    ],
    "nearest_transport": [
        "Find nearest road segments within {radius_m} m and include nature, lanes, speed, and restrictions.",
        "Around lat={lat}, lon={lon}, summarize transport by type and nearest distance.",
    ],
    "regulated_zones": [
        "Check regulated zones within {radius_m} m, returning type, category, and nearby names.",
        "Around this coordinate, list protected or zoned areas and distances.",
    ],
    "named_places": [
        "Find named places within {radius_m} m, including toponym, nature, and importance.",
        "What are the closest named places around this point and how far are they?",
    ],
}

def _prompt_hints(query_type: str, coords: ToolCoordinates, radius_m: int) -> list[str]:
    templates = PROMPT_TEMPLATES.get(query_type, [])
    return [
        template.format(lat=coords.lat, lon=coords.lon, radius_m=radius_m)
        for template in templates
    ]


def _geometry_select(include_geometry: bool, geom_expr: str) -> str:
    if not include_geometry:
        return "NULL::text AS geom_geojson"
    return f"ST_AsGeoJSON(ST_SimplifyPreserveTopology({geom_expr}, 0.00005)) AS geom_geojson"


def _artifacts_for_result(
    *,
    include_geometry: bool,
    title: str,
    coords: ToolCoordinates,
    radius_m: int | None,
    rows: list[dict[str, Any]],
) -> ToolArtifacts:
    if include_geometry:
        return build_map_artifacts(
            title=title,
            coords=coords,
            radius_m=radius_m,
            rows=rows,
        )
    return ToolArtifacts(maps=[], thumbnails=[], urls=_map_urls(coords))

def bdtopo_query_tool(
    query_type: BDTOPOQueryType,
    lat: float,
    lon: float,
    radius_m: int | None = None,
    limit: int = 5,
    include_geometry: bool = True,
) -> ToolResponse:
    """
    Query BDTOPO layers through curated PostGIS views for low-latency agent access.

    Args:
        query_type: One of:
          - admin_lookup
          - nearest_transport
          - regulated_zones
          - named_places
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.
        radius_m: Radius in meters for proximity/intersection filters.
        limit: Maximum number of rows to return (1-50).
        include_geometry: When false, skip GeoJSON generation and map layer artifacts.
    """
    config = get_config()
    safe_limit = min(max(int(limit or 5), 1), 50)
    effective_radius = int(
        radius_m if radius_m is not None else config.bdtopo_default_radius_m
    )
    coords = ToolCoordinates(lat=float(lat), lon=float(lon))

    try:
        if query_type == "admin_lookup":
            rows = _normalize_rows(
                _run_query(
                    """
                SELECT
                    v.source_table,
                    v.object_id,
                    COALESCE(
                        NULLIF(BTRIM(v.label), ''),
                        NULLIF(BTRIM(c.nom_officiel), ''),
                        NULLIF(BTRIM(c.code_insee), ''),
                        v.object_id
                    ) AS label,
                    c.nom_officiel,
                    c.code_insee,
                    c.population,
                    c.code_postal,
                    c.code_insee_du_departement AS departement_code,
                    c.code_insee_de_la_region AS region_code,
                    ST_Area(v.geom::geography) AS area_m2,
                    ST_Y(ST_PointOnSurface(v.geom)) AS feature_lat,
                    ST_X(ST_PointOnSurface(v.geom)) AS feature_lon,
                    {_geometry}
                FROM bdtopo_curated.mv_admin_latest v
                LEFT JOIN bdtopo_raw.commune c
                    ON v.source_table = 'commune'
                   AND c.cleabs = v.object_id
                WHERE ST_Intersects(
                    v.geom,
                    ST_SetSRID(ST_Point(%s, %s), 4326)
                )
                LIMIT 1
                """.format(_geometry=_geometry_select(include_geometry, "v.geom")),
                    (lon, lat),
                )
            )
            if not rows:
                return ToolResponse(
                    tool_name="bdtopo_query_tool",
                    message="No administrative entity found at this location.",
                    coordinates=coords,
                    artifacts=_artifacts_for_result(
                        include_geometry=include_geometry,
                        title=f"BDTOPO {query_type}",
                        coords=coords,
                        radius_m=effective_radius,
                        rows=[],
                    ),
                    data={
                        "query_type": query_type,
                        "radius_m": effective_radius,
                        "matches": [],
                        "supported_query_types": list(SUPPORTED_QUERY_TYPES),
                        "prompt_hints": _prompt_hints(
                            query_type, coords, effective_radius
                        ),
                    },
                    error=False,
                )
            first = rows[0]
            label = first.get("label") or first.get("object_id")
            insee_suffix = ""
            if first.get("code_insee"):
                insee_suffix = f" (INSEE {first.get('code_insee')})"
            return ToolResponse(
                tool_name="bdtopo_query_tool",
                message=f"Administrative match: {label}{insee_suffix}.",
                coordinates=coords,
                artifacts=_artifacts_for_result(
                    include_geometry=include_geometry,
                    title=f"BDTOPO {query_type}",
                    coords=coords,
                    radius_m=effective_radius,
                    rows=rows,
                ),
                data={
                    "query_type": query_type,
                    "radius_m": effective_radius,
                    "matches": rows,
                    "summary": {
                        "admin_name": first.get("nom_officiel") or first.get("label"),
                        "code_insee": first.get("code_insee"),
                        "population": first.get("population"),
                        "postal_code": first.get("code_postal"),
                        "area_m2": first.get("area_m2"),
                    },
                    "prompt_hints": _prompt_hints(query_type, coords, effective_radius),
                },
                error=False,
            )

        if query_type == "nearest_transport":
            rows = _normalize_rows(
                _run_query(
                    """
                SELECT
                    v.source_table,
                    v.object_id,
                    COALESCE(
                        NULLIF(BTRIM(v.label), ''),
                        NULLIF(BTRIM(t.nom_voie_ban_gauche), ''),
                        NULLIF(BTRIM(t.nom_voie_ban_droite), ''),
                        NULLIF(BTRIM(t.cpx_toponyme_route_nommee), ''),
                        v.object_id
                    ) AS label,
                    COALESCE(NULLIF(BTRIM(v.extra_value), ''), NULLIF(BTRIM(t.nature), '')) AS transport_nature,
                    t.importance,
                    t.nombre_de_voies,
                    t.vitesse_moyenne_vl,
                    t.sens_de_circulation,
                    t.restriction_de_hauteur,
                    t.restriction_de_poids_total,
                    t.restriction_de_largeur,
                    t.amenagement_cyclable_gauche,
                    t.amenagement_cyclable_droit,
                    ROUND(
                        ST_Distance(
                        v.geom::geography,
                        ST_SetSRID(ST_Point(%s, %s), 4326)::geography
                        )::numeric,
                        1
                    ) AS distance_m,
                    ST_Y(ST_PointOnSurface(v.geom)) AS feature_lat,
                    ST_X(ST_PointOnSurface(v.geom)) AS feature_lon,
                    {_geometry}
                FROM bdtopo_curated.mv_transport_latest v
                LEFT JOIN bdtopo_raw.troncon_de_route t
                    ON v.source_table = 'troncon_de_route'
                   AND t.cleabs = v.object_id
                WHERE ST_DWithin(
                    v.geom::geography,
                    ST_SetSRID(ST_Point(%s, %s), 4326)::geography,
                    %s
                )
                ORDER BY distance_m
                LIMIT %s
                """.format(_geometry=_geometry_select(include_geometry, "v.geom")),
                    (lon, lat, lon, lat, effective_radius, safe_limit),
                )
            )
            summary = _distance_summary(rows)
            summary["top_transport_types"] = _top_values(rows, "transport_nature")
            first = rows[0] if rows else None
            return ToolResponse(
                tool_name="bdtopo_query_tool",
                message=(
                    f"Found {len(rows)} nearby transport objects within {effective_radius} m."
                    + (
                        f" Nearest: {first.get('label')} ({first.get('distance_m')} m)."
                        if first
                        else ""
                    )
                ),
                coordinates=coords,
                artifacts=_artifacts_for_result(
                    include_geometry=include_geometry,
                    title=f"BDTOPO {query_type}",
                    coords=coords,
                    radius_m=effective_radius,
                    rows=rows,
                ),
                data={
                    "query_type": query_type,
                    "radius_m": effective_radius,
                    "matches": rows,
                    "summary": summary,
                    "prompt_hints": _prompt_hints(query_type, coords, effective_radius),
                },
                error=False,
            )

        if query_type == "regulated_zones":
            rows = _normalize_rows(
                _run_query(
                    """
                SELECT
                    v.source_table,
                    v.object_id,
                    COALESCE(
                        NULLIF(BTRIM(v.label), ''),
                        NULLIF(BTRIM(z.toponyme), ''),
                        NULLIF(BTRIM(p.toponyme), ''),
                        v.object_id
                    ) AS label,
                    COALESCE(
                        NULLIF(BTRIM(v.extra_value), ''),
                        NULLIF(BTRIM(z.nature_detaillee), ''),
                        NULLIF(BTRIM(z.nature), ''),
                        NULLIF(BTRIM(p.nature_detaillee), ''),
                        NULLIF(BTRIM(p.nature), '')
                    ) AS regulation_type,
                    z.categorie,
                    z.commune,
                    ROUND(
                        ST_Distance(
                            v.geom::geography,
                            ST_SetSRID(ST_Point(%s, %s), 4326)::geography
                        )::numeric,
                        1
                    ) AS distance_m,
                    ST_Y(ST_PointOnSurface(v.geom)) AS feature_lat,
                    ST_X(ST_PointOnSurface(v.geom)) AS feature_lon,
                    {_geometry}
                FROM bdtopo_curated.mv_regulated_latest v
                LEFT JOIN bdtopo_raw.zone_d_activite_ou_d_interet z
                    ON v.source_table = 'zone_d_activite_ou_d_interet'
                   AND z.cleabs = v.object_id
                LEFT JOIN bdtopo_raw.parc_ou_reserve p
                    ON v.source_table = 'parc_ou_reserve'
                   AND p.cleabs = v.object_id
                WHERE ST_DWithin(
                    v.geom::geography,
                    ST_SetSRID(ST_Point(%s, %s), 4326)::geography,
                    %s
                )
                ORDER BY distance_m
                LIMIT %s
                """.format(_geometry=_geometry_select(include_geometry, "v.geom")),
                    (lon, lat, lon, lat, effective_radius, safe_limit),
                )
            )
            used_fallback = False
            if not rows:
                used_fallback = True
                rows = _normalize_rows(
                    _run_query(
                        """
                        SELECT *
                        FROM (
                            SELECT
                                'parc_ou_reserve'::text AS source_table,
                                p.cleabs::text AS object_id,
                                COALESCE(NULLIF(BTRIM(p.toponyme), ''), p.cleabs) AS label,
                                COALESCE(NULLIF(BTRIM(p.nature_detaillee), ''), NULLIF(BTRIM(p.nature), '')) AS regulation_type,
                                NULL::text AS categorie,
                                NULL::text AS commune,
                                ROUND(
                                    ST_Distance(
                                        p.geometrie::geography,
                                        ST_SetSRID(ST_Point(%s, %s), 4326)::geography
                                    )::numeric,
                                    1
                                ) AS distance_m,
                                ST_Y(ST_PointOnSurface(p.geometrie)) AS feature_lat,
                                ST_X(ST_PointOnSurface(p.geometrie)) AS feature_lon,
                                {_park_geometry}
                            FROM bdtopo_raw.parc_ou_reserve p
                            WHERE ST_DWithin(
                                p.geometrie::geography,
                                ST_SetSRID(ST_Point(%s, %s), 4326)::geography,
                                %s
                            )
                            UNION ALL
                            SELECT
                                'zone_d_activite_ou_d_interet'::text AS source_table,
                                z.cleabs::text AS object_id,
                                COALESCE(NULLIF(BTRIM(z.toponyme), ''), z.cleabs) AS label,
                                COALESCE(NULLIF(BTRIM(z.nature_detaillee), ''), NULLIF(BTRIM(z.nature), '')) AS regulation_type,
                                z.categorie::text AS categorie,
                                z.commune::text AS commune,
                                ROUND(
                                    ST_Distance(
                                        z.geometrie::geography,
                                        ST_SetSRID(ST_Point(%s, %s), 4326)::geography
                                    )::numeric,
                                    1
                                ) AS distance_m,
                                ST_Y(ST_PointOnSurface(z.geometrie)) AS feature_lat,
                                ST_X(ST_PointOnSurface(z.geometrie)) AS feature_lon,
                                {_zone_geometry}
                            FROM bdtopo_raw.zone_d_activite_ou_d_interet z
                            WHERE ST_DWithin(
                                z.geometrie::geography,
                                ST_SetSRID(ST_Point(%s, %s), 4326)::geography,
                                %s
                            )
                        ) fallback
                        ORDER BY distance_m
                        LIMIT %s
                        """.format(
                            _park_geometry=_geometry_select(
                                include_geometry, "p.geometrie"
                            ),
                            _zone_geometry=_geometry_select(
                                include_geometry, "z.geometrie"
                            ),
                        ),
                        (
                            lon,
                            lat,
                            lon,
                            lat,
                            effective_radius,
                            lon,
                            lat,
                            lon,
                            lat,
                            effective_radius,
                            safe_limit,
                        ),
                    )
                )
            summary = _distance_summary(rows)
            summary["top_regulation_types"] = _top_values(rows, "regulation_type")
            return ToolResponse(
                tool_name="bdtopo_query_tool",
                message=(
                    f"Found {len(rows)} regulated zones within {effective_radius} m."
                    + (
                        " Used fallback regulated/zoning tables."
                        if used_fallback
                        else ""
                    )
                ),
                coordinates=coords,
                artifacts=_artifacts_for_result(
                    include_geometry=include_geometry,
                    title=f"BDTOPO {query_type}",
                    coords=coords,
                    radius_m=effective_radius,
                    rows=rows,
                ),
                data={
                    "query_type": query_type,
                    "radius_m": effective_radius,
                    "matches": rows,
                    "summary": summary,
                    "fallback_used": used_fallback,
                    "prompt_hints": _prompt_hints(query_type, coords, effective_radius),
                },
                error=False,
            )

        if query_type == "named_places":
            rows = _normalize_rows(
                _run_query(
                    """
                SELECT *
                FROM (
                    SELECT
                        v.source_table,
                        v.object_id,
                        COALESCE(
                            NULLIF(BTRIM(v.label), ''),
                            NULLIF(BTRIM(p.toponyme), ''),
                            v.object_id
                        ) AS label,
                        p.nature AS place_nature,
                        p.importance::text AS place_importance,
                        p.statut_du_toponyme,
                        p.insee_commune,
                        ROUND(
                            ST_Distance(
                                v.geom::geography,
                                ST_SetSRID(ST_Point(%s, %s), 4326)::geography
                            )::numeric,
                            1
                        ) AS distance_m,
                        ST_Y(ST_PointOnSurface(v.geom)) AS feature_lat,
                        ST_X(ST_PointOnSurface(v.geom)) AS feature_lon,
                        {_places_geometry}
                    FROM bdtopo_curated.mv_places_latest v
                    LEFT JOIN bdtopo_raw.lieu_dit_non_habite p
                        ON v.source_table = 'lieu_dit_non_habite'
                       AND p.cleabs = v.object_id
                    WHERE ST_DWithin(
                        v.geom::geography,
                        ST_SetSRID(ST_Point(%s, %s), 4326)::geography,
                        %s
                    )
                    UNION ALL
                    SELECT
                        'toponymie'::text AS source_table,
                        t.cleabs_de_l_objet::text AS object_id,
                        COALESCE(NULLIF(BTRIM(t.graphie_du_toponyme), ''), t.cleabs_de_l_objet::text) AS label,
                        t.nature_de_l_objet::text AS place_nature,
                        NULL::text AS place_importance,
                        t.statut_du_toponyme::text AS statut_du_toponyme,
                        NULL::text AS insee_commune,
                        ROUND(
                            ST_Distance(
                                t.geometrie::geography,
                                ST_SetSRID(ST_Point(%s, %s), 4326)::geography
                            )::numeric,
                            1
                        ) AS distance_m,
                        ST_Y(ST_PointOnSurface(t.geometrie)) AS feature_lat,
                        ST_X(ST_PointOnSurface(t.geometrie)) AS feature_lon,
                        {_toponymy_geometry}
                    FROM bdtopo_raw.toponymie t
                    WHERE ST_DWithin(
                        t.geometrie::geography,
                        ST_SetSRID(ST_Point(%s, %s), 4326)::geography,
                        %s
                    )
                ) places
                ORDER BY distance_m
                LIMIT %s
                """.format(
                    _places_geometry=_geometry_select(include_geometry, "v.geom"),
                    _toponymy_geometry=_geometry_select(
                        include_geometry, "t.geometrie"
                    ),
                ),
                    (
                        lon,
                        lat,
                        lon,
                        lat,
                        effective_radius,
                        lon,
                        lat,
                        lon,
                        lat,
                        effective_radius,
                        safe_limit,
                    ),
                )
            )
            summary = _distance_summary(rows)
            summary["top_place_natures"] = _top_values(rows, "place_nature")
            return ToolResponse(
                tool_name="bdtopo_query_tool",
                message=f"Found {len(rows)} named places within {effective_radius} m.",
                coordinates=coords,
                artifacts=_artifacts_for_result(
                    include_geometry=include_geometry,
                    title=f"BDTOPO {query_type}",
                    coords=coords,
                    radius_m=effective_radius,
                    rows=rows,
                ),
                data={
                    "query_type": query_type,
                    "radius_m": effective_radius,
                    "matches": rows,
                    "summary": summary,
                    "prompt_hints": _prompt_hints(query_type, coords, effective_radius),
                },
                error=False,
            )

        return ToolResponse(
            tool_name="bdtopo_query_tool",
            message=(
                "Unsupported query_type. Use one of: "
                "admin_lookup, nearest_transport, regulated_zones, named_places."
            ),
            coordinates=coords,
            data={
                "query_type": query_type,
                "supported_query_types": list(SUPPORTED_QUERY_TYPES),
                "include_geometry": include_geometry,
                "prompt_hints": _prompt_hints("admin_lookup", coords, effective_radius),
            },
            error=True,
        )
    except Exception as exc:  # noqa: BLE001 - tool-level guardrail
        logger.error("bdtopo_query_tool failed: %s", exc)
        return ToolResponse(
            tool_name="bdtopo_query_tool",
            message=f"BDTOPO query failed: {exc}",
            coordinates=coords,
            data={
                "query_type": query_type,
                "supported_query_types": list(SUPPORTED_QUERY_TYPES),
                "include_geometry": include_geometry,
                "prompt_hints": _prompt_hints(
                    query_type
                    if query_type in SUPPORTED_QUERY_TYPES
                    else "admin_lookup",
                    coords,
                    effective_radius,
                ),
            },
            error=True,
        )
