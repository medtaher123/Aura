"""BDTOPO cross-edition change snapshot tool."""

from __future__ import annotations

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

TRACKED_TABLES: tuple[tuple[str, str], ...] = (
    ("bdtopo_raw.commune", "geometrie"),
    ("bdtopo_raw.troncon_de_route", "geometrie"),
    ("bdtopo_raw.lieu_dit_non_habite", "geometrie"),
    ("bdtopo_raw.zone_d_activite_ou_d_interet", "geometrie"),
    ("bdtopo_raw.parc_ou_reserve", "geometrie"),
    ("bdtopo_raw.batiment", "geometrie"),
)


def _edition_exists(edition: str) -> bool:
    rows = run_query(
        """
        SELECT 1
        FROM bdtopo_meta.ingestion_log
        WHERE edition_date::text = %s
        LIMIT 1
        """,
        (edition,),
    )
    return bool(rows)


def _count_for_table(
    *,
    table_name: str,
    geom_col: str,
    edition: str,
    context: dict,
) -> int:
    table = qualified_identifier(table_name)
    where_sql, where_params = area_filter(geom_col=geom_col, context=context)

    rows = run_query(
        psycopg.sql.SQL(
            """
            SELECT COUNT(*) AS feature_count
            FROM {table}
            WHERE edition_date::text = %s
              AND {where}
            """
        ).format(table=table, where=where_sql),
        (edition,) + where_params,
    )
    return int(rows[0]["feature_count"]) if rows else 0


@mcp.tool()
def bdtopo_change_snapshot_tool(
    baseline_edition: str,
    target_edition: str,
    input_mode: BDTOPOAreaInputMode = "point",
    lat: float | None = None,
    lon: float | None = None,
    radius_m: int = 5000,
    place_name: str | None = None,
    bbox: list[float] | None = None,
) -> ToolResponse:
    """Compare BDTOPO coverage counts between two editions on a spatial extent."""
    tool_name = "bdtopo_change_snapshot_tool"
    if not baseline_edition or not target_edition:
        return ToolResponse(
            tool_name=tool_name,
            message="baseline_edition and target_edition are required.",
            error=True,
        )
    if baseline_edition == target_edition:
        return ToolResponse(
            tool_name=tool_name,
            message="baseline_edition and target_edition must be different.",
            error=True,
        )

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
            tool_name=tool_name,
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
            tool_name=tool_name,
            message=f"Invalid spatial input: {exc}",
            error=True,
        )

    if not _edition_exists(baseline_edition) or not _edition_exists(target_edition):
        available = normalize_rows(
            run_query(
                "SELECT DISTINCT edition_date::text AS edition FROM bdtopo_meta.ingestion_log ORDER BY edition",
                (),
            )
        )
        return ToolResponse(
            tool_name=tool_name,
            message="One or both requested editions are not loaded in bdtopo_meta.ingestion_log.",
            data={
                "baseline_edition": baseline_edition,
                "target_edition": target_edition,
                "available_editions": [row["edition"] for row in available],
            },
            error=True,
        )

    per_table: list[dict] = []
    for table_name, geom_col in TRACKED_TABLES:
        baseline_count = _count_for_table(
            table_name=table_name,
            geom_col=geom_col,
            edition=baseline_edition,
            context=context,
        )
        target_count = _count_for_table(
            table_name=table_name,
            geom_col=geom_col,
            edition=target_edition,
            context=context,
        )
        per_table.append(
            {
                "table": table_name,
                "baseline_count": baseline_count,
                "target_count": target_count,
                "delta": target_count - baseline_count,
            }
        )

    total_baseline = sum(item["baseline_count"] for item in per_table)
    total_target = sum(item["target_count"] for item in per_table)
    delta_total = total_target - total_baseline

    coords = context["coords"]
    return ToolResponse(
        tool_name=tool_name,
        message=(
            f"Change snapshot computed for {baseline_edition} -> {target_edition}."
            f" Global delta: {delta_total:+d} features."
        ),
        coordinates=coords,
        city=context.get("place_label") or place_name,
        artifacts=build_map_artifacts(
            title=f"BDTOPO change area {baseline_edition} -> {target_edition}",
            coords=coords,
            radius_m=context["radius_m"] if context["mode"] == "point" else None,
            rows=[],
            bbox=context.get("bbox"),
            fill_color=[255, 193, 7, 80],
        ),
        data={
            "baseline_edition": baseline_edition,
            "target_edition": target_edition,
            "input_mode": "point"
            if context["mode"] == "point"
            else ("place_name" if place_name else "bbox"),
            "radius_m": context["radius_m"],
            "bbox": context.get("bbox"),
            "tables": per_table,
            "summary": {
                "baseline_total": total_baseline,
                "target_total": total_target,
                "delta_total": delta_total,
                "most_increased_table": max(per_table, key=lambda item: item["delta"])[
                    "table"
                ]
                if per_table
                else None,
                "most_decreased_table": min(per_table, key=lambda item: item["delta"])[
                    "table"
                ]
                if per_table
                else None,
            },
            "prompt_hints": [
                "Ask for per-table deltas to understand which themes changed most.",
                "Run coverage quality on both editions to diagnose sparse themes.",
            ],
        },
        error=False,
    )
