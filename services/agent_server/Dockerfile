FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libexpat1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Python runtime settings only - application config comes from ECS
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# WORKERS and secrets are set via ECS task definition
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port 8080 --workers ${WORKERS:-1}"]
