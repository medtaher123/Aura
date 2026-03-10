"""Load BDTOPO GeoPackage layers into PostGIS with idempotency controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
from typing_extensions import LiteralString, cast
from urllib.parse import unquote, urlparse

from .logger import get_logger
import psycopg
from psycopg import sql

from .config import PipelineConfig

logger = get_logger("loader")


THEME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "administratif": ("admin", "commune", "departement", "canton", "arrondissement"),
    "bati": ("bati", "batiment", "construction", "building"),
    "hydrographie": ("hydro", "cours_d_eau", "plan_d_eau", "water"),
    "lieux_nommes": ("toponyme", "lieu", "nomme", "nom_"),
    "occupation_sol": ("vegetation", "occupation", "sol", "haie", "estran"),
    "services_activites": ("activite", "service", "energie", "industriel", "erp"),
    "transport": ("route", "troncon", "transport", "ferre", "aerodrome", "itiner"),
    "zones_reglementees": ("reglement", "zone", "servitude"),
}


@dataclass(slots=True)
class LayerLoadResult:
    layer_name: str
    target_table: str
    row_count: int
    theme: str


def _normalize_identifier(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", value).lower().strip("_")


def _infer_theme(layer_name: str) -> str:
    lower = layer_name.lower()
    for theme, keywords in THEME_KEYWORDS.items():
        if any(keyword in lower for keyword in keywords):
            return theme
    return "unknown"


def _to_ogr_pg_dsn(database_url: str) -> str:
    parsed = urlparse(database_url)
    if not parsed.scheme.startswith("postgres"):
        raise ValueError("BDTOPO_DATABASE_URL must be a PostgreSQL URL.")
    db_name = parsed.path.lstrip("/")
    if not db_name:
        raise ValueError("Database name is missing in BDTOPO_DATABASE_URL.")
    parts = [
        f"host={parsed.hostname or ''}",
        f"port={parsed.port or 5432}",
        f"dbname={db_name}",
        f"user={unquote(parsed.username or '')}",
        f"password={unquote(parsed.password or '')}",
    ]
    return " ".join(parts)


def _list_gpkg_layers(gpkg_path: Path) -> list[str]:
    process = subprocess.run(
        ["ogrinfo", "-ro", str(gpkg_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"Failed to inspect {gpkg_path} with ogrinfo: {process.stderr}"
        )
    layers: list[str] = []
    pattern = re.compile(r"^\s*\d+:\s+([^\s(]+)")
    for line in process.stdout.splitlines():
        match = pattern.match(line)
        if match:
            layers.append(match.group(1))
    if not layers:
        raise RuntimeError(f"No layers found in GeoPackage: {gpkg_path}")
    return layers


def _apply_schema(connection: psycopg.Connection, schema_file: Path) -> None:
    schema_sql: LiteralString = cast(
        LiteralString, schema_file.read_text(encoding="utf-8")
    )
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL(schema_sql))
    connection.commit()


def _ogr_load_layer(
    *,
    ogr_pg_dsn: str,
    gpkg_path: Path,
    layer_name: str,
    tmp_table_name: str,
) -> None:
    command = [
        "ogr2ogr",
        "-f",
        "PostgreSQL",
        f"PG:{ogr_pg_dsn}",
        str(gpkg_path),
        layer_name,
        "-nln",
        f"bdtopo_stage.{tmp_table_name}",
        "-nlt",
        "PROMOTE_TO_MULTI",
        "-t_srs",
        "EPSG:4326",
        "-overwrite",
        "--config",
        "PG_USE_COPY",
        "YES",
    ]
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    if process.returncode != 0:
        raise RuntimeError(
            f"ogr2ogr failed for layer {layer_name}\n"
            f"stdout:\n{process.stdout}\n"
            f"stderr:\n{process.stderr}"
        )


def _fetch_columns(
    connection: psycopg.Connection,
    schema_name: str,
    table_name: str,
) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
            ORDER BY ordinal_position
            """,
            (schema_name, table_name),
        )
        rows = cursor.fetchall()
    return [row[0] for row in rows]


def _drop_stage_bound_defaults(
    connection: psycopg.Connection,
    target_table_name: str,
) -> None:
    """Drop defaults copied from temporary stage-table sequences."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT attribute.attname
            FROM pg_attrdef AS attrdef
            JOIN pg_attribute AS attribute
              ON attribute.attrelid = attrdef.adrelid
             AND attribute.attnum = attrdef.adnum
            JOIN pg_class AS class_rel
              ON class_rel.oid = attrdef.adrelid
            JOIN pg_namespace AS namespace_rel
              ON namespace_rel.oid = class_rel.relnamespace
            WHERE namespace_rel.nspname = 'bdtopo_raw'
              AND class_rel.relname = %s
              AND pg_get_expr(attrdef.adbin, attrdef.adrelid) LIKE %s
            """,
            (target_table_name, "%bdtopo_stage.%"),
        )
        columns = [row[0] for row in cursor.fetchall()]

        for column in columns:
            cursor.execute(
                sql.SQL(
                    """
                    ALTER TABLE bdtopo_raw.{target}
                    ALTER COLUMN {column} DROP DEFAULT
                    """
                ).format(
                    target=sql.Identifier(target_table_name),
                    column=sql.Identifier(column),
                )
            )


