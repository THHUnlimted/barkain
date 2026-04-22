#!/usr/bin/env bash
# Facebook Marketplace extraction script — DOM eval via Decodo residential proxy.
#
# Facebook gates Marketplace by IP reputation: AWS datacenter IPs get a hard
# redirect to /login/, residential IPs see content with a dismissible login
# overlay. This script routes Chromium through a local proxy relay that injects
# Decodo credentials, giving us a US residential IP.
#
# Login modal: HIDE with display:none (NEVER .remove() — breaks React tree).
# DOM is fully rendered behind the CSS overlay.
# All items default to condition "used".
#
# Anchor selector: a[href*="/marketplace/item/"]
# Usage: ./extract.sh <query> [max_listings]
#
# Requires env vars: DECODO_PROXY_USER, DECODO_PROXY_PASS (set in docker run).
# DECODO_PROXY_HOST defaults to gate.decodo.com, DECODO_PROXY_PORT to 7000.

set -euo pipefail

QUERY="${1:?Usage: $0 <query> [max_listings]}"
MAX_LISTINGS="${2:-10}"

CDP_PORT=9222
PROFILE_DIR="/tmp/chrome-scrape-$$"
JS_FILE="/tmp/extract-$$.js"
RETRY_MAX=2
CHROMIUM="${CHROMIUM_PATH:-/usr/bin/chromium}"
PROXY_RELAY_PORT=18080

# Location resolution order:
#   1. Per-request override from the backend (FB_LOCATION_SLUG /
#      FB_RADIUS_MILES in the process env — set by containers/base/server.py
#      when the iOS caller supplied user coordinates).
#   2. Container-wide env default (FB_MARKETPLACE_LOCATION — baked at
#      container start, defaults to sanfrancisco).
# When FB_LOCATION_SLUG arrives empty (user has no preference saved) we
# fall back to the env default, so cold-start behaviour is unchanged.
FB_LOCATION="${FB_LOCATION_SLUG:-}"
if [ -z "$FB_LOCATION" ]; then
  FB_LOCATION="${FB_MARKETPLACE_LOCATION:-sanfrancisco}"
fi
FB_RADIUS="${FB_RADIUS_MILES:-}"

# Disable image loading by default — Marketplace DOM selectors only need
# the <img src> attribute string (not the bytes), and images are ~70% of
# the page weight. Set FB_MARKETPLACE_DISABLE_IMAGES=0 to re-enable.
DISABLE_IMAGES="${FB_MARKETPLACE_DISABLE_IMAGES:-1}"

# Proxy-bypass list. Chromium routes ALL traffic through --proxy-server
# unless a domain matches this denylist. Without it, every Chromium
# background fetch (component updater, autofill, optimization guide,
# safe-browsing, sync, reporting) burns Decodo residential-proxy
# bandwidth — observed ~15 MB/hour of "Google" bytes on the Decodo
# dashboard in 2026-04. Facebook + fbcdn MUST stay on-proxy or the
# datacenter IP is refused with /login/. See docs/SCRAPING_AGENT_ARCHITECTURE.md
# §C.11.
#
# Chromium's proxy-bypass glob only supports leading `*.` — mid-label
# wildcards like `clients*.google.com` silently don't match. So we use
# `*.google.com` as a catch-all for all google.com subdomains (fb_marketplace
# never legitimately needs google.com traffic). Same for doubleclick,
# googleusercontent, etc. Measured post-deploy: drops per-scrape cost from
# ~600 KB to ~13 KB (97.8% reduction) — see §C.11.
PROXY_BYPASS_LIST='<-loopback>;*.google.com;*.googleapis.com;*.gvt1.com;*.gstatic.com;*.google-analytics.com;*.googletagmanager.com;*.doubleclick.net;*.googleusercontent.com;*.googlevideo.com;*.ytimg.com;*.youtube.com;*.chrome.google.com;*.chromecast.com;edgedl.me.gvt1.com;redirector.gvt1.com'

# Helpers
log()  { echo "[$(date +%T)] $*" >&2; }
jitter() {
  local min_ms=$1 max_ms=$2
  local delay_ms=$((min_ms + RANDOM % (max_ms - min_ms)))
  sleep "$(echo "scale=3; $delay_ms / 1000" | bc)" 2>/dev/null || sleep 1
}

# Cleanup on exit
cleanup() {
  agent-browser close 2>/dev/null || true
  pkill -f "chromium.*--remote-debugging-port=$CDP_PORT" 2>/dev/null || true
  pkill -f "proxy_relay.py" 2>/dev/null || true
  rm -rf "$PROFILE_DIR" "$JS_FILE" 2>/dev/null || true
}
trap cleanup EXIT

# Reserve fd 3 as the real stdout and redirect fd 1 to stderr for all other commands.
exec 3>&1
exec 1>&2

# Step 0: Start proxy relay (Decodo auth handled transparently)
if [ -n "${DECODO_PROXY_USER:-}" ] && [ -n "${DECODO_PROXY_PASS:-}" ]; then
  pkill -f "proxy_relay.py" 2>/dev/null || true
  python3 /app/proxy_relay.py &
  RELAY_PID=$!
  sleep 1
  PROXY_FLAG=(
    "--proxy-server=http://127.0.0.1:$PROXY_RELAY_PORT"
    "--proxy-bypass-list=$PROXY_BYPASS_LIST"
  )
  log "Proxy relay started (pid $RELAY_PID) → Decodo residential IP"
