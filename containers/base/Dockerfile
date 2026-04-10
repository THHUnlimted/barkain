# Barkain — Shared Scraper Container Base Image
# All retailer-specific containers inherit from this image.
# Includes: Chromium (headed), agent-browser CLI, Python/FastAPI server, Xvfb.
#
# Build: docker build -t barkain-base:latest containers/base/

FROM node:20-bookworm

# System dependencies for headed Chromium + Xvfb
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    xvfb \
    python3 \
    python3-pip \
    python3-venv \
    fonts-liberation \
    libnss3 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    jq \
    procps \
    curl \
    bc \
    && rm -rf /var/lib/apt/lists/*

# Install agent-browser CLI globally
RUN npm i -g agent-browser && agent-browser install || true

# Python virtual environment with FastAPI + uvicorn
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir fastapi "uvicorn[standard]"

# Environment
ENV DISPLAY=:99
ENV CHROMIUM_PATH=/usr/bin/chromium

WORKDIR /app

# Copy shared server + entrypoint (used by all retailer containers)
COPY server.py .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh
