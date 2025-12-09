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

# Upgrade pip
RUN pip3 install --upgrade pip setuptools wheel --break-system-packages

# Install Ollama
RUN curl -fsSL https://ollama.ai/install.sh | sh

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose ports
EXPOSE 8501 11434

# Create startup script
RUN echo '#!/bin/bash\n\
set -e\n\
echo "Starting Ollama server..."\n\
ollama serve &\n\
OLLAMA_PID=$!\n\
echo "Waiting for Ollama to be ready..."\n\
sleep 5\n\
echo "Pulling Mistral model..."\n\
ollama pull mistral || echo "Model already exists or pull failed, continuing..."\n\
echo "Starting Streamlit app..."\n\
streamlit run streamlit_app.py --server.port=8501 --server.address=0.0.0.0 --server.headless=true\n\
wait $OLLAMA_PID\n\
' > /app/start.sh && chmod +x /app/start.sh

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
  CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Run the startup script
CMD ["/app/start.sh"]
