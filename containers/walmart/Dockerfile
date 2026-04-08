# Barkain — Walmart Scraper Container
# Port: 8083 | Retailer: walmart
# CRITICAL: PerimeterX — Chrome must launch directly with search URL.
# Never use agent-browser open for navigation.

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
ENV RETAILER_ID=walmart
ENV SCRIPT_VERSION=0.1.0

WORKDIR /app

# Copy application files
COPY server.py .
COPY extract.sh ./base-extract.sh
COPY entrypoint.sh .
RUN chmod +x base-extract.sh entrypoint.sh

# Copy retailer-specific files
COPY extract.js .
COPY config.json .
COPY test_fixtures.json .

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
