# Multi-stage build for MetaplanetLLM with Ollama
FROM ubuntu:24.04 AS base

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies including Python 3.12
RUN apt-get update && apt-get install -y \
    python3.12 \
    python3-pip \
    curl \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set python3.12 as default python3
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1

# Install Ollama
RUN curl -fsSL https://ollama.ai/install.sh | sh

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies (ignore system packages to avoid conflicts)
RUN pip3 install --no-cache-dir --ignore-installed -r requirements.txt --break-system-packages

# Copy application files
COPY . .

# Pre-download Mistral model during build (so it's baked into the image)
# Set OLLAMA_MODELS to ensure it's stored in the image layer
ENV OLLAMA_MODELS=/app/.ollama/models
RUN mkdir -p /app/.ollama && \
    ollama serve & \
    OLLAMA_PID=$! && \
    echo "Waiting for Ollama to start..." && \
    sleep 10 && \
    echo "Pulling mistral model..." && \
    ollama pull mistral && \
    echo "Model downloaded successfully" && \
    ollama list && \
    kill $OLLAMA_PID && \
    wait $OLLAMA_PID 2>/dev/null || true

# Expose ports
EXPOSE 8501 11434

# Create startup script
RUN echo '#!/bin/bash\n\
set -e\n\
export OLLAMA_MODELS=/app/.ollama/models\n\
ollama serve &\n\
sleep 5\n\
ollama list || echo "Failed to list models"\n\
exec streamlit run streamlit_app.py --server.port=8501 --server.address=0.0.0.0 --server.headless=true --server.enableCORS=false --server.enableXsrfProtection=false\n\
' > /app/start.sh && chmod +x /app/start.sh

# Run the startup script
CMD ["/app/start.sh"]
