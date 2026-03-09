"""BDTOPO coverage and quality diagnostics."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg.sql

from core.logger import get_logger
from mcp_singleton import mcp
from tools.bdtopo_common import (
    area_filter,
    build_map_artifacts,
    normalize_rows,
    qualified_identifier,
    resolve_area_context,
    run_query,
)
from utils.bbox_service import LocationAmbiguousError
from utils.contracts import BDTOPOAreaInputMode, ToolResponse

logger = get_logger(__name__)


@dataclass(frozen=True)
class CoverageSpec:
    key: str
    source: str
    geom_col: str
    label_expr: str


COVERAGE_SPECS: tuple[CoverageSpec, ...] = (
    CoverageSpec("administratif", "bdtopo_raw.commune", "geometrie", "nom_officiel"),
    CoverageSpec(
        "transport", "bdtopo_raw.troncon_de_route", "geometrie", "nom_voie_ban_gauche"
    ),
    CoverageSpec(
        "regulated_areas", "bdtopo_raw.parc_ou_reserve", "geometrie", "toponyme"
    ),
    CoverageSpec(
        "activity_zones",
        "bdtopo_raw.zone_d_activite_ou_d_interet",
        "geometrie",
        "toponyme",
    ),
    CoverageSpec(
        "named_places", "bdtopo_raw.lieu_dit_non_habite", "geometrie", "toponyme"
    ),
    CoverageSpec(
        "toponymy", "bdtopo_raw.toponymie", "geometrie", "graphie_du_toponyme"
    ),
    CoverageSpec("buildings", "bdtopo_raw.batiment", "geometrie", "cleabs"),
    CoverageSpec(
        "land_use_vegetation", "bdtopo_raw.zone_de_vegetation", "geometrie", "nature"
    ),
    CoverageSpec(
        "land_use_habitation", "bdtopo_raw.zone_d_habitation", "geometrie", "toponyme"
    ),
    CoverageSpec(
        "hydro_line", "bdtopo_raw.troncon_hydrographique", "geometrie", "nature"
    ),
    CoverageSpec(
        "hydro_surface", "bdtopo_raw.surface_hydrographique", "geometrie", "nature"
    ),
)


def _coverage_query(
    *, spec: CoverageSpec, context: dict
) -> tuple[psycopg.sql.Composed, tuple]:
    source = qualified_identifier(spec.source)
    label = qualified_identifier(spec.label_expr)
    where_sql, where_params = area_filter(geom_col=spec.geom_col, context=context)

    return (
        psycopg.sql.SQL(
            """
            SELECT
                %s AS metric_key,
                %s AS source,
                COUNT(*) AS feature_count,
                COUNT(*) FILTER (
                    WHERE NULLIF(BTRIM(COALESCE({label}::text, '')), '') IS NOT NULL
                ) AS named_count
            FROM {source}
            WHERE {where}
            """
        ).format(source=source, label=label, where=where_sql),
        (spec.key, spec.source) + where_params,
    )


@mcp.tool()
def bdtopo_coverage_quality_tool(
    input_mode: BDTOPOAreaInputMode = "point",
    lat: float | None = None,
    lon: float | None = None,
    radius_m: int = 5000,
    place_name: str | None = None,
    bbox: list[float] | None = None,
) -> ToolResponse:
    """Run coverage/quality diagnostics over a point radius, place name, or bbox."""
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
            tool_name="bdtopo_coverage_quality_tool",
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
            tool_name="bdtopo_coverage_quality_tool",
            message=f"Invalid spatial input: {exc}",
            error=True,
        )

    rows: list[dict] = []
    for spec in COVERAGE_SPECS:
        sql_query, params = _coverage_query(spec=spec, context=context)
        result = normalize_rows(run_query(sql_query, params))
        if result:
            rows.append(result[0])

    total_features = int(sum(int(row.get("feature_count") or 0) for row in rows))
    themes_with_data = [
        row["metric_key"] for row in rows if int(row.get("feature_count") or 0) > 0
    ]
    sparse_themes = [
        row["metric_key"] for row in rows if int(row.get("feature_count") or 0) == 0
    ]

    for row in rows:
        count = int(row.get("feature_count") or 0)
        named = int(row.get("named_count") or 0)
        row["named_ratio"] = round((named / count), 4) if count else 0.0

    coords = context["coords"]
    response_city = context.get("place_label") or place_name
    return ToolResponse(
        tool_name="bdtopo_coverage_quality_tool",
        message=(
            f"Coverage quality computed over {len(rows)} indicators."
            f" {len(themes_with_data)} indicators contain data."
        ),
        city=response_city,
        coordinates=coords,
        artifacts=build_map_artifacts(
            title="BDTOPO coverage quality area",
            coords=coords,
            radius_m=context["radius_m"] if context["mode"] == "point" else None,
            rows=[],
            bbox=context.get("bbox"),
            fill_color=[76, 175, 80, 80],
        ),
        data={
            "input_mode": "point"
            if context["mode"] == "point"
            else ("place_name" if place_name else "bbox"),
            "radius_m": context["radius_m"],
            "bbox": context.get("bbox"),
            "total_features": total_features,
            "indicators": rows,
            "themes_with_data": themes_with_data,
            "themes_without_data": sparse_themes,
            "prompt_hints": [
                "Ask for the top sparse indicators to prioritize ingestion improvements.",
                "Compare the same area across two editions with bdtopo_change_snapshot_tool.",
            ],
        },
        error=False,
    )
