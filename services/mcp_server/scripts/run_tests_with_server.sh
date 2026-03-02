#!/usr/bin/env bash
# Run the same steps as the CI "Start MCP server and run tests" job.
# Usage: from repo root, ./services/mcp_server/scripts/run_tests_with_server.sh
#    or: cd services/mcp_server && ./scripts/run_tests_with_server.sh

set -e
cd "$(dirname "$0")/.."
export OPENTOPO_API_KEY="${OPENTOPO_API_KEY:-test-opentopo-api-key}"
export MAP_KEY="${MAP_KEY:-test-map-key}"
export GEOSERVER_BASE_URL="${GEOSERVER_BASE_URL:-https://example.invalid/geoserver}"

echo "Starting MCP server..."
python server.py &
SERVER_PID=$!
trap "kill $SERVER_PID 2>/dev/null || true" EXIT

echo "Waiting for MCP server on port 8000..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/health >/dev/null; then
    echo "Server is ready."
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "Server did not become ready in time."
    exit 1
  fi
  sleep 2
done

pytest -v --tb=short "$@"
