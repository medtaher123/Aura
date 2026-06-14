#!/bin/bash
set -e

# Trap signals for graceful shutdown
trap 'kill -TERM $STREAMLIT_PID 2>/dev/null; wait' SIGTERM SIGINT


if [ "$DEBUG" = "true" ]; then
    echo "Starting Streamlit application in DEBUG mode..."
    # We invoke Streamlit as a Python module through debugpy
    python3 -m debugpy --listen 0.0.0.0:5678 -m streamlit run src/ui/streamlit_app.py \
        --server.port=8501 \
        --server.address=0.0.0.0 \
        --server.headless=true \
        --server.enableCORS=false \
        --server.enableXsrfProtection=false &
else
    echo "Starting Streamlit application..."
    streamlit run src/ui/streamlit_app.py \
        --server.port=8501 \
        --server.address=0.0.0.0 \
        --server.headless=true \
        --server.enableCORS=false \
        --server.enableXsrfProtection=false &
fi

STREAMLIT_PID=$!

# Wait for process
wait -n
exit $? 
