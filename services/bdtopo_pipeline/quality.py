"""Data quality checks and lightweight observability reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json

import psycopg
from psycopg import sql

from .config import PipelineConfig


@dataclass(slots=True)
class TableQuality:
    table_name: str
    row_count: int
    invalid_geometry_count: int
    invalid_ratio: float


@dataclass(slots=True)
class QualityReport:
    ok: bool
    threshold: float
    tables_checked: int
    failing_tables: list[str]
    table_metrics: list[TableQuality]


def _list_geometry_tables(connection: psycopg.Connection) -> list[tuple[str, str]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT f_table_name, f_geometry_column
            FROM public.geometry_columns
            WHERE f_table_schema = 'bdtopo_raw'
            ORDER BY f_table_name
            """
        )
        return [(row[0], row[1]) for row in cursor.fetchall()]


def run_quality_checks(config: PipelineConfig) -> QualityReport:
    if not config.postgis_dsn:
        raise ValueError("BDTOPO_DATABASE_URL is required to run quality checks.")

    table_metrics: list[TableQuality] = []
    failing_tables: list[str] = []

    with psycopg.connect(config.postgis_dsn, autocommit=False) as connection:
        for table_name, geometry_column in _list_geometry_tables(connection):
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("SELECT COUNT(*) FROM bdtopo_raw.{table}").format(
                        table=sql.Identifier(table_name)
                    )
                )
                row_count = int(cursor.fetchone()[0])
                cursor.execute(
                    sql.SQL(
                        """
                        SELECT COUNT(*)
                        FROM bdtopo_raw.{table}
                        WHERE {geom} IS NOT NULL
                          AND NOT ST_IsValid({geom})
                        """
                    ).format(
                        table=sql.Identifier(table_name),
                        geom=sql.Identifier(geometry_column),
                    )
                )
                invalid_count = int(cursor.fetchone()[0])

            ratio = (invalid_count / row_count) if row_count else 0.0
            metric = TableQuality(
                table_name=table_name,
                row_count=row_count,
                invalid_geometry_count=invalid_count,
                invalid_ratio=ratio,
            )
            table_metrics.append(metric)
            if ratio > config.quality_invalid_ratio_threshold:
                failing_tables.append(table_name)

    report = QualityReport(
        ok=not failing_tables,
        threshold=config.quality_invalid_ratio_threshold,
        tables_checked=len(table_metrics),
        failing_tables=failing_tables,
        table_metrics=table_metrics,
    )

    config.report_dir.mkdir(parents=True, exist_ok=True)
    output_file = config.report_dir / "quality_report.json"
    payload = {
        "ok": report.ok,
        "threshold": report.threshold,
        "tables_checked": report.tables_checked,
        "failing_tables": report.failing_tables,
        "table_metrics": [asdict(metric) for metric in report.table_metrics],
    }
    output_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return report

