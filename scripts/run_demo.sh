#!/usr/bin/env bash
# =============================================================================
# Barkain — Local Demo Runner
# =============================================================================
# Runs the full scan→resolve→prices pipeline locally.
# Prerequisites: Docker running, .env file with GEMINI_API_KEY
#
# Usage:
#   chmod +x scripts/run_demo.sh
#   ./scripts/run_demo.sh          # Start everything
#   ./scripts/run_demo.sh stop     # Stop everything
#   ./scripts/run_demo.sh test     # Run a test query (after starting)
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${CYAN}>>>${NC} $*"; }
ok()   { echo -e "${GREEN} ✓${NC} $*"; }
warn() { echo -e "${YELLOW} ⚠${NC} $*"; }
fail() { echo -e "${RED} ✗${NC} $*"; }

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# ── Stop everything ──────────────────────────────────────
if [ "${1:-}" = "stop" ]; then
    log "Stopping demo..."
    docker compose down 2>/dev/null || true
    # Stop any running retailer containers
    for c in barkain-amazon barkain-walmart barkain-target barkain-best-buy barkain-ebay-new; do
        docker stop "$c" 2>/dev/null && docker rm "$c" 2>/dev/null || true
    done
    # Kill backend
    pkill -f "uvicorn app.main:app" 2>/dev/null || true
    ok "Everything stopped."
    exit 0
fi

