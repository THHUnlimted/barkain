#!/usr/bin/env bash
# Best Buy extraction script — 9-step agent-browser DOM eval pattern.
# Anchor selector: a.sku-title → walk up to .list-item card container.
# Bot detection: Moderate — headed Chrome with anti-detection flags works.
#
# Step 2b optimizations (target: <45s from ~90s):
#   - Reduced scroll passes from 5 to 2 (first 12 results front-loaded)
#   - Switched warmup+search waits from networkidle to load
#   - Removed homepage scroll during warmup
#   - Added TIMING profiling logs to stderr
#
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
timing() { echo "[$(date +%T)] TIMING: $* at $(date +%s%N | cut -b1-13)ms" >&2; }
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

# Reserve fd 3 as the real stdout and redirect fd 1 to stderr for all other commands.
# Why: agent-browser writes progress lines ("✓ Done", "✓ <page title>", "✓ Browser closed")
# to stdout, which used to pollute the JSON we hand back to server.py and broke json.loads.
# Only the final extraction JSON should land on fd 3.
exec 3>&1
exec 1>&2

# Step 1: Kill stale Chrome / agent-browser sessions
pkill -f "chromium.*--remote-debugging-port=$CDP_PORT" 2>/dev/null || true
sleep 1

# Build search URL
SEARCH_URL="https://www.bestbuy.com/site/searchpage.jsp?st=$(echo "$QUERY" | sed 's/ /+/g')"

# Retry loop
attempt=0
while [ $attempt -lt $RETRY_MAX ]; do
  attempt=$((attempt + 1))
  PROFILE_DIR="/tmp/chrome-scrape-$(date +%s)-$attempt"
  [ $attempt -gt 1 ] && { pkill -f "chromium.*--remote-debugging-port=$CDP_PORT" 2>/dev/null || true; jitter 1500 3000; }

  # Step 2: Launch headed Chromium with anti-detection flags
  timing "chrome_launch_start"
  "$CHROMIUM" \
    --remote-debugging-port=$CDP_PORT \
    --user-data-dir="$PROFILE_DIR" \
    --no-first-run \
    --no-default-browser-check \
    --disable-blink-features=AutomationControlled \
    --disable-gpu \
    --no-sandbox \
    "about:blank" &
  sleep 3
  timing "chrome_launch_done"

  # Step 3: Warm up on Best Buy homepage (establish cookies)
  # Optimization: removed homepage scroll and switched to load wait (not networkidle)
  timing "warmup_start"
  jitter 500 1000
  ab open "https://www.bestbuy.com" || { log "Warm-up failed (attempt $attempt)"; continue; }
  ab wait --load load 2>/dev/null || true
  jitter 1000 2000
  timing "warmup_done"

  # Step 4: Navigate to search page
  timing "navigate_start"
  ab open "$SEARCH_URL" || { log "Navigation failed (attempt $attempt)"; continue; }
  ab wait --load load 2>/dev/null || true
  jitter 1000 2000
  timing "navigate_done"

  # Step 5: Bot detection check
  PAGE_TITLE=$(ab get title 2>/dev/null || echo "")
  if echo "$PAGE_TITLE" | grep -qi "robot\|captcha\|blocked\|verify\|denied\|access denied"; then
    log "Bot detection triggered (attempt $attempt): $PAGE_TITLE"
    continue
  fi
  timing "bot_check_passed"

  # Step 6: Handle overlays/modals (Best Buy: location/cookie prompts)
  ab eval 'document.querySelector(".c-close-icon")?.click()' 2>/dev/null || true
  jitter 300 600

  # Step 7: Scroll to load lazy content (2 passes — first 12 results front-loaded)
  # Optimization: reduced from 5 passes; extra passes only loaded lazy images
  timing "scroll_start"
  for i in 1 2; do
    ab scroll down $((250 + RANDOM % 400)) 2>/dev/null || true
    jitter 500 1000
  done
  timing "scroll_done"

  # Step 8: Extract via DOM eval
  timing "extract_start"
  cp /app/extract.js "$JS_FILE"
  sed -i "s/__MAX_LISTINGS__/$MAX_LISTINGS/g" "$JS_FILE"

  RAW_OUTPUT=$(ab eval --stdin < "$JS_FILE" 2>/dev/null || echo "")

  # Validate output has content
  if [ ${#RAW_OUTPUT} -lt 10 ]; then
    log "Empty extraction output (attempt $attempt)"
    continue
  fi

  # Step 9: Unwrap agent-browser JSON string quoting and emit the JSON on fd 3 (real stdout).
  timing "extract_done"
  python3 -c "
import json, sys
raw = sys.stdin.read().strip()
if raw.startswith('\"'):
    raw = json.loads(raw)
data = json.loads(raw)
json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
" <<< "$RAW_OUTPUT" >&3

  timing "complete"
  exit 0
done

# All attempts failed
log "Failed after $RETRY_MAX attempts"
echo '{"listings":[],"metadata":{"url":"","extracted_at":"","bot_detected":true}}' >&3
exit 1
