#!/usr/bin/env bash
# Barkain — Live Extraction Test Script
# Run this ON the EC2 instance after containers are running.
# Tests real extractions against live retailer sites.
#
# IMPORTANT: Uses "max_listings" (not "max_results") — that's the actual field name.
set -euo pipefail

# Test products
PRODUCTS=(
    "Sony WH-1000XM5"
    "Apple AirPods Pro 2nd generation"
)

# Detect running containers by checking which ports respond
PORTS_TO_CHECK="amazon:8081 best_buy:8082 walmart:8083 target:8084 home_depot:8085 lowes:8086 ebay_new:8087 ebay_used:8088 sams_club:8089 backmarket:8090 fb_marketplace:8091"

ACTIVE_RETAILERS=""
for pair in $PORTS_TO_CHECK; do
    retailer="${pair%%:*}"
    port="${pair##*:}"
    if curl -s --max-time 2 "http://localhost:${port}/health" &>/dev/null; then
        ACTIVE_RETAILERS="$ACTIVE_RETAILERS $pair"
    fi
done

if [ -z "$ACTIVE_RETAILERS" ]; then
    echo "ERROR: No containers responding. Run ec2_deploy.sh first."
    exit 1
fi

echo "========================================="
echo "  Barkain Live Extraction Tests"
echo "========================================="
echo "Active containers:$(echo "$ACTIVE_RETAILERS" | sed 's/:[0-9]*//g')"
echo ""

PASS=0
FAIL=0
RESULTS=""

for product in "${PRODUCTS[@]}"; do
    echo "--- Testing: ${product} ---"
    echo ""

    for pair in $ACTIVE_RETAILERS; do
        retailer="${pair%%:*}"
        port="${pair##*:}"

        echo -n "  ${retailer} (port ${port}): "

        RESPONSE=$(curl -s --max-time 45 -X POST "http://localhost:${port}/extract" \
            -H "Content-Type: application/json" \
            -d "{\"query\": \"${product}\", \"max_listings\": 3}" 2>/dev/null || echo '{"error":{"code":"CURL_FAILED"}}')

        # Check for listings
        LISTING_COUNT=$(echo "$RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    listings = data.get('listings', [])
    print(len(listings))
except:
    print(0)
" 2>/dev/null || echo "0")

        # Check for error
        ERROR_CODE=$(echo "$RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    err = data.get('error')
    print(err.get('code', '') if err else '')
except:
    print('PARSE_FAILED')
" 2>/dev/null || echo "PARSE_FAILED")

        # Check for bot detection
        BOT_DETECTED=$(echo "$RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('metadata', {}).get('bot_detected', False))
except:
    print('unknown')
" 2>/dev/null || echo "unknown")

        # Check first listing price
        FIRST_PRICE=$(echo "$RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    listings = data.get('listings', [])
    if listings:
        print(listings[0].get('price', 0))
    else:
        print(0)
except:
    print(0)
" 2>/dev/null || echo "0")

        if [ "$LISTING_COUNT" -gt 0 ] && [ "$FIRST_PRICE" != "0" ]; then
            echo "PASS (${LISTING_COUNT} listings, first price: \$${FIRST_PRICE})"
            PASS=$((PASS + 1))
            RESULTS="${RESULTS}\n| ${retailer} | ${product} | PASS | ${LISTING_COUNT} | \$${FIRST_PRICE} | |"
        elif [ "$BOT_DETECTED" = "True" ]; then
            echo "FAIL — bot detected"
            FAIL=$((FAIL + 1))
            RESULTS="${RESULTS}\n| ${retailer} | ${product} | BLOCKED | 0 | - | Bot detection triggered |"
        elif [ -n "$ERROR_CODE" ] && [ "$ERROR_CODE" != "" ]; then
            echo "FAIL — ${ERROR_CODE}"
            FAIL=$((FAIL + 1))
            RESULTS="${RESULTS}\n| ${retailer} | ${product} | FAIL | 0 | - | ${ERROR_CODE} |"
        else
            echo "FAIL — 0 listings or \$0 price"
            FAIL=$((FAIL + 1))
            RESULTS="${RESULTS}\n| ${retailer} | ${product} | FAIL | ${LISTING_COUNT} | \$${FIRST_PRICE} | Empty or zero-price listings |"
        fi
    done
    echo ""
done

# ── Summary ──────────────────────────────────────────────────────

TOTAL=$((PASS + FAIL))

echo "========================================="
echo "  Results: ${PASS}/${TOTAL} passed"
echo "========================================="
echo ""
echo "| Retailer | Product | Status | Listings | Price | Notes |"
echo "|----------|---------|--------|----------|-------|-------|"
echo -e "$RESULTS"
echo ""

if [ "$FAIL" -gt 0 ]; then
    echo "Some extractions failed. Check individual responses:"
    echo "  curl -s -X POST http://localhost:<PORT>/extract \\"
    echo "    -H 'Content-Type: application/json' \\"
    echo "    -d '{\"query\": \"Sony WH-1000XM5\", \"max_listings\": 3}' | python3 -m json.tool"
fi
