"""BDTOPO thematic explanation tool."""

from __future__ import annotations

from typing import Any

import psycopg.sql

from core.logger import get_logger
from modules.geospatial.bdtopo_common import (
    SafeQuery,
    area_filter,
    build_map_artifacts,
    normalize_rows,
    resolve_area_context,
    run_query,
)
from utils.bbox_service import LocationAmbiguousError
from utils.contracts import (
    BDTOPOAreaInputMode,
    BDTOPOExplainObjective,
    ToolResponse,
)

logger = get_logger(__name__)

def _scalar(sql_query: SafeQuery, params: tuple[Any, ...]) -> float:
    rows = run_query(sql_query, params)
    if not rows:
        return 0.0
    value = rows[0].get("value")
    if value is None:
        return 0.0
    return float(value)

def bdtopo_thematic_explain_tool(
    objective: BDTOPOExplainObjective = "site_screening",
    input_mode: BDTOPOAreaInputMode = "point",
    lat: float | None = None,
    lon: float | None = None,
    radius_m: int = 3000,
    place_name: str | None = None,
    bbox: list[float] | None = None,
) -> ToolResponse:
    """
    Build an evidence-based explanation from BDTOPO signals.

    objective:
      - site_screening
      - mobility_risk
      - compliance
      - general
    """
    try:
        context = resolve_area_context(
            input_mode=input_mode,
            lat=lat,
            lon=lon,
            radius_m=radius_m,
            place_name=place_name,
            bbox=bbox,
        )
    except LocationAmbiguousError as exc:
        return ToolResponse(
            tool_name="bdtopo_thematic_explain_tool",
            message=f"I found multiple matches for '{exc.query}'. Please confirm the correct location.",
            city=place_name,
            data={
                "needs_location_confirmation": True,
                "location_query": exc.query,
                "candidates": exc.candidates,
                "resume_patch": {"field": "place_name"},
            },
            error=False,
        )
    except Exception as exc:
        return ToolResponse(
            tool_name="bdtopo_thematic_explain_tool",
            message=f"Invalid spatial input: {exc}",
            error=True,
        )

    coords = context["coords"]
    where_sql, where_params = area_filter(geom_col="geometrie", context=context)

    if context["mode"] == "bbox":
        admin_rows = normalize_rows(
            run_query(
                psycopg.sql.SQL(
                    """
                    SELECT nom_officiel, code_insee, population, code_postal
                    FROM bdtopo_raw.commune
                    WHERE {where}
                    ORDER BY population DESC NULLS LAST
                    LIMIT 1
                    """
                ).format(where=where_sql),
                where_params,
            )
        )
    else:
        admin_rows = normalize_rows(
            run_query(
                """
                SELECT nom_officiel, code_insee, population, code_postal
                FROM bdtopo_raw.commune
                WHERE ST_Contains(geometrie, ST_SetSRID(ST_Point(%s, %s), 4326))
                LIMIT 1
                """,
                (coords.lon, coords.lat),
            )
        )

    transport_count = _scalar(
        psycopg.sql.SQL(
            """
            SELECT COUNT(*) AS value
            FROM bdtopo_raw.troncon_de_route
            WHERE {where}
            """
        ).format(where=where_sql),
        where_params,
    )
    regulated_count = _scalar(
        psycopg.sql.SQL(
            """
            SELECT SUM(cnt)::float AS value
            FROM (
                SELECT COUNT(*) AS cnt
                FROM bdtopo_raw.parc_ou_reserve
                WHERE {where}
                UNION ALL
                SELECT COUNT(*) AS cnt
                FROM bdtopo_raw.zone_d_activite_ou_d_interet
                WHERE {where}
            ) q
            """
        ).format(where=where_sql),
        where_params + where_params,
    )
    named_places_count = _scalar(
        psycopg.sql.SQL(
            """
            SELECT COUNT(*) AS value
            FROM bdtopo_raw.lieu_dit_non_habite
            WHERE {where}
            """
        ).format(where=where_sql),
        where_params,
    )
    hydro_count = _scalar(
        psycopg.sql.SQL(
            """
            SELECT SUM(cnt)::float AS value
            FROM (
                SELECT COUNT(*) AS cnt
                FROM bdtopo_raw.troncon_hydrographique
                WHERE {where}
                UNION ALL
                SELECT COUNT(*) AS cnt
                FROM bdtopo_raw.surface_hydrographique
                WHERE {where}
            ) q
            """
        ).format(where=where_sql),
        where_params + where_params,
    )

    admin = admin_rows[0] if admin_rows else {}
    evidence = [
        {
            "signal": "administrative_context",
            "value": admin.get("nom_officiel"),
            "details": {
                "code_insee": admin.get("code_insee"),
                "population": admin.get("population"),
                "postal_code": admin.get("code_postal"),
            },
            "source": "bdtopo_raw.commune",
        },
        {
            "signal": "transport_presence",
            "value": int(transport_count),
            "details": {"radius_m": context["radius_m"]},
            "source": "bdtopo_raw.troncon_de_route",
        },
        {
            "signal": "regulated_constraints",
            "value": int(regulated_count),
            "details": {"radius_m": context["radius_m"]},
            "source": "bdtopo_raw.parc_ou_reserve + bdtopo_raw.zone_d_activite_ou_d_interet",
        },
        {
            "signal": "named_place_density",
            "value": int(named_places_count),
            "details": {"radius_m": context["radius_m"]},
            "source": "bdtopo_raw.lieu_dit_non_habite",
        },
        {
            "signal": "hydro_context",
            "value": int(hydro_count),
            "details": {"radius_m": context["radius_m"]},
            "source": "bdtopo_raw.troncon_hydrographique + bdtopo_raw.surface_hydrographique",
        },
    ]

    interpretations: list[str] = []
    if objective == "mobility_risk":
        interpretations.append(
            f"Transport density is {int(transport_count)} feature(s), suggesting {'high' if transport_count > 200 else 'moderate/low'} network intensity."
        )
        interpretations.append(
            f"Regulated constraints count is {int(regulated_count)}, relevant for access and route compliance."
        )
    elif objective == "compliance":
        interpretations.append(
            f"Regulated/zoning features in scope: {int(regulated_count)}; this is the primary compliance signal."
        )
        interpretations.append(
            f"Administrative anchor: {admin.get('nom_officiel') or 'unknown'} (INSEE {admin.get('code_insee') or 'n/a'})."
        )
    elif objective == "site_screening":
        interpretations.append(
            f"Screening profile combines {int(transport_count)} transport features and {int(regulated_count)} regulated features."
        )
        interpretations.append(
            f"Named-place density is {int(named_places_count)} and hydro context count is {int(hydro_count)}."
        )
    else:
        interpretations.append(
            f"General context: transport={int(transport_count)}, regulated={int(regulated_count)}, named_places={int(named_places_count)}, hydro={int(hydro_count)}."
        )

    score = 50
    score += min(int(transport_count // 25), 20)
    score -= min(int(regulated_count // 10), 25)
    score -= min(int(hydro_count // 20), 15)
    screening_score = max(0, min(100, score))

    return ToolResponse(
        tool_name="bdtopo_thematic_explain_tool",
        message=f"Thematic explanation generated for objective '{objective}'.",
        coordinates=coords,
        city=context.get("place_label") or place_name,
        artifacts=build_map_artifacts(
            title=f"BDTOPO thematic explain ({objective})",
            coords=coords,
            radius_m=context["radius_m"] if context["mode"] == "point" else None,
            rows=[],
            bbox=context.get("bbox"),
            fill_color=[3, 169, 244, 80],
        ),
        data={
            "objective": objective,
            "input_mode": "point"
            if context["mode"] == "point"
            else ("place_name" if place_name else "bbox"),
            "radius_m": context["radius_m"],
            "bbox": context.get("bbox"),
            "evidence": evidence,
            "interpretation": interpretations,
            "summary": {
                "screening_score_0_100": screening_score,
                "transport_count": int(transport_count),
                "regulated_count": int(regulated_count),
                "named_places_count": int(named_places_count),
                "hydro_count": int(hydro_count),
            },
            "prompt_hints": [
                "Ask for change_snapshot to compare this explanation across editions.",
                "Ask for intersection checks if regulated_count is high and roads are involved.",
            ],
        },
        error=False,
    )
