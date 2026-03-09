#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Bootstrap first BDTOPO ingest (one command).

Usage:
  ./services/bdtopo_pipeline/bootstrap_first_ingest.sh [options]

Options:
  --database-url <dsn>         PostgreSQL DSN (or set BDTOPO_DATABASE_URL).
  --mode <full|express|differential>
                               Ingestion mode (default: full).
  --edition-date <YYYY-MM-DD>  Edition date (default: current UTC date).
  --urls "<u1,u2,...>"         Inline archive URLs (sets BDTOPO_SOURCE_URLS).
  --urls-file <path>           File with one URL per line (sets BDTOPO_SOURCE_URLS_FILE).
  --work-dir <path>            Working directory (sets BDTOPO_WORK_DIR).
  --python <bin>               Python executable (default: python3).
  --install-system-deps        Install p7zip + gdal via apt-get if missing.
  --skip-pip-install           Skip pip install of Python dependencies.
  -h, --help                   Show this help.

Examples:
  ./services/bdtopo_pipeline/bootstrap_first_ingest.sh \
    --database-url "postgresql://user:pass@host:5432/bdtopo" \
    --edition-date 2025-12-15

  ./services/bdtopo_pipeline/bootstrap_first_ingest.sh \
    --database-url "postgresql://user:pass@host:5432/bdtopo" \
    --mode differential \
    --urls "https://...001,https://...002"
EOF
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

MODE="full"
EDITION_DATE="$(date -u +%F)"
PYTHON_BIN="python3"
INSTALL_SYSTEM_DEPS="false"
SKIP_PIP_INSTALL="false"

DB_URL="${BDTOPO_DATABASE_URL:-}"
INLINE_URLS=""
URLS_FILE=""
WORK_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --database-url)
      DB_URL="${2:-}"
      shift 2
      ;;
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    --edition-date)
      EDITION_DATE="${2:-}"
      shift 2
      ;;
    --urls)
      INLINE_URLS="${2:-}"
      shift 2
      ;;
    --urls-file)
      URLS_FILE="${2:-}"
      shift 2
      ;;
    --work-dir)
      WORK_DIR="${2:-}"
      shift 2
      ;;
    --python)
      PYTHON_BIN="${2:-}"
      shift 2
      ;;
    --install-system-deps)
      INSTALL_SYSTEM_DEPS="true"
      shift
      ;;
    --skip-pip-install)
      SKIP_PIP_INSTALL="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ "$MODE" != "full" && "$MODE" != "express" && "$MODE" != "differential" ]]; then
  echo "Invalid --mode: $MODE (expected: full|express|differential)" >&2
  exit 1
fi

if [[ -z "$DB_URL" ]]; then
  echo "BDTOPO database URL is required (--database-url or BDTOPO_DATABASE_URL)." >&2
  exit 1
fi

if [[ -n "$INLINE_URLS" && -n "$URLS_FILE" ]]; then
  echo "Use either --urls or --urls-file, not both." >&2
  exit 1
fi

if [[ "$MODE" != "full" && -z "$INLINE_URLS" && -z "$URLS_FILE" ]]; then
  echo "Mode '$MODE' requires --urls or --urls-file." >&2
  exit 1
fi

if ! command_exists "$PYTHON_BIN"; then
  echo "Python executable not found: $PYTHON_BIN" >&2
  exit 1
fi

missing_bins=()
for bin in 7z ogrinfo ogr2ogr; do
  if ! command_exists "$bin"; then
    missing_bins+=("$bin")
  fi
done

if [[ ${#missing_bins[@]} -gt 0 ]]; then
  if [[ "$INSTALL_SYSTEM_DEPS" == "true" ]]; then
    if ! command_exists apt-get; then
      echo "Cannot auto-install system dependencies: apt-get not found." >&2
      echo "Missing tools: ${missing_bins[*]}" >&2
      exit 1
    fi

    SUDO=""
    if [[ "${EUID}" -ne 0 ]]; then
      if command_exists sudo; then
        SUDO="sudo"
      else
        echo "sudo not found and not running as root." >&2
        echo "Install manually: p7zip-full gdal-bin" >&2
        exit 1
      fi
    fi

    $SUDO apt-get update
    $SUDO apt-get install -y --no-install-recommends p7zip-full gdal-bin
  else
    echo "Missing required system tools: ${missing_bins[*]}" >&2
    echo "Install them first (Ubuntu/Debian): sudo apt-get install -y p7zip-full gdal-bin" >&2
    echo "Or rerun with: --install-system-deps" >&2
    exit 1
  fi
fi

if [[ "$SKIP_PIP_INSTALL" != "true" ]]; then
  "$PYTHON_BIN" -m pip install --upgrade pip -q
  "$PYTHON_BIN" -m pip install -r "${REPO_ROOT}/services/bdtopo_pipeline/requirements.txt" -q
fi

export BDTOPO_DATABASE_URL="$DB_URL"
if [[ -n "$INLINE_URLS" ]]; then
  export BDTOPO_SOURCE_URLS="$INLINE_URLS"
fi
if [[ -n "$URLS_FILE" ]]; then
  export BDTOPO_SOURCE_URLS_FILE="$URLS_FILE"
fi
if [[ -n "$WORK_DIR" ]]; then
  export BDTOPO_WORK_DIR="$WORK_DIR"
fi

echo "Starting BDTOPO ingest:"
echo "  mode=${MODE}"
echo "  edition_date=${EDITION_DATE}"
echo "  work_dir=${BDTOPO_WORK_DIR:-/tmp/bdtopo}"

"$PYTHON_BIN" "${REPO_ROOT}/services/bdtopo_pipeline/run_pipeline.py" \
  --mode "$MODE" \
  --edition-date "$EDITION_DATE"

echo "Done. Reports:"
echo "  ${BDTOPO_WORK_DIR:-/tmp/bdtopo}/reports/${EDITION_DATE}/pipeline_summary.json"
echo "  ${BDTOPO_WORK_DIR:-/tmp/bdtopo}/reports/${EDITION_DATE}/quality_report.json"
