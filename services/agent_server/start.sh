#!/bin/bash

if [ "$DEV_MODE" = "true" ]; then
    echo "🔧 Starting in DEV mode (auto-reload enabled)"
    exec uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload
else
    echo "🚀 Starting in PROD mode"
    exec uvicorn src.main:app --host 0.0.0.0 --port 8080 --workers ${WORKERS:-1}
fi

