FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libexpat1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt


COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Python runtime settings only - application config comes from ECS
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# WORKERS and secrets (OPENTOPO_API_KEY, MAP_KEY) are set via ECS task definition
CMD ["sh", "-c", "uvicorn server:mcp.sse_app --host 0.0.0.0 --port 8000 --workers ${WORKERS:-1}"]