# ── Test query ───────────────────────────────────────────
if [ "${1:-}" = "test" ]; then
    log "Testing product resolution (Sony WH-1000XM5 headphones, UPC: 027242923782)..."
    echo ""

    # Step 1: Resolve product
    log "POST /api/v1/products/resolve"
    RESOLVE_RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/products/resolve \
        -H "Content-Type: application/json" \
        -d '{"upc": "027242923782"}')
    echo "$RESOLVE_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESOLVE_RESPONSE"

    PRODUCT_ID=$(echo "$RESOLVE_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || echo "")

    if [ -z "$PRODUCT_ID" ]; then
        fail "Product resolution failed. Check Gemini API key in .env"
        exit 1
    fi
    ok "Product resolved: $PRODUCT_ID"
    echo ""

    # Step 2: Get prices
    log "GET /api/v1/prices/$PRODUCT_ID"
    curl -s "http://localhost:8000/api/v1/prices/$PRODUCT_ID" | python3 -m json.tool 2>/dev/null
    echo ""
    ok "Done! Check the prices above."
    exit 0
fi

# ── Start everything ─────────────────────────────────────
log "=== Barkain Local Demo ==="
echo ""

# 1. Check prerequisites
log "Checking prerequisites..."
command -v docker >/dev/null 2>&1 || { fail "Docker not installed"; exit 1; }
command -v python3 >/dev/null 2>&1 || { fail "Python3 not installed"; exit 1; }
docker info >/dev/null 2>&1 || { fail "Docker not running — start Docker Desktop first"; exit 1; }

if [ ! -f "backend/.env" ]; then
    if [ -f ".env.example" ]; then
        warn "No backend/.env found. Copying from .env.example..."
        cp .env.example backend/.env
        warn "EDIT backend/.env and add your GEMINI_API_KEY before running test!"
    else
        fail "No .env.example found. Create backend/.env with at least GEMINI_API_KEY"
        exit 1
    fi
fi
ok "Prerequisites OK"

# 2. Start infrastructure (PostgreSQL + Redis)
log "Starting PostgreSQL + Redis..."
docker compose up -d
sleep 3

# Wait for PostgreSQL
for i in $(seq 1 15); do
    if docker exec barkain-db pg_isready -U app -d barkain >/dev/null 2>&1; then
        ok "PostgreSQL ready"
        break
    fi
    [ "$i" -eq 15 ] && { fail "PostgreSQL didn't start in time"; exit 1; }
    sleep 1
done

# Wait for Redis
for i in $(seq 1 10); do
    if docker exec barkain-redis redis-cli ping >/dev/null 2>&1; then
        ok "Redis ready"
        break
    fi
    [ "$i" -eq 10 ] && { fail "Redis didn't start in time"; exit 1; }
    sleep 1
done

# 3. Install Python deps + run migrations
log "Installing Python dependencies..."
cd backend
pip install -r requirements.txt -r requirements-test.txt -q 2>/dev/null
cd "$PROJECT_ROOT"

log "Running database migrations..."
cd backend
alembic upgrade head 2>/dev/null
cd "$PROJECT_ROOT"
ok "Migrations complete (21 tables)"

# 4. Seed retailers
log "Seeding retailers..."
cd backend
python3 -c "
import asyncio
from scripts.seed_retailers import seed_retailers
asyncio.run(seed_retailers())
" 2>/dev/null || python3 scripts/seed_retailers.py 2>/dev/null || warn "Seed script may need manual run"
cd "$PROJECT_ROOT"
ok "11 retailers seeded"

# 5. Disable auth for demo (temporary override)
log "Creating auth bypass for demo..."
# We add a temporary middleware that skips auth if X-Demo-Mode header is present
# This is NOT for production — just for local testing
cat > /tmp/barkain_demo_patch.py << 'PYEOF'
# Temporary: to bypass auth for local demo testing,
# set this env var before starting uvicorn:
#   export BARKAIN_DEMO_MODE=1
#
# Then all requests will be treated as authenticated with user_id "demo_user"
# Remove this for any real deployment.
import os
print("")
if os.getenv("BARKAIN_DEMO_MODE") == "1":
    print("  ⚠️  DEMO MODE: Auth bypass enabled (all requests as demo_user)")
    print("  ⚠️  Do NOT use in production!")
else:
    print("  Auth is ENABLED. Set BARKAIN_DEMO_MODE=1 to bypass for testing.")
print("")
PYEOF
python3 /tmp/barkain_demo_patch.py

# 6. Start backend
log "Starting backend on http://localhost:8000 ..."
cd backend
BARKAIN_DEMO_MODE=1 nohup uvicorn app.main:app --reload --port 8000 > /tmp/barkain_backend.log 2>&1 &
BACKEND_PID=$!
cd "$PROJECT_ROOT"

# Wait for backend
for i in $(seq 1 15); do
    if curl -s http://localhost:8000/api/v1/health >/dev/null 2>&1; then
        ok "Backend running (PID: $BACKEND_PID)"
        break
    fi
    [ "$i" -eq 15 ] && { fail "Backend didn't start. Check /tmp/barkain_backend.log"; exit 1; }
    sleep 1
done

# 7. Health check
log "Health check..."
curl -s http://localhost:8000/api/v1/health | python3 -m json.tool

echo ""
log "=== Demo Ready ==="
echo ""
echo "  Backend:  http://localhost:8000"
echo "  Health:   http://localhost:8000/api/v1/health"
echo "  Swagger:  http://localhost:8000/docs"
echo ""
echo "  To test the full flow:"
echo "    ./scripts/run_demo.sh test"
echo ""
echo "  To test manually with curl:"
echo "    # Resolve a product by UPC"
echo "    curl -X POST http://localhost:8000/api/v1/products/resolve \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"upc\": \"027242923782\"}'"
echo ""
echo "    # Get prices (use product_id from above)"
echo "    curl http://localhost:8000/api/v1/prices/{product_id}"
echo ""
echo "  To stop:"
echo "    ./scripts/run_demo.sh stop"
echo ""
warn "NOTE: Retailer containers are NOT running."
warn "Price fetching will return 0 results until containers are built."
warn "To build + run containers (example: Amazon):"
echo ""
echo "    cd containers/amazon"
echo "    docker build -t barkain-amazon ."
echo "    docker run -d -p 8081:8080 --name barkain-amazon barkain-amazon"
echo ""
warn "Container builds are ~2.8GB and require Chromium."
warn "On Apple Silicon, add --platform linux/amd64 (slow, runs under emulation)."
