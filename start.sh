#!/bin/bash
set -e

# Trap signals for graceful shutdown
trap 'kill -TERM $OLLAMA_PID $STREAMLIT_PID 2>/dev/null; wait' SIGTERM SIGINT

echo "Starting Ollama service..."
export OLLAMA_MODELS=/app/.ollama/models
ollama serve &
OLLAMA_PID=$!

# Wait for Ollama to be ready using health endpoint
echo "Waiting for Ollama to be ready..."
timeout 60 bash -c 'until curl -sf http://localhost:11434/api/tags >/dev/null; do sleep 1; done' || {
    echo "ERROR: Ollama failed to become ready"
    exit 1
}

echo "Ollama is ready!"
ollama list

echo "Starting Streamlit application..."
streamlit run streamlit_app.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false &
STREAMLIT_PID=$!

# Wait for both processes
wait -n
exit $?
