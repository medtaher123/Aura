# Multi-stage build for MetaplanetLLM
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

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies (ignore system packages to avoid conflicts)
RUN pip3 install --no-cache-dir --ignore-installed -r requirements.txt --break-system-packages

# Copy application files
COPY . .

# Expose ports
EXPOSE 8501 5679

# Copy startup script
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Add Docker health check
HEALTHCHECK --interval=20s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8501/health || exit 1

# Run the startup script
CMD ["/app/start.sh"]