else
  PROXY_FLAG=()
  log "WARNING: DECODO_PROXY_USER/PASS not set — running without proxy (datacenter IP will be blocked by Facebook)"
fi

# Step 1: Kill stale Chrome / agent-browser sessions
pkill -f "chromium.*--remote-debugging-port=$CDP_PORT" 2>/dev/null || true
sleep 1

# Build search URL with location slug. When the user supplied a radius
# through FB_RADIUS_MILES we append &radius=N — FB Marketplace honors it
# on the search URL the same way the in-app radius picker does.
ENCODED_QUERY=$(echo "$QUERY" | sed 's/ /+/g')
SEARCH_URL="https://www.facebook.com/marketplace/${FB_LOCATION}/search/?query=${ENCODED_QUERY}&exact=false"
if [ -n "$FB_RADIUS" ]; then
  SEARCH_URL="${SEARCH_URL}&radius=${FB_RADIUS}"
fi
log "fb_marketplace location=${FB_LOCATION} radius=${FB_RADIUS:-default}"

# Retry loop
attempt=0
while [ $attempt -lt $RETRY_MAX ]; do
  attempt=$((attempt + 1))
  PROFILE_DIR="/tmp/chrome-scrape-$(date +%s)-$attempt"
  [ $attempt -gt 1 ] && { pkill -f "chromium.*--remote-debugging-port=$CDP_PORT" 2>/dev/null || true; jitter 1500 3000; }

  # Step 2: Launch headed Chromium with anti-detection flags + proxy.
  #
  # Telemetry / background-networking kill list: every one of these flags
  # prevents a class of Chromium-internal request that would otherwise be
  # forwarded through the Decodo proxy and burn residential-proxy bandwidth.
  # Collectively they reduced the "Google domains" slice of the Decodo
  # dashboard from ~15 MB/hour to effectively 0 in 2026-04-17 scoping fix.
  # See docs/SCRAPING_AGENT_ARCHITECTURE.md §C.11.
  IMAGE_FLAG=()
  if [ "$DISABLE_IMAGES" = "1" ]; then
    IMAGE_FLAG=("--blink-settings=imagesEnabled=false")
  fi

  "$CHROMIUM" \
    --remote-debugging-port=$CDP_PORT \
    --user-data-dir="$PROFILE_DIR" \
    "${PROXY_FLAG[@]}" \
    "${IMAGE_FLAG[@]}" \
    --no-first-run \
    --no-default-browser-check \
    --disable-blink-features=AutomationControlled \
    --disable-gpu \
    --no-sandbox \
    --disable-background-networking \
    --disable-background-timer-throttling \
    --disable-backgrounding-occluded-windows \
    --disable-breakpad \
    --disable-client-side-phishing-detection \
    --disable-component-update \
    --disable-default-apps \
    --disable-domain-reliability \
    --disable-sync \
    --disable-features=OptimizationHints,OptimizationGuideModelDownloading,Translate,MediaRouter,InterestFeedContentSuggestions,CalculateNativeWinOcclusion,AutofillServerCommunication \
    --metrics-recording-only \
    --no-pings \
    --no-report-upload \
    "about:blank" &
  sleep 3

  # Step 3: Connect agent-browser to the CDP port
  agent-browser connect $CDP_PORT || { log "CDP connect failed (attempt $attempt)"; continue; }

  # Step 4: Warm up on Facebook Marketplace homepage
  jitter 800 1500
  agent-browser open "https://www.facebook.com/marketplace" || { log "Warm-up failed (attempt $attempt)"; continue; }
  agent-browser wait --load networkidle 2>/dev/null || true
  jitter 1500 3000

  # Step 5: Navigate to search page
  agent-browser open "$SEARCH_URL" || { log "Navigation failed (attempt $attempt)"; continue; }
  agent-browser wait --load networkidle 2>/dev/null || true
  jitter 1500 2500

  # Step 6: Bot detection check
  PAGE_TITLE=$(agent-browser get title 2>/dev/null || echo "")
  if echo "$PAGE_TITLE" | grep -qi "robot\|captcha\|blocked\|verify\|denied\|access denied"; then
    log "Bot detection triggered (attempt $attempt): $PAGE_TITLE"
    continue
  fi

  # Step 7: Handle login modal — HIDE with display:none (NEVER .remove())
  agent-browser eval 'document.querySelectorAll("[role=\"dialog\"]").forEach(d => d.style.display = "none"); document.body.style.overflow = "auto"' 2>/dev/null || true
  jitter 500 1000

  # Step 8: Scroll to load lazy content
  for i in 1 2 3 4 5; do
    agent-browser scroll down $((250 + RANDOM % 400)) 2>/dev/null || true
    jitter 600 1200
  done

  # Step 9: Extract via DOM eval
  cp /app/extract.js "$JS_FILE"
  sed -i "s/__MAX_LISTINGS__/$MAX_LISTINGS/g" "$JS_FILE"

  RAW_OUTPUT=$(agent-browser eval --stdin < "$JS_FILE" 2>/dev/null || echo "")

  # Validate output has content
  if [ ${#RAW_OUTPUT} -lt 10 ]; then
    log "Empty extraction output (attempt $attempt)"
    continue
  fi

  # Step 10: Unwrap agent-browser JSON string quoting and emit on fd 3.
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

# All attempts failed
log "Failed after $RETRY_MAX attempts"
echo '{"listings":[],"metadata":{"url":"","extracted_at":"","bot_detected":true}}' >&3
exit 1