def _fetch_pk_columns(
    connection: psycopg.Connection,
    schema_name: str,
    table_name: str,
) -> list[str]:
    """Return primary-key column names for the given table (empty if none)."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE i.indisprimary
              AND n.nspname = %s
              AND c.relname = %s
            ORDER BY array_position(i.indkey, a.attnum)
            """,
            (schema_name, table_name),
        )
        return [row[0] for row in cursor.fetchall()]


def _align_columns(
    connection: psycopg.Connection,
    tmp_table_name: str,
    target_table_name: str,
) -> None:
    """Add any columns present in the stage table but missing from the raw table."""
    stage_cols = set(_fetch_columns(connection, "bdtopo_stage", tmp_table_name))
    raw_cols = set(_fetch_columns(connection, "bdtopo_raw", target_table_name))
    missing = stage_cols - raw_cols
    if not missing:
        return
    with connection.cursor() as cursor:
        for col in missing:
            cursor.execute(
                sql.SQL(
                    """
                    SELECT data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'bdtopo_stage'
                      AND table_name = %s
                      AND column_name = %s
                    """
                ),
                (tmp_table_name, col),
            )
            row = cursor.fetchone()
            col_type = row[0] if row else "TEXT"
            logger.info(f"Adding missing column {col} ({col_type}) to bdtopo_raw.{target_table_name}")
            cursor.execute(
                sql.SQL(
                    "ALTER TABLE bdtopo_raw.{target} ADD COLUMN {col} {type}"
                ).format(
                    target=sql.Identifier(target_table_name),
                    col=sql.Identifier(col),
                    type=sql.SQL(col_type),
                )
            )


def _merge_tmp_into_raw(
    *,
    connection: psycopg.Connection,
    tmp_table_name: str,
    target_table_name: str,
    edition_date: str,
    source_file: str,
    theme: str,
    layer_name: str,
) -> LayerLoadResult:
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS bdtopo_raw.{target}
                (LIKE bdtopo_stage.{tmp} INCLUDING ALL EXCLUDING DEFAULTS)
                """
            ).format(
                target=sql.Identifier(target_table_name),
                tmp=sql.Identifier(tmp_table_name),
            )
        )

        for schema_name, table_name in (
            ("bdtopo_raw", target_table_name),
            ("bdtopo_stage", tmp_table_name),
        ):
            cursor.execute(
                sql.SQL(
                    """
                    ALTER TABLE {schema}.{table}
                    ADD COLUMN IF NOT EXISTS edition_date DATE,
                    ADD COLUMN IF NOT EXISTS source_file TEXT,
                    ADD COLUMN IF NOT EXISTS theme TEXT,
                    ADD COLUMN IF NOT EXISTS loaded_at TIMESTAMPTZ DEFAULT NOW()
                    """
                ).format(
                    schema=sql.Identifier(schema_name),
                    table=sql.Identifier(table_name),
                )
            )

        cursor.execute(
            sql.SQL(
                """
                UPDATE bdtopo_stage.{tmp}
                   SET edition_date = %s,
                       source_file = %s,
                       theme = %s,
                       loaded_at = NOW()
                """
            ).format(tmp=sql.Identifier(tmp_table_name)),
            (edition_date, source_file, theme),
        )

        cursor.execute(
            sql.SQL(
                """
                DELETE FROM bdtopo_raw.{target}
                WHERE edition_date = %s
                  AND source_file = %s
                  AND theme = %s
                """
            ).format(target=sql.Identifier(target_table_name)),
            (edition_date, source_file, theme),
        )

    _drop_stage_bound_defaults(connection, target_table_name)
    _align_columns(connection, tmp_table_name, target_table_name)

    columns = _fetch_columns(connection, "bdtopo_stage", tmp_table_name)
    column_identifiers = sql.SQL(", ").join(
        sql.Identifier(column) for column in columns
    )

    pk_cols = _fetch_pk_columns(connection, "bdtopo_raw", target_table_name)

    with connection.cursor() as cursor:
        if pk_cols:
            non_pk = [c for c in columns if c not in pk_cols]
            update_set = sql.SQL(", ").join(
                sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(c))
                for c in non_pk
            )
            cursor.execute(
                sql.SQL(
                    """
                    INSERT INTO bdtopo_raw.{target} ({columns})
                    SELECT {columns}
                      FROM bdtopo_stage.{tmp}
                    ON CONFLICT ({pk}) DO UPDATE SET {update_set}
                    """
                ).format(
                    target=sql.Identifier(target_table_name),
                    tmp=sql.Identifier(tmp_table_name),
                    columns=column_identifiers,
                    pk=sql.SQL(", ").join(sql.Identifier(c) for c in pk_cols),
                    update_set=update_set,
                )
            )
        else:
            cursor.execute(
                sql.SQL(
                    """
                    INSERT INTO bdtopo_raw.{target} ({columns})
                    SELECT {columns}
                      FROM bdtopo_stage.{tmp}
                    """
                ).format(
                    target=sql.Identifier(target_table_name),
                    tmp=sql.Identifier(tmp_table_name),
                    columns=column_identifiers,
                )
            )

        cursor.execute(
            sql.SQL("SELECT COUNT(*) FROM bdtopo_stage.{tmp}").format(
                tmp=sql.Identifier(tmp_table_name)
            )
        )
        fetchone = cursor.fetchone()
        if not fetchone:
            raise RuntimeError(f"Failed to fetch row count for {tmp_table_name}")
        row_count = int(fetchone[0])

        cursor.execute(
            """
            INSERT INTO bdtopo_meta.ingestion_log
                (edition_date, source_file, layer_name, target_table, theme, row_count, loaded_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (edition_date, source_file, layer_name)
            DO UPDATE SET row_count = EXCLUDED.row_count,
                          loaded_at = EXCLUDED.loaded_at
            """,
            (
                edition_date,
                source_file,
                layer_name,
                target_table_name,
                theme,
                row_count,
            ),
        )

        cursor.execute(
            sql.SQL("DROP TABLE IF EXISTS bdtopo_stage.{tmp}").format(
                tmp=sql.Identifier(tmp_table_name)
            )
        )

    connection.commit()
    return LayerLoadResult(
        layer_name=layer_name,
        target_table=target_table_name,
        row_count=row_count,
        theme=theme,
    )


def _layer_already_loaded(
    conn: psycopg.Connection, edition_date: str, source_file: str, layer_name: str
) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM bdtopo_meta.ingestion_log "
            "WHERE edition_date = %s AND source_file = %s AND layer_name = %s "
            "LIMIT 1",
            (edition_date, source_file, layer_name),
        )
        return cur.fetchone() is not None


def _cleanup_orphaned_stage_tables(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'bdtopo_stage'
        """)
        for (table_name,) in cursor.fetchall():
            logger.info(f"Dropping orphaned stage table: bdtopo_stage.{table_name}")
            cursor.execute(
                sql.SQL("DROP TABLE IF EXISTS bdtopo_stage.{t} CASCADE").format(
                    t=sql.Identifier(table_name)
                )
            )
    connection.commit()


