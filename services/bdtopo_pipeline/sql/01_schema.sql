CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS bdtopo_stage;
CREATE SCHEMA IF NOT EXISTS bdtopo_raw;
CREATE SCHEMA IF NOT EXISTS bdtopo_curated;
CREATE SCHEMA IF NOT EXISTS bdtopo_meta;

CREATE TABLE IF NOT EXISTS bdtopo_meta.ingestion_log (
    id BIGSERIAL PRIMARY KEY,
    edition_date DATE NOT NULL,
    source_file TEXT NOT NULL,
    layer_name TEXT NOT NULL,
    target_table TEXT NOT NULL,
    theme TEXT NOT NULL,
    row_count BIGINT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ingestion_log_edition
    ON bdtopo_meta.ingestion_log (edition_date);

