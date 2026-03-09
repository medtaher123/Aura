# BDTOPO Full-France Pipeline

This service ingests BDTOPO full-France GeoPackage archives into PostGIS and prepares curated views for agent queries.

## What It Does

- Downloads multipart `.7z.001..N` archives from IGN.
- Extracts GeoPackage files.
- Loads all layers into `bdtopo_raw.*` with lineage columns:
  - `edition_date`
  - `source_file`
  - `theme`
  - `loaded_at`
- Builds spatial and filter indexes.
- Creates curated materialized views:
  - `bdtopo_curated.mv_admin_latest`
  - `bdtopo_curated.mv_transport_latest`
  - `bdtopo_curated.mv_regulated_latest`
  - `bdtopo_curated.mv_places_latest`
- Runs quality checks and writes JSON reports.

## Prerequisites

- Python 3.11+
- `7z` (from `p7zip-full`)
- GDAL CLI (`ogrinfo`, `ogr2ogr`)
- PostGIS-enabled PostgreSQL target

## Environment Variables

- `BDTOPO_DATABASE_URL` (required): PostgreSQL URL for ingestion and optimization.
- `BDTOPO_WORK_DIR` (default: `/tmp/bdtopo`)
- `BDTOPO_SOURCE_TEMPLATE` (default full-France WGS84G pattern)
- `BDTOPO_SOURCE_URLS` (optional inline URL list, comma/newline separated)
- `BDTOPO_SOURCE_URLS_FILE` (optional path with one URL per line)
- `BDTOPO_PART_COUNT` (default: `9`)
- `BDTOPO_DOWNLOAD_TIMEOUT_SECONDS` (default: `90`)
- `BDTOPO_DOWNLOAD_MAX_RETRIES` (default: `5`)
- `BDTOPO_QUALITY_INVALID_RATIO_THRESHOLD` (default: `0.01`)

## Run

```bash
python services/bdtopo_pipeline/run_pipeline.py --mode full --edition-date 2025-12-15
```

For differential or express mode, provide URLs directly or via a text file:

```bash
export BDTOPO_SOURCE_URLS="https://.../part1.7z.001,https://.../part1.7z.002"
# OR: export BDTOPO_SOURCE_URLS_FILE=/path/to/urls.txt
export BDTOPO_SOURCE_URLS_FILE=/path/to/urls.txt
python services/bdtopo_pipeline/run_pipeline.py --mode differential --edition-date 2026-03-15
```

## One-Command Bootstrap (First Ingest)

Use the helper script to install dependencies (optional) and run the pipeline in one step:

```bash
./services/bdtopo_pipeline/bootstrap_first_ingest.sh \
  --database-url "postgresql://user:password@host:5432/bdtopo" \
  --edition-date 2025-12-15
```

If your machine is missing `7z`/GDAL tools:

```bash
./services/bdtopo_pipeline/bootstrap_first_ingest.sh \
  --database-url "postgresql://user:password@host:5432/bdtopo" \
  --edition-date 2025-12-15 \
  --install-system-deps
```

## Outputs

Reports are saved under:

- `/tmp/bdtopo/reports/<edition-date>/pipeline_summary.json`
- `/tmp/bdtopo/reports/<edition-date>/quality_report.json`

## Theme-to-Capability Mapping

See `services/bdtopo_pipeline/THEME_CAPABILITIES.md`.

## Operations Runbook

For production secret wiring and validation steps (GitHub + ECS), see:

- `services/bdtopo_pipeline/OPS_RUNBOOK.md`
