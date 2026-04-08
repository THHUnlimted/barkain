#!/usr/bin/env bash
# Walmart extraction script — CRITICAL: PerimeterX workaround.
# NEVER use agent-browser open for navigation — PerimeterX blocks it 100%.
# Chrome must be launched directly with the search URL as its starting page.
# agent-browser is still used for wait, scroll, eval, get title via CDP.
#
# Anchor selector: [data-item-id]
# Usage: ./extract.sh <query> [max_listings]

set -euo pipefail

QUERY="${1:?Usage: $0 <query> [max_listings]}"
MAX_LISTINGS="${2:-10}"

CDP_PORT=9222
PROFILE_DIR="/tmp/chrome-scrape-$$"
JS_FILE="/tmp/extract-$$.js"
RETRY_MAX=2
CHROMIUM="${CHROMIUM_PATH:-/usr/bin/chromium}"

# Helpers
log()  { echo "[$(date +%T)] $*" >&2; }
jitter() {
  local min_ms=$1 max_ms=$2
  local delay_ms=$((min_ms + RANDOM % (max_ms - min_ms)))
  sleep "$(echo "scale=3; $delay_ms / 1000" | bc)" 2>/dev/null || sleep 1
}
ab() { agent-browser --cdp $CDP_PORT "$@" 2>/dev/null; }

# Cleanup on exit
cleanup() {
  ab close 2>/dev/null || true
  pkill -f "chromium.*--remote-debugging-port=$CDP_PORT" 2>/dev/null || true
  rm -rf "$PROFILE_DIR" "$JS_FILE" 2>/dev/null || true
}
trap cleanup EXIT

# Step 1: Kill stale Chrome / agent-browser sessions
pkill -f "chromium.*--remote-debugging-port=$CDP_PORT" 2>/dev/null || true
sleep 1

# Build search URL
SEARCH_URL="https://www.walmart.com/search?q=$(echo "$QUERY" | sed 's/ /+/g')"

# Retry loop
attempt=0
while [ $attempt -lt $RETRY_MAX ]; do
  attempt=$((attempt + 1))
  PROFILE_DIR="/tmp/chrome-scrape-$(date +%s)-$attempt"
  [ $attempt -gt 1 ] && { pkill -f "chromium.*--remote-debugging-port=$CDP_PORT" 2>/dev/null || true; jitter 1500 3000; }

  # Step 2: Launch Chromium DIRECTLY with the search URL (NOT about:blank)
  # CRITICAL: PerimeterX triggers on agent-browser open navigation.
  # Chrome must open the search URL as its first page.
  "$CHROMIUM" \
    --remote-debugging-port=$CDP_PORT \
    --user-data-dir="$PROFILE_DIR" \
    --no-first-run \
    --no-default-browser-check \
    --disable-blink-features=AutomationControlled \
    --disable-gpu \
    --no-sandbox \
    "$SEARCH_URL" &
  sleep 4

  # Step 3: NO warm-up step — Chrome already navigated to search URL.
  # Wait for the page to finish loading via CDP.
  ab wait --load networkidle 2>/dev/null || true
  jitter 1500 2500

  # Step 5: Bot detection check
  PAGE_TITLE=$(ab get title 2>/dev/null || echo "")
  if echo "$PAGE_TITLE" | grep -qi "robot\|captcha\|blocked\|verify\|denied\|access denied"; then
    log "Bot detection triggered (attempt $attempt): $PAGE_TITLE"
    continue
  fi

  # Step 6: Handle overlays/modals (Walmart: none typically needed after direct launch)

  # Step 7: Scroll to load lazy content
  for i in 1 2 3 4 5; do
    ab scroll down $((250 + RANDOM % 400)) 2>/dev/null || true
    jitter 600 1200
  done

  # Step 8: Extract via DOM eval
  cp /app/extract.js "$JS_FILE"
  sed -i "s/__MAX_LISTINGS__/$MAX_LISTINGS/g" "$JS_FILE"

  RAW_OUTPUT=$(ab eval --stdin < "$JS_FILE" 2>/dev/null || echo "")

  # Validate output has content
  if [ ${#RAW_OUTPUT} -lt 10 ]; then
    log "Empty extraction output (attempt $attempt)"
    continue
  fi

  # Step 9: Unwrap agent-browser JSON string quoting and output to stdout
  python3 -c "
import json, sys
raw = sys.stdin.read().strip()
if raw.startswith('\"'):
    raw = json.loads(raw)
data = json.loads(raw)
json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
" <<< "$RAW_OUTPUT"

  exit 0
done

# All attempts failed
log "Failed after $RETRY_MAX attempts"
echo '{"listings":[],"metadata":{"url":"","extracted_at":"","bot_detected":true}}'
exit 1
