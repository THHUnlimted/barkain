#!/usr/bin/env bash
# eBay (Used/Refurbished) extraction — filters to used and refurbished items.
# Search URL includes &LH_ItemCondition=3000|2500|2000|2010|2020|2030 for used/refurb.
#
# Anchor: .s-item
# Usage: ./extract.sh <query> [max_listings]

set -euo pipefail

QUERY="${1:?Usage: $0 <query> [max_listings]}"
MAX_LISTINGS="${2:-10}"

CDP_PORT=9222
PROFILE_DIR="/tmp/chrome-scrape-$$"
JS_FILE="/tmp/extract-$$.js"
RETRY_MAX=2
CHROMIUM="${CHROMIUM_PATH:-/usr/bin/chromium}"

log()  { echo "[$(date +%T)] $*" >&2; }
jitter() {
  local min_ms=$1 max_ms=$2
  local delay_ms=$((min_ms + RANDOM % (max_ms - min_ms)))
  sleep "$(echo "scale=3; $delay_ms / 1000" | bc)" 2>/dev/null || sleep 1
}
ab() { agent-browser --cdp $CDP_PORT "$@" 2>/dev/null; }

cleanup() {
  ab close 2>/dev/null || true
  pkill -f "chromium.*--remote-debugging-port=$CDP_PORT" 2>/dev/null || true
  rm -rf "$PROFILE_DIR" "$JS_FILE" 2>/dev/null || true
}
trap cleanup EXIT

# Reserve fd 3 as the real stdout and redirect fd 1 to stderr for all other commands.
# Why: agent-browser writes progress lines ("✓ Done", page titles, "✓ Browser closed")
# to stdout, which used to pollute the JSON we hand back to server.py and broke json.loads.
# Only the final extraction JSON should land on fd 3.
exec 3>&1
exec 1>&2

pkill -f "chromium.*--remote-debugging-port=$CDP_PORT" 2>/dev/null || true
sleep 1

# eBay used/refurb condition filter: 3000=Used, 2500=Seller refurb, 2000=Certified refurb
SEARCH_URL="https://www.ebay.com/sch/i.html?_nkw=$(echo "$QUERY" | sed 's/ /+/g')&LH_ItemCondition=3000%7C2500%7C2000"

attempt=0
while [ $attempt -lt $RETRY_MAX ]; do
  attempt=$((attempt + 1))
  PROFILE_DIR="/tmp/chrome-scrape-$(date +%s)-$attempt"
  [ $attempt -gt 1 ] && { pkill -f "chromium.*--remote-debugging-port=$CDP_PORT" 2>/dev/null || true; jitter 1500 3000; }

  "$CHROMIUM" \
    --remote-debugging-port=$CDP_PORT \
    --user-data-dir="$PROFILE_DIR" \
    --no-first-run --no-default-browser-check \
    --disable-blink-features=AutomationControlled \
    --disable-gpu --no-sandbox \
    "about:blank" &
  sleep 3

  jitter 800 1500
  ab open "https://www.ebay.com" || { log "Warm-up failed (attempt $attempt)"; continue; }
  ab wait --load networkidle 2>/dev/null || true
  jitter 1500 3000
  ab scroll down $((150 + RANDOM % 250)) 2>/dev/null || true

  ab open "$SEARCH_URL" || { log "Navigation failed (attempt $attempt)"; continue; }
  ab wait --load networkidle 2>/dev/null || true
  jitter 1500 2500

  PAGE_TITLE=$(ab get title 2>/dev/null || echo "")
  if echo "$PAGE_TITLE" | grep -qi "robot\|captcha\|blocked\|verify\|denied\|access denied"; then
    log "Bot detection triggered (attempt $attempt): $PAGE_TITLE"
    continue
  fi

  for i in 1 2 3 4 5; do
    ab scroll down $((250 + RANDOM % 400)) 2>/dev/null || true
    jitter 600 1200
  done

  cp /app/extract.js "$JS_FILE"
  sed -i "s/__MAX_LISTINGS__/$MAX_LISTINGS/g" "$JS_FILE"

  RAW_OUTPUT=$(ab eval --stdin < "$JS_FILE" 2>/dev/null || echo "")

  if [ ${#RAW_OUTPUT} -lt 10 ]; then
    log "Empty extraction output (attempt $attempt)"
    continue
  fi

  # Step 9: Unwrap agent-browser JSON string quoting and emit the JSON on fd 3 (real stdout).
  python3 -c "
import json, sys
raw = sys.stdin.read().strip()
if raw.startswith('\"'):
    raw = json.loads(raw)
data = json.loads(raw)
json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
" <<< "$RAW_OUTPUT" >&3

  exit 0
done

log "Failed after $RETRY_MAX attempts"
echo '{"listings":[],"metadata":{"url":"","extracted_at":"","bot_detected":true}}' >&3
exit 1
