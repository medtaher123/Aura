"""Post-load optimization: indexes and curated materialized views."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from psycopg import sql
from tqdm import tqdm

from .config import PipelineConfig
from .logger import get_logger

logger = get_logger("optimizer")


@dataclass(slots=True)
class OptimizationSummary:
    indexed_tables: int
    curated_views: list[str]


def _list_raw_tables(connection: psycopg.Connection) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'bdtopo_raw'
            ORDER BY table_name
            """
        )
        return [row[0] for row in cursor.fetchall()]


def _find_geometry_column(connection: psycopg.Connection, table_name: str) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT f_geometry_column
            FROM public.geometry_columns
            WHERE f_table_schema = 'bdtopo_raw'
              AND f_table_name = %s
            LIMIT 1
            """,
            (table_name,),
        )
        row = cursor.fetchone()
    return row[0] if row else None


def _pick_column(connection: psycopg.Connection, table_name: str, candidates: tuple[str, ...]) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'bdtopo_raw'
              AND table_name = %s
            """,
            (table_name,),
        )
        columns = {row[0].lower(): row[0] for row in cursor.fetchall()}
    for candidate in candidates:
        if candidate in columns:
            return columns[candidate]
    return None


def _pick_table(tables: list[str], preferred_keywords: tuple[str, ...]) -> str | None:
    for table in tables:
        if all(keyword in table for keyword in preferred_keywords):
            return table
    return None


def _create_or_replace_view(
    connection: psycopg.Connection,
    *,
    view_name: str,
    source_table: str | None,
    geometry_column: str | None,
    object_id_column: str | None,
    label_column: str | None,
    extra_column: str | None = None,
    extra_alias: str | None = None,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("DROP MATERIALIZED VIEW IF EXISTS bdtopo_curated.{view}").format(
            view=sql.Identifier(view_name)
        ))

        if not source_table or not geometry_column:
            cursor.execute(
                sql.SQL(
                    """
                    CREATE MATERIALIZED VIEW bdtopo_curated.{view} AS
                    SELECT
                        NULL::text AS source_table,
                        NULL::text AS object_id,
                        NULL::text AS label,
                        NULL::text AS extra_value,
                        NULL::geometry AS geom
                    WHERE FALSE
                    """
                ).format(view=sql.Identifier(view_name))
            )
            return

        object_expr = (
            sql.Identifier(object_id_column)
            if object_id_column
            else sql.SQL("'unknown'")
        )
        label_expr = (
            sql.Identifier(label_column)
            if label_column
            else sql.SQL("NULL")
        )
        if extra_column:
            extra_expr = sql.Identifier(extra_column)
        else:
            extra_expr = sql.SQL("NULL")

        cursor.execute(
            sql.SQL(
                """
                CREATE MATERIALIZED VIEW bdtopo_curated.{view} AS
                SELECT
                    {source_lit}::text AS source_table,
                    {object_id}::text AS object_id,
                    {label}::text AS label,
                    {extra}::text AS extra_value,
                    ST_Transform({geom}, 4326) AS geom
                FROM bdtopo_raw.{source}
                WHERE {geom} IS NOT NULL
                """
            ).format(
                view=sql.Identifier(view_name),
                source=sql.Identifier(source_table),
                source_lit=sql.Literal(source_table),
                geom=sql.Identifier(geometry_column),
                object_id=object_expr,
                label=label_expr,
                extra=extra_expr,
            ),
        )

        if extra_alias:
            cursor.execute(
                sql.SQL(
                    "COMMENT ON MATERIALIZED VIEW bdtopo_curated.{view} IS {comment}"
                ).format(
                    view=sql.Identifier(view_name),
                    comment=sql.Literal(f"extra_value column semantics: {extra_alias}"),
                ),
            )


