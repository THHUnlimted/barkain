#!/usr/bin/env bash
# Start Xvfb (virtual framebuffer for headed Chromium) then the FastAPI server.
set -e

# Remove any stale X lock files left behind by a previous container run.
# Without this, `docker restart` fails because Xvfb refuses to bind :99
# when /tmp/.X99-lock already exists.
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true

# Start Xvfb on display :99
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
XVFB_PID=$!

# Wait for Xvfb to be ready
sleep 2

# Start the FastAPI server
exec uvicorn server:app --host 0.0.0.0 --port 8080