def load_gpkg_files(
    config: PipelineConfig, gpkg_files: list[Path]
) -> list[LayerLoadResult]:
    if not config.database_url:
        raise ValueError(
            "BDTOPO_DATABASE_URL is required to load GeoPackages into PostGIS."
        )

    schema_file = Path(__file__).resolve().parent / "sql" / "01_schema.sql"
    if not schema_file.exists():
        raise FileNotFoundError(f"Schema file missing: {schema_file}")
    logger.info(f"Applying schema from {schema_file}")
    ogr_pg_dsn = _to_ogr_pg_dsn(config.database_url)
    results: list[LayerLoadResult] = []

    with psycopg.connect(config.database_url, autocommit=False) as connection:
        logger.info("Connecting to PostGIS")
        _apply_schema(connection, schema_file)
        _cleanup_orphaned_stage_tables(connection)
        logger.info(f"Parsing {len(gpkg_files)} GeoPackages...")
        for gpkg_path in gpkg_files:
            source_file = gpkg_path.name
            layers = _list_gpkg_layers(gpkg_path)
            logger.info(f"  Found {len(layers)} layers in {gpkg_path}")
            for i_la, layer_name in enumerate(layers, start=1):
                if _layer_already_loaded(connection, config.edition_date, source_file, layer_name):
                    logger.info(f"[{i_la}/{len(layers)}] Skipping {layer_name} (already loaded)")
                    continue
                layer_slug = _normalize_identifier(layer_name) or "layer"
                tmp_table = f"    tmp_{layer_slug}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')[-10:]}"
                target_table = layer_slug[:55]
                theme = _infer_theme(layer_name)
                logger.info(f"    [{i_la}/{len(layers)}] Loading {layer_name} into {tmp_table}")
                _ogr_load_layer(
                    ogr_pg_dsn=ogr_pg_dsn,
                    gpkg_path=gpkg_path,
                    layer_name=layer_name,
                    tmp_table_name=tmp_table,
                )
                logger.info(f"    [{i_la}/{len(layers)}] Merging {tmp_table} into {target_table}")
                result = _merge_tmp_into_raw(
                    connection=connection,
                    tmp_table_name=tmp_table,
                    target_table_name=target_table,
                    edition_date=config.edition_date,
                    source_file=source_file,
                    theme=theme,
                    layer_name=layer_name,
                )
                results.append(result)
    logger.info(f"Loaded {len(results)} layers into {config.edition_date}")
    return results
