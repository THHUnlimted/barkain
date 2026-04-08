#!/usr/bin/env bash
set -e
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
sleep 1
exec uvicorn server:app --host 0.0.0.0 --port 8080
