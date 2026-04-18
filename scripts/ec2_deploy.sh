#!/usr/bin/env bash
# Barkain — EC2 Container Deployment Script
# Run this ON the EC2 instance after SSH-ing in.
# Usage: bash ec2_deploy.sh [--all]
#   Default: builds + runs Amazon (8081), Best Buy (8082), Walmart (8083)
#   --all:   builds + runs all 11 retailers
set -euo pipefail

REPO_URL="https://github.com/THHUnlimted/barkain.git"
REPO_DIR="$HOME/barkain"

echo "========================================="
echo "  Barkain EC2 Container Deployment"
echo "========================================="

# ── Phase B: Install Docker + Clone ──────────────────────────────

if ! command -v docker &>/dev/null; then
    echo "[1/4] Installing Docker..."
    sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
    sudo usermod -aG docker "$USER"
    echo ""
    echo "!! Docker installed. You MUST log out and back in for group changes."
    echo "!! Run: exit"
    echo "!! Then SSH back in and re-run this script."
    exit 0
else
    echo "[1/4] Docker already installed"
fi

# Verify docker works without sudo
if ! docker info &>/dev/null; then
    echo "ERROR: Docker requires logout/login for group membership."
    echo "Run: exit, SSH back in, then re-run this script."
    exit 1
fi

if [ -d "$REPO_DIR" ]; then
    echo "[2/4] Repo exists, pulling latest..."
    cd "$REPO_DIR" && git pull
else
    echo "[2/4] Cloning repo..."
    git clone "$REPO_URL" "$REPO_DIR"
    cd "$REPO_DIR"
fi

echo "  Branch: $(git branch --show-current)"
echo "  Latest: $(git log --oneline -1)"

# ── Phase C: Build Images ───────────────────────────────────────

echo ""
echo "[3/4] Building container images..."

echo "  Building barkain-base:latest (this takes 5-10 min first time)..."
docker build -t barkain-base:latest containers/base/
echo "  Base image size: $(docker images barkain-base:latest --format '{{.Size}}')"

# Define retailers to build
if [ "${1:-}" = "--all" ]; then
    # 8086 (lowes) dropped 2026-04-18 — container deterministically hung at ~143 s
    # with 0 listings (was 2i-d-L2).
    # 8089 (sams_club) dropped 2026-04-18 — ~77 s + 1.4 MB Decodo per scan was
    # the weakest cost/benefit on the roster (vs 30 s + 17 KB on fb_marketplace,
    # sub-second on API-backed retailers).
    RETAILERS="amazon:8081 best_buy:8082 walmart:8083 target:8084 home_depot:8085 ebay_new:8087 ebay_used:8088 backmarket:8090 fb_marketplace:8091"
    echo "  Building ALL 9 retailer containers..."
else
    RETAILERS="amazon:8081 best_buy:8082 walmart:8083"
    echo "  Building 3 priority retailers (Amazon, Best Buy, Walmart)..."
fi

for pair in $RETAILERS; do
    retailer="${pair%%:*}"
    echo "  Building barkain-${retailer}..."
    docker build -t "barkain-${retailer}" "containers/${retailer}/"
done

echo ""
docker images | grep barkain

# ── Phase D: Run Containers ─────────────────────────────────────

echo ""
echo "[4/4] Starting containers..."

# Decodo residential proxy creds for IP-gated retailers (fb_marketplace).
# sams_club previously used the same path; retired 2026-04-18.
# Source from /etc/barkain-scrapers.env if it exists; otherwise rely on env
# already present in the shell. Missing creds → container runs without proxy
# and logs a warning (fb_marketplace will fail with /login/ redirect).
DECODO_ENV_FLAGS=()
if [ -f /etc/barkain-scrapers.env ]; then
    # shellcheck disable=SC1091
    set -a; . /etc/barkain-scrapers.env; set +a
fi
if [ -n "${DECODO_PROXY_USER:-}" ] && [ -n "${DECODO_PROXY_PASS:-}" ]; then
    DECODO_ENV_FLAGS=(
        -e "DECODO_PROXY_USER=$DECODO_PROXY_USER"
        -e "DECODO_PROXY_PASS=$DECODO_PROXY_PASS"
    )
fi

for pair in $RETAILERS; do
    retailer="${pair%%:*}"
    port="${pair##*:}"
    container_name="${retailer//_/}"  # remove underscores for container name

    # Stop existing container if running
    docker rm -f "$container_name" 2>/dev/null || true

    # Inject Decodo creds for retailers that route through the residential proxy.
    extra_env=()
    case "$retailer" in
        fb_marketplace)
            extra_env=("${DECODO_ENV_FLAGS[@]}")
            ;;
    esac

    echo "  Starting ${retailer} on port ${port}..."
    docker run -d \
        --name "$container_name" \
        -p "${port}:8080" \
        --restart unless-stopped \
        --memory=2g \
        --cpus=1.0 \
        "${extra_env[@]}" \
        "barkain-${retailer}"
done

echo ""
echo "Waiting 10s for Xvfb + Chromium startup..."
sleep 10

# ── Health Checks ────────────────────────────────────────────────

echo ""
echo "========================================="
echo "  Health Checks"
echo "========================================="

ALL_HEALTHY=true
for pair in $RETAILERS; do
    retailer="${pair%%:*}"
    port="${pair##*:}"

    STATUS=$(curl -s --max-time 5 "http://localhost:${port}/health" 2>/dev/null || echo '{"status":"unreachable"}')
    HEALTH=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "error")

    if [ "$HEALTH" = "healthy" ]; then
        echo "  [PASS] ${retailer} (port ${port}): healthy"
    else
        echo "  [FAIL] ${retailer} (port ${port}): ${HEALTH}"
        ALL_HEALTHY=false
    fi
done

echo ""
if [ "$ALL_HEALTHY" = true ]; then
    echo "All containers healthy! Run ec2_test_extractions.sh for live tests."
else
    echo "Some containers unhealthy. Check logs: docker logs <container_name>"
fi

# ── Post-Deploy Verification (Step 2b-final) ─────────────────────
# Compare MD5 of extract.js inside each running container against the repo
# copy so a previous `docker cp` hot-patch is visible. Fixes 2b-val-L1 where
# amazon/best_buy/walmart extract.js was hot-patched on EC2 and silently
# reverted on the next stop+start.

echo ""
echo "========================================="
echo "  Post-Deploy Verification"
echo "========================================="

for pair in $RETAILERS; do
    retailer="${pair%%:*}"
    container_name="${retailer//_/}"

    if [ ! -f "containers/${retailer}/extract.js" ]; then
        echo "  [SKIP] ${retailer}: no extract.js in repo (uses extract.sh only)"
        continue
    fi

    HASH=$(docker exec "${container_name}" md5sum /app/extract.js 2>/dev/null | cut -d' ' -f1 || echo "missing")
    LOCAL_HASH=$(md5sum "containers/${retailer}/extract.js" | cut -d' ' -f1)

    if [ "$HASH" = "$LOCAL_HASH" ]; then
        echo "  [PASS] ${retailer}: extract.js matches repo (${LOCAL_HASH:0:12})"
    else
        echo "  [WARN] ${retailer}: extract.js STALE — container=${HASH:0:12} repo=${LOCAL_HASH:0:12}"
    fi
done