def optimize_postgis(config: PipelineConfig) -> OptimizationSummary:
    if not config.database_url:
        raise ValueError("BDTOPO_DATABASE_URL is required for optimization.")

    with psycopg.connect(config.database_url, autocommit=False) as connection:
        with connection.cursor() as cursor:
            cursor.execute("CREATE SCHEMA IF NOT EXISTS bdtopo_curated")

        tables = _list_raw_tables(connection)
        indexed_tables = 0
        logger.info(f"Indexing {len(tables)} raw tables")
        for table_name in tqdm(tables, desc="Indexing", unit="table"):
            geometry_column = _find_geometry_column(connection, table_name)
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE INDEX IF NOT EXISTS {idx}
                        ON bdtopo_raw.{table} (edition_date, theme)
                        """
                    ).format(
                        idx=sql.Identifier(f"idx_{table_name}_edition_theme"),
                        table=sql.Identifier(table_name),
                    )
                )
                if geometry_column:
                    cursor.execute(
                        sql.SQL(
                            """
                            CREATE INDEX IF NOT EXISTS {idx}
                            ON bdtopo_raw.{table}
                            USING GIST ({geom})
                            """
                        ).format(
                            idx=sql.Identifier(f"idx_{table_name}_{geometry_column}_gist"),
                            table=sql.Identifier(table_name),
                            geom=sql.Identifier(geometry_column),
                        )
                    )
                    indexed_tables += 1

        logger.info(f"Analyzing {len(tables)} tables")
        for table_name in tqdm(tables, desc="Analyzing", unit="table"):
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("ANALYZE bdtopo_raw.{t}").format(
                    t=sql.Identifier(table_name)
                ))

        logger.info("Building curated materialized views")
        admin_table = _pick_table(tables, ("commune",)) or _pick_table(tables, ("admin",))
        transport_table = _pick_table(tables, ("troncon", "route")) or _pick_table(tables, ("route",))
        regulated_table = _pick_table(tables, ("zone", "reglement")) or _pick_table(tables, ("servitude",))
        places_table = _pick_table(tables, ("toponyme",)) or _pick_table(tables, ("lieu",))

        _create_or_replace_view(
            connection,
            view_name="mv_admin_latest",
            source_table=admin_table,
            geometry_column=_find_geometry_column(connection, admin_table) if admin_table else None,
            object_id_column=_pick_column(connection, admin_table, ("cleabs", "id", "objectid", "gid")) if admin_table else None,
            label_column=_pick_column(connection, admin_table, ("nom", "nom_com", "libelle")) if admin_table else None,
        )
        _create_or_replace_view(
            connection,
            view_name="mv_transport_latest",
            source_table=transport_table,
            geometry_column=_find_geometry_column(connection, transport_table) if transport_table else None,
            object_id_column=_pick_column(connection, transport_table, ("cleabs", "id", "objectid", "gid")) if transport_table else None,
            label_column=_pick_column(connection, transport_table, ("nom", "nom_voie", "libelle")) if transport_table else None,
            extra_column=_pick_column(connection, transport_table, ("nature", "classement", "typevoie")) if transport_table else None,
            extra_alias="transport_nature",
        )
        _create_or_replace_view(
            connection,
            view_name="mv_regulated_latest",
            source_table=regulated_table,
            geometry_column=_find_geometry_column(connection, regulated_table) if regulated_table else None,
            object_id_column=_pick_column(connection, regulated_table, ("cleabs", "id", "objectid", "gid")) if regulated_table else None,
            label_column=_pick_column(connection, regulated_table, ("nom", "libelle")) if regulated_table else None,
            extra_column=_pick_column(connection, regulated_table, ("typezone", "nature", "type")) if regulated_table else None,
            extra_alias="regulation_type",
        )
        _create_or_replace_view(
            connection,
            view_name="mv_places_latest",
            source_table=places_table,
            geometry_column=_find_geometry_column(connection, places_table) if places_table else None,
            object_id_column=_pick_column(connection, places_table, ("cleabs", "id", "objectid", "gid")) if places_table else None,
            label_column=_pick_column(connection, places_table, ("nom", "toponyme", "libelle")) if places_table else None,
        )

        for view in (
            "mv_admin_latest",
            "mv_transport_latest",
            "mv_regulated_latest",
            "mv_places_latest",
        ):
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE INDEX IF NOT EXISTS {idx}
                        ON bdtopo_curated.{view} USING GIST (geom)
                        """
                    ).format(
                        idx=sql.Identifier(f"idx_{view}_geom"),
                        view=sql.Identifier(view),
                    )
                )

        for view in (
            "mv_admin_latest",
            "mv_transport_latest",
            "mv_regulated_latest",
            "mv_places_latest",
        ):
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("ANALYZE bdtopo_curated.{v}").format(
                    v=sql.Identifier(view)
                ))

        connection.commit()

    logger.info(f"Optimization complete: {indexed_tables} spatial indexes, 4 curated views")
    return OptimizationSummary(
        indexed_tables=indexed_tables,
        curated_views=[
            "bdtopo_curated.mv_admin_latest",
            "bdtopo_curated.mv_transport_latest",
            "bdtopo_curated.mv_regulated_latest",
            "bdtopo_curated.mv_places_latest",
        ],
    )

