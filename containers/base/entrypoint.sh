#!/usr/bin/env bash
# Start Xvfb (virtual framebuffer for headed Chromium) then the FastAPI server.
set -e

# Start Xvfb on display :99
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
XVFB_PID=$!

# Wait for Xvfb to be ready
sleep 1

# Start the FastAPI server
exec uvicorn server:app --host 0.0.0.0 --port 8080
