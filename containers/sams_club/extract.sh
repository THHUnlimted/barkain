#!/usr/bin/env bash
# Sam's Club extraction script — DOM eval via Decodo residential proxy.
#
# Sam's Club gates search by IP reputation: AWS datacenter IPs get redirected
# to /are-you-human?url=...&uuid=...&vid=... (Akamai-style bot interstitial).
# The homepage loads fine — it's the /s/ search path that triggers the gate.
# This script routes Chromium through a local proxy relay that injects Decodo
# credentials, giving us a US residential IP.
#
# No login required for search. Homepage warmup is load-bearing (sets session
# cookies the search page expects).
#
# Anchor selector: [data-testid="productCard"] with fallbacks in extract.js.
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

# Disable image loading by default — extract.js only reads <img src> as a
# string (not the bytes). Images are ~60% of search-page weight on samsclub.
# Set SAMS_CLUB_DISABLE_IMAGES=0 to re-enable.
DISABLE_IMAGES="${SAMS_CLUB_DISABLE_IMAGES:-1}"

# Proxy-bypass list. Chromium routes ALL traffic through --proxy-server
# unless a domain matches this denylist. Without it, every Chromium
# background fetch (component updater, autofill, optimization guide,
# safe-browsing, sync, reporting) burns Decodo residential-proxy
# bandwidth — same pattern defeated on fb_marketplace in SP-decodo-scoping
# (2026-04-17). Samsclub.com + perimeterx (px-cdn.net / px-cloud.net) MUST
# stay on-proxy — those are the IP-reputation checkpoints. Everything else
# (image CDNs, fonts, ad verification, session replay) is not IP-gated and
# can egress the datacenter IP direct for free.
#
# What MUST stay on-proxy:
#  - *.samsclub.com / www.samsclub.com — the site being scraped
#  - *.px-cdn.net / *.px-cloud.net — PerimeterX fingerprint/telemetry. Moving
#    this off-proxy would cause PX to see two different IPs (datacenter for
#    PX + residential for HTML), which almost certainly triggers the gate.
#
# What we bypass (measured 2026-04-18, ~720 KB/run of otherwise-paid bytes):
#  - *.samsclubimages.com — primary image CDN (~700 KB/run — BIGGEST saving)
#  - *.walmartimages.com — shared image CDN (Sam's Club is a Walmart subsidiary)
#  - *.typekit.net — Adobe Fonts
#  - *.doubleverify.com / tpsc-*.doubleverify.com / tps-dn-*.doubleverify.com
#    — ad viewability (not load-bearing for DOM, not IP-gated)
#  - *.quantummetric.com — session replay (not IP-gated)
#  - *.googlesyndication.com / *.adtrafficquality.google / *.safeframe.*
#    — ad inventory (also suppressed to some extent by Chromium's flags)
#  - *.crcldu.com / *.wal.co — telemetry beacons
#  - All google/gvt1/gstatic/doubleclick (same as C.11 for Chromium internals)
#
# Chromium's proxy-bypass glob only supports leading `*.` — mid-label
# wildcards like `clients*.google.com` silently don't match.
# First-party telemetry subdomains: explicit-hostname entries (Chromium's
# bypass glob doesn't match unrooted subdomains via a parent `*.samsclub.com`
# without also matching the main site). Measured 2026-04-18: these dump
# ~1.7 MB/run of analytics beacons / scene7 images / dap tag-manager
# through Decodo if left unbypassed. Samsclub does NOT fingerprint or
# IP-gate these subdomains — only *.px-cdn.net and *.px-cloud.net matter.
# Chromium bypass syntax note: `*.example.com` matches subdomains only
# (foo.example.com), NOT the bare `example.com` itself. For hosts that
# serve from both (crcldu.com / wal.co), include both forms.
PROXY_BYPASS_LIST='<-loopback>;*.google.com;*.googleapis.com;*.gvt1.com;*.gstatic.com;*.google-analytics.com;*.googletagmanager.com;*.doubleclick.net;*.googleusercontent.com;*.googlevideo.com;*.ytimg.com;*.youtube.com;*.chrome.google.com;*.chromecast.com;edgedl.me.gvt1.com;redirector.gvt1.com;*.samsclubimages.com;*.walmartimages.com;*.typekit.net;*.doubleverify.com;*.quantummetric.com;*.googlesyndication.com;*.adtrafficquality.google;*.safeframe.googlesyndication.com;*.crcldu.com;crcldu.com;*.wal.co;wal.co;beacon.samsclub.com;dap.samsclub.com;titan.samsclub.com;scene7.samsclub.com;dapglass.samsclub.com'

# Site-specific URLs
SITE_HOMEPAGE="https://www.samsclub.com"
SEARCH_URL="https://www.samsclub.com/s/$(echo "$QUERY" | sed 's/ /%20/g')"

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
  pkill -f "proxy_relay.py" 2>/dev/null || true
  rm -rf "$PROFILE_DIR" "$JS_FILE" 2>/dev/null || true
}
trap cleanup EXIT

# Reserve fd 3 as the real stdout and redirect fd 1 to stderr for all other commands.
# Why: agent-browser writes progress lines ("✓ Done", page titles, "✓ Browser closed")
# to stdout, which used to pollute the JSON we hand back to server.py and broke json.loads.
# Only the final extraction JSON should land on fd 3.
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
  log "WARNING: DECODO_PROXY_USER/PASS not set — running without proxy (datacenter IP will be gated at /are-you-human/)"
fi

# Step 1: Kill stale Chrome / agent-browser sessions
pkill -f "chromium.*--remote-debugging-port=$CDP_PORT" 2>/dev/null || true
sleep 1

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
  # Same set validated on fb_marketplace in SP-decodo-scoping (2026-04-17).
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
  sleep 1

  # Step 3: Warm up on Sam's Club homepage. Load-bearing — direct navigation
  # to /s/ without homepage cookies triggers the /are-you-human/ gate even
  # from a residential IP. Measured 2026-04-18 in SP-samsclub-decodo.
  jitter 200 400
  ab open "$SITE_HOMEPAGE" || { log "Warm-up failed (attempt $attempt)"; continue; }
  ab wait --load load 2>/dev/null || true
  jitter 500 1000

  # Step 4: Navigate to search page
  ab open "$SEARCH_URL" || { log "Navigation failed (attempt $attempt)"; continue; }
  ab wait --load load 2>/dev/null || true
  jitter 500 1000

  # Step 5: Bot detection check
  PAGE_TITLE=$(ab get title 2>/dev/null || echo "")
  if echo "$PAGE_TITLE" | grep -qi "robot\|captcha\|blocked\|verify\|denied\|access denied\|are you human"; then
    log "Bot detection triggered (attempt $attempt): $PAGE_TITLE"
    continue
  fi

  # Step 6: Handle overlays/modals (Sam's Club: none typically needed)

  # Step 7: Scroll to load lazy content (3 iterations sufficient for max_listings≤10)
  for i in 1 2 3; do
    ab scroll down $((250 + RANDOM % 400)) 2>/dev/null || true
    jitter 200 400
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

# All attempts failed
log "Failed after $RETRY_MAX attempts"
echo '{"listings":[],"metadata":{"url":"","extracted_at":"","bot_detected":true}}' >&3
exit 1
