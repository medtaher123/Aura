#!/bin/bash
set -e

# Trap signals for graceful shutdown
trap 'kill -TERM $STREAMLIT_PID 2>/dev/null; wait' SIGTERM SIGINT

echo "Starting Streamlit application..."
streamlit run src/ui/streamlit_app.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false &
STREAMLIT_PID=$!

# Wait for process
wait -n
exit $?
