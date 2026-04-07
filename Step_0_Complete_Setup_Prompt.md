# Barkain — Step 0: Complete Infrastructure Setup

> **Paste this entire prompt into Claude Code.**
> **Platform:** macOS
> **Repo location:** `/Desktop/BarkainApp/Barkain/` (Xcode project already exists here)
> **Time estimate:** ~20 min for agent work + Mike's manual tasks afterward

---

## MASTER INSTRUCTIONS

You are setting up the Barkain development environment on Mike's Mac. The Xcode project already exists at `/Desktop/BarkainApp/Barkain/` — that directory IS the repo root. Do NOT create a new directory or move anything.

**Your workflow:**

1. **AUDIT FIRST** — Check every tool, file, directory, service, and config that should exist. Report what's already done vs what's missing. Do NOT install or create anything during the audit.
2. **FIX GAPS** — Install missing CLI tools, create missing directories, create missing files, start Docker if needed. Only touch what's actually missing.
3. **VERIFY EVERYTHING** — Run comprehensive verification of all tools, containers, files, env vars, git status, and MCP readiness.
4. **REPORT** — Output a structured summary: what was already done, what the agent completed, and what Mike must do manually (with exact step-by-step instructions).

**Rules:**
- Work inside `/Desktop/BarkainApp/Barkain/` for everything
- NEVER overwrite files that already exist and have content (ask first)
- If a tool is already installed, skip it — don't reinstall
- If Docker containers are already running, don't restart them
- If `.env` already has real keys filled in, don't touch those values
- The Xcode project (`Barkain.xcodeproj`, `Barkain/`, `BarkainTests/`, `BarkainUITests/`) was created by Mike in Xcode — never modify these

---

## PHASE 1: FULL AUDIT (Do NOT change anything yet)

Run every single check below and collect results before taking any action.

### 1A. CLI Tools Audit

Check each tool individually. Record version if found, or "MISSING" if not.

```bash
echo "╔══════════════════════════════════════════╗"
echo "║     BARKAIN STEP 0 — FULL AUDIT          ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "═══ 1A. CLI TOOLS ═══"
echo ""

# Core tools
echo -n "Homebrew:      "; brew --version 2>/dev/null | head -1 || echo "MISSING"
echo -n "Git:           "; git --version 2>/dev/null || echo "MISSING"
echo -n "GitHub CLI:    "; gh --version 2>/dev/null | head -1 || echo "MISSING"
echo -n "Python3:       "; python3 --version 2>/dev/null || echo "MISSING"
echo -n "pip3:          "; pip3 --version 2>/dev/null | head -1 || echo "MISSING"
echo -n "Node.js:       "; node --version 2>/dev/null || echo "MISSING (needed for MCP servers)"
echo -n "npm:           "; npm --version 2>/dev/null || echo "MISSING (needed for MCP servers)"
echo -n "npx:           "; npx --version 2>/dev/null || echo "MISSING (needed for MCP servers)"

# Docker
echo ""
echo -n "Docker:        "; docker --version 2>/dev/null || echo "MISSING"
echo -n "Docker Compose:"; docker compose version 2>/dev/null || echo "MISSING"
echo -n "Docker Daemon: "; docker info >/dev/null 2>&1 && echo "RUNNING" || echo "NOT RUNNING"

# Dev tools
echo ""
echo -n "jq:            "; jq --version 2>/dev/null || echo "MISSING"
echo -n "xcodes:        "; xcodes version 2>/dev/null || echo "MISSING"
echo -n "swiftlint:     "; swiftlint --version 2>/dev/null || echo "MISSING"
echo -n "ruff:          "; ruff --version 2>/dev/null || echo "MISSING"
echo -n "alembic:       "; alembic --version 2>/dev/null | head -1 || echo "MISSING"
echo -n "pytest:        "; pytest --version 2>/dev/null | head -1 || echo "MISSING"

# Xcode
echo ""
echo -n "Xcode:         "; xcodebuild -version 2>/dev/null | head -1 || echo "MISSING"
echo -n "xcode-select:  "; xcode-select -p 2>/dev/null || echo "NOT CONFIGURED"
echo -n "Swift:         "; swift --version 2>/dev/null | head -1 || echo "MISSING"
```

### 1B. Repo & File Structure Audit

```bash
echo ""
echo "═══ 1B. REPO & FILE STRUCTURE ═══"
echo ""

cd /Desktop/BarkainApp/Barkain/ 2>/dev/null || { echo "❌ REPO DIRECTORY NOT FOUND at /Desktop/BarkainApp/Barkain/"; exit 1; }

# Git
echo -n "Git repo initialized: "; [ -d .git ] && echo "YES" || echo "NO"
echo -n "Git remote:           "; git remote get-url origin 2>/dev/null || echo "NONE"
echo -n "Branch:               "; git branch --show-current 2>/dev/null || echo "N/A"

echo ""
echo "--- Root-level files ---"
[ -f CLAUDE.md ]           && echo "  ✅ CLAUDE.md" || echo "  ❌ CLAUDE.md MISSING"
[ -f docker-compose.yml ]  && echo "  ✅ docker-compose.yml" || echo "  ❌ docker-compose.yml MISSING"
[ -f .env.example ]        && echo "  ✅ .env.example" || echo "  ❌ .env.example MISSING"
[ -f .env ]                && echo "  ✅ .env" || echo "  ❌ .env MISSING"
[ -f .gitignore ]          && echo "  ✅ .gitignore" || echo "  ❌ .gitignore MISSING"

echo ""
echo "--- Xcode project (should already exist from Xcode) ---"
[ -f Barkain.xcodeproj/project.pbxproj ] && echo "  ✅ Barkain.xcodeproj" || echo "  ❌ Barkain.xcodeproj MISSING"
[ -d Barkain ]             && echo "  ✅ Barkain/ (iOS source)" || echo "  ❌ Barkain/ MISSING"
[ -d BarkainTests ]        && echo "  ✅ BarkainTests/" || echo "  ❌ BarkainTests/ MISSING"
[ -d BarkainUITests ]      && echo "  ✅ BarkainUITests/" || echo "  ❌ BarkainUITests/ MISSING"

echo ""
echo "--- docs/ directory ---"
[ -d docs ] && echo "  ✅ docs/ exists" || echo "  ❌ docs/ MISSING"
for doc in ARCHITECTURE AUTH_SECURITY CARD_REWARDS COMPONENT_MAP DATA_MODEL DEPLOYMENT FEATURES IDENTITY_DISCOUNTS PHASES SCRAPING_AGENT_ARCHITECTURE SEARCH_STRATEGY TESTING; do
  [ -f "docs/${doc}.md" ] && echo "    ✅ ${doc}.md" || echo "    ❌ ${doc}.md MISSING"
done

echo ""
echo "--- Backend & other directories ---"
[ -d backend ]                && echo "  ✅ backend/" || echo "  ❌ backend/ MISSING"
[ -d backend/app ]            && echo "    ✅ backend/app/" || echo "    ❌ backend/app/ MISSING"
[ -d backend/modules ]        && echo "    ✅ backend/modules/" || echo "    ❌ backend/modules/ MISSING"
[ -d backend/ai ]             && echo "    ✅ backend/ai/" || echo "    ❌ backend/ai/ MISSING"
[ -d backend/ai/prompts ]     && echo "    ✅ backend/ai/prompts/" || echo "    ❌ backend/ai/prompts/ MISSING"
[ -d backend/workers ]        && echo "    ✅ backend/workers/" || echo "    ❌ backend/workers/ MISSING"
[ -d backend/tests ]          && echo "    ✅ backend/tests/" || echo "    ❌ backend/tests/ MISSING"
[ -d backend/tests/modules ]  && echo "    ✅ backend/tests/modules/" || echo "    ❌ backend/tests/modules/ MISSING"
[ -d backend/tests/fixtures ] && echo "    ✅ backend/tests/fixtures/" || echo "    ❌ backend/tests/fixtures/ MISSING"
[ -d containers ]             && echo "  ✅ containers/" || echo "  ❌ containers/ MISSING"
[ -d infrastructure ]         && echo "  ✅ infrastructure/" || echo "  ❌ infrastructure/ MISSING"
[ -d infrastructure/migrations ] && echo "    ✅ infrastructure/migrations/" || echo "    ❌ infrastructure/migrations/ MISSING"
[ -d infrastructure/terraform ]  && echo "    ✅ infrastructure/terraform/" || echo "    ❌ infrastructure/terraform/ MISSING"
[ -d scripts ]                && echo "  ✅ scripts/" || echo "  ❌ scripts/ MISSING"
[ -d prototype ]              && echo "  ✅ prototype/" || echo "  ❌ prototype/ MISSING"
```

### 1C. Docker Containers Audit

```bash
echo ""
echo "═══ 1C. DOCKER CONTAINERS ═══"
echo ""

if docker info >/dev/null 2>&1; then
  echo "Docker daemon: RUNNING"
  echo ""
  
  # Check if containers exist (running or stopped)
  echo "--- Container status ---"
  docker ps -a --filter "name=barkain-db$" --format "  barkain-db:       {{.Status}}" 2>/dev/null || echo "  barkain-db:       NOT FOUND"
  docker ps -a --filter "name=barkain-db-test" --format "  barkain-db-test:  {{.Status}}" 2>/dev/null || echo "  barkain-db-test:  NOT FOUND"
  docker ps -a --filter "name=barkain-redis" --format "  barkain-redis:    {{.Status}}" 2>/dev/null || echo "  barkain-redis:    NOT FOUND"
  
  echo ""
  echo "--- Service connectivity ---"
  docker exec barkain-db psql -U app -d barkain -c "SELECT 1;" >/dev/null 2>&1 && echo "  ✅ PostgreSQL main: CONNECTED" || echo "  ❌ PostgreSQL main: CANNOT CONNECT"
  docker exec barkain-db-test psql -U app -d barkain_test -c "SELECT 1;" >/dev/null 2>&1 && echo "  ✅ PostgreSQL test: CONNECTED" || echo "  ❌ PostgreSQL test: CANNOT CONNECT"
  docker exec barkain-redis redis-cli ping >/dev/null 2>&1 && echo "  ✅ Redis: CONNECTED (PONG)" || echo "  ❌ Redis: CANNOT CONNECT"
  
  echo ""
  echo "--- TimescaleDB extension ---"
  docker exec barkain-db psql -U app -d barkain -t -c "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb';" 2>/dev/null | tr -d '[:space:]' | grep -q "." && echo "  ✅ TimescaleDB enabled (main): $(docker exec barkain-db psql -U app -d barkain -t -c "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb';" 2>/dev/null | tr -d '[:space:]')" || echo "  ❌ TimescaleDB NOT enabled (main)"
  docker exec barkain-db-test psql -U app -d barkain_test -t -c "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb';" 2>/dev/null | tr -d '[:space:]' | grep -q "." && echo "  ✅ TimescaleDB enabled (test): $(docker exec barkain-db-test psql -U app -d barkain_test -t -c "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb';" 2>/dev/null | tr -d '[:space:]')" || echo "  ❌ TimescaleDB NOT enabled (test)"
else
  echo "❌ Docker daemon NOT RUNNING — cannot check containers"
fi
```

### 1D. Environment Variables Audit

```bash
echo ""
echo "═══ 1D. ENVIRONMENT VARIABLES (.env) ═══"
echo ""

cd /Desktop/BarkainApp/Barkain/

if [ -f .env ]; then
  echo ".env file: EXISTS"
  echo ""
  
  echo "--- Phase 1 CRITICAL keys ---"
  
  # Check each key: is it present AND not a placeholder?
  check_key() {
    local key=$1
    local placeholder=$2
    local label=$3
    if grep -q "^${key}=" .env 2>/dev/null; then
      local val=$(grep "^${key}=" .env | cut -d'=' -f2-)
      if [ -z "$val" ] || [ "$val" = "$placeholder" ] || [ "$val" = "xxxxx" ]; then
        echo "  ⚠️  ${label}: PLACEHOLDER (needs real value)"
      else
        echo "  ✅ ${label}: SET (value present)"
      fi
    else
      echo "  ❌ ${label}: KEY MISSING from .env"
    fi
  }
  
  check_key "CLERK_SECRET_KEY" "sk_test_xxxxx" "CLERK_SECRET_KEY"
  check_key "CLERK_PUBLISHABLE_KEY" "pk_test_xxxxx" "CLERK_PUBLISHABLE_KEY"
  check_key "GEMINI_API_KEY" "xxxxx" "GEMINI_API_KEY"
  check_key "UPCITEMDB_API_KEY" "xxxxx" "UPCITEMDB_API_KEY"
  
  echo ""
  echo "--- Phase 1 NICE-TO-HAVE keys ---"
  check_key "ANTHROPIC_API_KEY" "sk-ant-xxxxx" "ANTHROPIC_API_KEY"
  check_key "OPENAI_API_KEY" "sk-xxxxx" "OPENAI_API_KEY"
  
  echo ""
  echo "--- Phase 4 production optimization keys (NOT blocking) ---"
  check_key "BEST_BUY_API_KEY" "xxxxx" "BEST_BUY_API_KEY"
  check_key "EBAY_CLIENT_ID" "xxxxx" "EBAY_CLIENT_ID"
  check_key "EBAY_CLIENT_SECRET" "xxxxx" "EBAY_CLIENT_SECRET"
  check_key "KEEPA_API_KEY" "xxxxx" "KEEPA_API_KEY"
  
  echo ""
  echo "--- Affiliate keys (NOT blocking) ---"
  check_key "AMAZON_ASSOCIATE_TAG" "" "AMAZON_ASSOCIATE_TAG"
  check_key "EBAY_CAMPAIGN_ID" "" "EBAY_CAMPAIGN_ID"
  check_key "CJ_WEBSITE_ID" "" "CJ_WEBSITE_ID"
  
  echo ""
  echo "--- Infrastructure keys (should have defaults) ---"
  check_key "DATABASE_URL" "" "DATABASE_URL"
  check_key "TEST_DATABASE_URL" "" "TEST_DATABASE_URL"
  check_key "REDIS_URL" "" "REDIS_URL"
  check_key "ENVIRONMENT" "" "ENVIRONMENT"
  
else
  echo "❌ .env file: DOES NOT EXIST"
fi
```

### 1E. GitHub Auth Audit

```bash
echo ""
echo "═══ 1E. GITHUB AUTH ═══"
echo ""
gh auth status 2>&1 || echo "❌ Not authenticated with GitHub CLI"
```

### 1F. MCP Server Readiness Audit

```bash
echo ""
echo "═══ 1F. MCP SERVER READINESS ═══"
echo ""

# Check if the packages the MCP servers need are available
echo "--- npm packages (can MCP servers run?) ---"
echo -n "  @modelcontextprotocol/server-postgres: "; npx --yes @modelcontextprotocol/server-postgres --help >/dev/null 2>&1 && echo "AVAILABLE" || echo "will install on first use (npx)"
echo -n "  @upstash/context7-mcp:                 "; npx --yes @upstash/context7-mcp --help >/dev/null 2>&1 && echo "AVAILABLE" || echo "will install on first use (npx)"

# Check Claude Code config locations
echo ""
echo "--- Claude Code config file locations ---"
[ -f ~/.claude.json ] && echo "  ✅ ~/.claude.json EXISTS" || echo "  ❌ ~/.claude.json NOT FOUND"
[ -f ~/.claude/claude_desktop_config.json ] && echo "  ✅ ~/.claude/claude_desktop_config.json EXISTS" || echo "  ❌ ~/.claude/claude_desktop_config.json NOT FOUND"
[ -d ~/.claude ] && echo "  ✅ ~/.claude/ directory EXISTS" || echo "  ❌ ~/.claude/ directory NOT FOUND"

# Check for project-level MCP config
[ -f /Desktop/BarkainApp/Barkain/.mcp.json ] && echo "  ✅ .mcp.json (project-level) EXISTS" || echo "  ℹ️  .mcp.json (project-level) not found — can create one"

# Check if xcodebuildmcp is installed
echo ""
echo -n "  XcodeBuildMCP: "; which xcodebuildmcp >/dev/null 2>&1 && echo "INSTALLED" || echo "NOT INSTALLED (needed for Step 1g)"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║           AUDIT COMPLETE                  ║"
echo "║     Review results above, then proceed    ║"
echo "╚══════════════════════════════════════════╝"
```

---

## PHASE 2: FIX ALL GAPS

Now that the audit is complete, fix everything that was missing. **Only act on items that showed MISSING/NOT FOUND/NOT RUNNING in the audit.**

### 2A. Install Missing CLI Tools

```
FOR EACH TOOL THAT SHOWED "MISSING" IN THE AUDIT:

Homebrew tools (install via `brew install <name>`):
  - gh (GitHub CLI)
  - jq
  - xcodes
  - swiftlint
  - node (if missing — needed for MCP servers via npx)

pip tools (install via `pip3 install <name>`):
  - ruff
  - alembic
  - pytest

DO NOT install:
  - Docker Desktop (requires GUI — flag for Mike)
  - Xcode (requires App Store — flag for Mike)
  - Homebrew itself (requires manual install — flag for Mike)

After installing, re-run the version check for each tool you installed to confirm it works.
```

### 2B. Initialize Git Repo (if not already initialized)

```bash
cd /Desktop/BarkainApp/Barkain/

# Only if .git doesn't exist
if [ ! -d .git ]; then
  git init
  echo "Initialized git repo"
fi

# Only if no remote is configured
if ! git remote get-url origin >/dev/null 2>&1; then
  echo "⚠️ No git remote configured."
  echo "   Mike needs to either:"
  echo "   1. Run: gh repo create barkain --private --source=. --push"
  echo "   2. Or: git remote add origin git@github.com:USERNAME/barkain.git"
fi
```

### 2C. Create Missing Root Files

**Only create files that showed MISSING in the audit.** Do NOT overwrite existing files.

If `.gitignore` is MISSING, create it with this exact content:
```
# ── Environment ───────────────────────────────────
.env
.env.local
.env.production

# ── Python ────────────────────────────────────────
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.venv/
venv/
*.egg

# ── iOS / Xcode ──────────────────────────────────
Barkain.xcodeproj/xcuserdata/
Barkain.xcodeproj/project.xcworkspace/xcuserdata/
*.xcuserstate
DerivedData/
build/
*.ipa
*.dSYM.zip
*.dSYM
Config/Secrets.xcconfig

# ── IDE ──────────────────────────────────────────
.idea/
.vscode/
*.swp
*.swo
*~
.DS_Store

# ── Docker ───────────────────────────────────────
# Don't ignore docker-compose.yml — it's committed

# ── Testing ──────────────────────────────────────
.coverage
htmlcov/
.pytest_cache/
TestResults.xcresult

# ── Prompt Packages (NOT in repo) ────────────────
prompts/

# ── Misc ─────────────────────────────────────────
*.log
tmp/
```

If `docker-compose.yml` is MISSING, create it with this exact content:
```yaml
version: "3.9"

services:
  postgres:
    image: timescale/timescaledb:latest-pg16
    container_name: barkain-db
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: barkain
      POSTGRES_USER: app
      POSTGRES_PASSWORD: localdev
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d barkain"]
      interval: 5s
      timeout: 3s
      retries: 5

  postgres-test:
    image: timescale/timescaledb:latest-pg16
    container_name: barkain-db-test
    ports:
      - "5433:5432"
    environment:
      POSTGRES_DB: barkain_test
      POSTGRES_USER: app
      POSTGRES_PASSWORD: test
    tmpfs:
      - /var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d barkain_test"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: barkain-redis
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  pgdata:
```

If `.env.example` is MISSING, create it with this exact content:
```
# Barkain — Environment Variables
# Copy to .env and fill in real values
# NEVER commit .env to git

# ── Database ─────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://app:localdev@localhost:5432/barkain
TEST_DATABASE_URL=postgresql+asyncpg://app:test@localhost:5433/barkain_test

# ── Cache ────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0

# ── Auth (Clerk) ─────────────────────────────────────
CLERK_SECRET_KEY=sk_test_xxxxx
CLERK_PUBLISHABLE_KEY=pk_test_xxxxx

# ── Retail Data APIs (Phase 4 production optimization) ─
BEST_BUY_API_KEY=xxxxx
EBAY_CLIENT_ID=xxxxx
EBAY_CLIENT_SECRET=xxxxx
KEEPA_API_KEY=xxxxx

# ── UPC Resolution (Phase 1) ──────────────────────────
GEMINI_API_KEY=xxxxx
UPCITEMDB_API_KEY=xxxxx

# ── AI Models (Phase 3: recommendations, fallback) ───
ANTHROPIC_API_KEY=sk-ant-xxxxx
OPENAI_API_KEY=sk-xxxxx

# ── Affiliate (Phase 2 — leave blank until approved) ─
AMAZON_ASSOCIATE_TAG=
EBAY_CAMPAIGN_ID=
CJ_WEBSITE_ID=

# ── Environment ──────────────────────────────────────
ENVIRONMENT=development
LOG_LEVEL=DEBUG
CORS_ORIGINS=http://localhost:3000,http://localhost:8000

# ── Rate Limiting ────────────────────────────────────
RATE_LIMIT_GENERAL=60
RATE_LIMIT_WRITE=30
RATE_LIMIT_AI=10
```

If `.env` is MISSING (but `.env.example` exists), create it:
```bash
cp .env.example .env
echo "Created .env from .env.example — Mike needs to fill in real keys"
```

If `.env` already EXISTS, do NOT overwrite it. Only check if it's missing keys compared to `.env.example` and report which keys are missing.

### 2D. Create Missing Directories

Only create directories that showed MISSING in the audit:

```bash
cd /Desktop/BarkainApp/Barkain/

# Create only if missing (mkdir -p is safe — won't error on existing)
mkdir -p docs
mkdir -p backend/app
mkdir -p backend/modules
mkdir -p backend/ai/prompts
mkdir -p backend/workers
mkdir -p backend/tests/modules
mkdir -p backend/tests/fixtures
mkdir -p containers
mkdir -p infrastructure/migrations
mkdir -p infrastructure/terraform
mkdir -p scripts
mkdir -p prototype
```

### 2E. Check & Report on docs/ Files

The 12 guiding docs + CLAUDE.md should already be placed by Mike. If any are missing, report exactly which ones and remind Mike to copy them from the downloaded files.

```
If ANY docs are missing, output this message:

"The following guiding docs are missing from your repo. Copy them from the 
downloaded barkain-repo-files folder:

  MISSING_FILE → /Desktop/BarkainApp/Barkain/docs/MISSING_FILE
  (or CLAUDE.md → /Desktop/BarkainApp/Barkain/CLAUDE.md)

These are BLOCKERS for Step 1a. The coding agent reads these docs to understand
the project architecture."
```

### 2F. Start Docker Containers (if not running)

```bash
cd /Desktop/BarkainApp/Barkain/

# Only start if Docker daemon is running but containers aren't
if docker info >/dev/null 2>&1; then
  # Check if all 3 containers are running
  RUNNING=$(docker ps --filter "name=barkain" --format "{{.Names}}" | wc -l | tr -d ' ')
  
  if [ "$RUNNING" -lt 3 ]; then
    echo "Starting Docker containers..."
    docker compose up -d
    
    echo "Waiting 15 seconds for containers to initialize..."
    sleep 15
    
    # Enable TimescaleDB on both postgres instances
    echo "Enabling TimescaleDB extension..."
    docker exec barkain-db psql -U app -d barkain -c "CREATE EXTENSION IF NOT EXISTS timescaledb;" 2>/dev/null
    docker exec barkain-db-test psql -U app -d barkain_test -c "CREATE EXTENSION IF NOT EXISTS timescaledb;" 2>/dev/null
    
    echo "Containers started."
  else
    echo "All 3 containers already running — skipping."
    
    # Still ensure TimescaleDB is enabled even if containers were already running
    docker exec barkain-db psql -U app -d barkain -c "CREATE EXTENSION IF NOT EXISTS timescaledb;" 2>/dev/null
    docker exec barkain-db-test psql -U app -d barkain_test -c "CREATE EXTENSION IF NOT EXISTS timescaledb;" 2>/dev/null
  fi
else
  echo "❌ Docker daemon is NOT running."
  echo "   🧑 MIKE: Open Docker Desktop and wait for it to fully start, then re-run this prompt."
fi
```

### 2G. Create Project-Level MCP Config (if not exists)

Claude Code supports a `.mcp.json` file at the project root for project-specific MCP servers. Create it if it doesn't exist:

```bash
cd /Desktop/BarkainApp/Barkain/

if [ ! -f .mcp.json ]; then
cat > .mcp.json << 'MCPEOF'
{
  "mcpServers": {
    "postgresql": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://app:localdev@localhost:5432/barkain"]
    },
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp"]
    }
  }
}
MCPEOF
  echo "Created .mcp.json with PostgreSQL and Context7 MCP servers"
  echo "⚠️ Mike still needs to configure Redis MCP, Clerk MCP, and XcodeBuildMCP"
else
  echo ".mcp.json already exists — not overwriting"
  echo "Current contents:"
  cat .mcp.json
fi
```

---

## PHASE 3: COMPREHENSIVE VERIFICATION

Re-run every check to confirm the gaps are fixed.

```bash
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   BARKAIN STEP 0 — FINAL VERIFICATION        ║"
echo "╚══════════════════════════════════════════════╝"

cd /Desktop/BarkainApp/Barkain/

echo ""
echo "═══ CLI TOOLS (all should show versions) ═══"
echo -n "  brew:       "; brew --version 2>/dev/null | head -1 || echo "❌ MISSING"
echo -n "  git:        "; git --version 2>/dev/null || echo "❌ MISSING"
echo -n "  gh:         "; gh --version 2>/dev/null | head -1 || echo "❌ MISSING"
echo -n "  python3:    "; python3 --version 2>/dev/null || echo "❌ MISSING"
echo -n "  node:       "; node --version 2>/dev/null || echo "❌ MISSING"
echo -n "  npm:        "; npm --version 2>/dev/null || echo "❌ MISSING"
echo -n "  docker:     "; docker --version 2>/dev/null || echo "❌ MISSING"
echo -n "  compose:    "; docker compose version 2>/dev/null || echo "❌ MISSING"
echo -n "  jq:         "; jq --version 2>/dev/null || echo "❌ MISSING"
echo -n "  xcodes:     "; xcodes version 2>/dev/null || echo "❌ MISSING"
echo -n "  swiftlint:  "; swiftlint --version 2>/dev/null || echo "❌ MISSING"
echo -n "  ruff:       "; ruff --version 2>/dev/null || echo "❌ MISSING"
echo -n "  alembic:    "; alembic --version 2>/dev/null | head -1 || echo "❌ MISSING"
echo -n "  pytest:     "; pytest --version 2>/dev/null | head -1 || echo "❌ MISSING"
echo -n "  xcodebuild: "; xcodebuild -version 2>/dev/null | head -1 || echo "❌ MISSING"
echo -n "  swift:      "; swift --version 2>/dev/null | head -1 || echo "❌ MISSING"

echo ""
echo "═══ DOCKER CONTAINERS ═══"
docker compose ps 2>/dev/null || echo "❌ Cannot check containers"
echo ""
docker exec barkain-db psql -U app -d barkain -c "SELECT 'PostgreSQL main: OK';" 2>/dev/null | grep OK || echo "  ❌ PostgreSQL main: FAILED"
docker exec barkain-db-test psql -U app -d barkain_test -c "SELECT 'PostgreSQL test: OK';" 2>/dev/null | grep OK || echo "  ❌ PostgreSQL test: FAILED"
docker exec barkain-redis redis-cli ping 2>/dev/null | grep PONG && echo "  Redis: PONG ✅" || echo "  ❌ Redis: FAILED"
echo ""
echo "TimescaleDB:"
docker exec barkain-db psql -U app -d barkain -t -c "SELECT 'main: v' || extversion FROM pg_extension WHERE extname = 'timescaledb';" 2>/dev/null | tr -d '[:space:]' || echo "  ❌ Not enabled (main)"
docker exec barkain-db-test psql -U app -d barkain_test -t -c "SELECT 'test: v' || extversion FROM pg_extension WHERE extname = 'timescaledb';" 2>/dev/null | tr -d '[:space:]' || echo "  ❌ Not enabled (test)"

echo ""
echo "═══ REPO STRUCTURE ═══"
for item in CLAUDE.md docker-compose.yml .env.example .env .gitignore; do
  [ -f "$item" ] && echo "  ✅ $item" || echo "  ❌ $item"
done
[ -f Barkain.xcodeproj/project.pbxproj ] && echo "  ✅ Barkain.xcodeproj" || echo "  ❌ Barkain.xcodeproj"
for dir in docs backend containers infrastructure/migrations scripts prototype Barkain BarkainTests BarkainUITests; do
  [ -d "$dir" ] && echo "  ✅ $dir/" || echo "  ❌ $dir/"
done

echo ""
echo "═══ GUIDING DOCS (12 required) ═══"
DOCS_FOUND=0
DOCS_MISSING=0
for doc in ARCHITECTURE AUTH_SECURITY CARD_REWARDS COMPONENT_MAP DATA_MODEL DEPLOYMENT FEATURES IDENTITY_DISCOUNTS PHASES SCRAPING_AGENT_ARCHITECTURE SEARCH_STRATEGY TESTING; do
  if [ -f "docs/${doc}.md" ]; then
    echo "  ✅ ${doc}.md"
    DOCS_FOUND=$((DOCS_FOUND + 1))
  else
    echo "  ❌ ${doc}.md MISSING"
    DOCS_MISSING=$((DOCS_MISSING + 1))
  fi
done
echo "  Found: $DOCS_FOUND/12"

echo ""
echo "═══ .env KEY STATUS ═══"
if [ -f .env ]; then
  # Function to check key
  check_final() {
    local key=$1
    local label=$2
    local val=$(grep "^${key}=" .env 2>/dev/null | cut -d'=' -f2-)
    if [ -z "$val" ] || [ "$val" = "xxxxx" ] || [ "$val" = "sk_test_xxxxx" ] || [ "$val" = "pk_test_xxxxx" ] || [ "$val" = "sk-ant-xxxxx" ] || [ "$val" = "sk-xxxxx" ]; then
      echo "  ⚠️  $label — needs real value"
    else
      echo "  ✅ $label — set"
    fi
  }
  
  echo "  Phase 1 Critical:"
  check_final "CLERK_SECRET_KEY" "CLERK_SECRET_KEY"
  check_final "CLERK_PUBLISHABLE_KEY" "CLERK_PUBLISHABLE_KEY"
  check_final "GEMINI_API_KEY" "GEMINI_API_KEY"
  check_final "UPCITEMDB_API_KEY" "UPCITEMDB_API_KEY"
  echo "  Phase 1 Nice-to-have:"
  check_final "ANTHROPIC_API_KEY" "ANTHROPIC_API_KEY"
  check_final "OPENAI_API_KEY" "OPENAI_API_KEY"
  echo "  Phase 4 (not blocking):"
  check_final "BEST_BUY_API_KEY" "BEST_BUY_API_KEY"
  check_final "EBAY_CLIENT_ID" "EBAY_CLIENT_ID"
  check_final "KEEPA_API_KEY" "KEEPA_API_KEY"
else
  echo "  ❌ .env file missing!"
fi

echo ""
echo "═══ GIT STATUS ═══"
echo -n "  Remote: "; git remote get-url origin 2>/dev/null || echo "NONE"
echo -n "  Branch: "; git branch --show-current 2>/dev/null || echo "N/A"
echo -n "  Commits: "; git log --oneline 2>/dev/null | wc -l | tr -d ' '
echo -n "  Clean: "; git status --porcelain 2>/dev/null | wc -l | tr -d ' '; echo " uncommitted changes"

echo ""
echo "═══ MCP CONFIG ═══"
[ -f .mcp.json ] && echo "  ✅ .mcp.json exists" || echo "  ❌ .mcp.json missing"
[ -f ~/.claude.json ] && echo "  ✅ ~/.claude.json exists" || echo "  ℹ️  ~/.claude.json not found"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║         VERIFICATION COMPLETE                 ║"
echo "╚══════════════════════════════════════════════╝"
```

---

## PHASE 4: SUMMARY REPORT

After completing Phases 1-3, output a structured report using this exact format. Fill in ✅ or ❌ based on actual results:

```
╔══════════════════════════════════════════════════════════════╗
║              BARKAIN STEP 0 — SUMMARY REPORT                ║
╚══════════════════════════════════════════════════════════════╝

ALREADY DONE (found during audit):
  [list everything that was already installed/configured before agent ran]

COMPLETED BY AGENT:
  [list everything the agent installed/created/started]

═══ 🧑 MIKE — MANUAL TASKS REMAINING ═══

🔴 BLOCKERS (must complete before Step 1a):

  1. CLERK KEYS
     → Go to https://dashboard.clerk.com → Barkain project → API Keys
     → Copy Publishable Key → paste into .env as CLERK_PUBLISHABLE_KEY
     → Copy Secret Key → paste into .env as CLERK_SECRET_KEY
     → Enable sign-in methods: Email, Google, Apple Sign-In
       (User & Authentication → Email, Phone, Username → enable Email)
       (User & Authentication → Social Connections → enable Google + Apple)

  2. GEMINI API KEY
     → Go to https://aistudio.google.com/apikey
     → Create or copy API key
     → Paste into .env as GEMINI_API_KEY

  3. UPCITEMDB API KEY
     → Go to https://www.upcitemdb.com/wp/docs/main/development/getting-started/
     → Sign up, get API key (free tier: 100 lookups/day)
     → Paste into .env as UPCITEMDB_API_KEY

  4. GUIDING DOCS (if any are missing)
     → Copy the downloaded files into your repo:
       - CLAUDE.md → /Desktop/BarkainApp/Barkain/CLAUDE.md
       - All 12 .md files → /Desktop/BarkainApp/Barkain/docs/

  5. MCP SERVERS FOR CLAUDE CODE
     → Add these to your Claude Code MCP settings.
     
     Option A: Project-level (.mcp.json already created by agent — check contents)
     Option B: Global config (~/.claude.json)
     
     Servers to configure:

     POSTGRESQL:
     {
       "command": "npx",
       "args": ["-y", "@modelcontextprotocol/server-postgres",
                "postgresql://app:localdev@localhost:5432/barkain"]
     }

     REDIS:
     Install: npm install -g @modelcontextprotocol/server-redis
     OR use npx:
     {
       "command": "npx",
       "args": ["-y", "@modelcontextprotocol/server-redis",
                "redis://localhost:6379"]
     }

     CONTEXT7 (library docs):
     {
       "command": "npx",
       "args": ["-y", "@upstash/context7-mcp"]
     }

     CLERK:
     {
       "command": "npx",
       "args": ["-y", "@clerk/mcp-server"],
       "env": {
         "CLERK_SECRET_KEY": "sk_test_YOUR_REAL_KEY_HERE"
       }
     }

     After configuring, restart Claude Code and test:
       - PostgreSQL: ask agent to "run SELECT 1 on the database"
       - Redis: ask agent to "ping Redis"
       - Context7: ask agent to "look up FastAPI docs"
       - Clerk: ask agent to "list Clerk users"

  6. GITHUB REMOTE (if not configured)
     → Run: gh repo create barkain --private --source=. --push
     → Or: git remote add origin git@github.com:YOURUSERNAME/barkain.git
     → Then: git add -A && git commit -m "feat: initial repo scaffold" && git push -u origin main
     → Set up branch protection:
       gh api repos/YOURUSERNAME/barkain/branches/main/protection -X PUT \
         -f required_status_checks='{"strict":true,"contexts":["tests"]}' \
         -F enforce_admins=false \
         -f required_pull_request_reviews='{"required_approving_review_count":0}'

🟡 BEFORE STEP 1g (iOS work):

  7. VISUAL PROTOTYPE
     → Create 6 static screens in prototype/:
       Scan tab, Search tab, Savings tab, Profile tab,
       Recommendation Result, Loading State
     → Format: HTML/CSS, Figma PNG, or static SwiftUI previews
     → Commit: git add prototype/ && git commit -m "feat: visual prototype"

  8. XCODEBUILDMCP
     → Install: brew install xcodebuildmcp/tap/xcodebuildmcp
     → Add to MCP config:
       { "command": "xcodebuildmcp" }

🟢 NOT BLOCKING (do whenever):

  9.  Anthropic API key → console.anthropic.com → .env ANTHROPIC_API_KEY
  10. OpenAI API key → platform.openai.com → .env OPENAI_API_KEY
  11. Best Buy API → developer.bestbuy.com → .env BEST_BUY_API_KEY
  12. eBay Developer → developer.ebay.com → .env EBAY_CLIENT_ID + SECRET
  13. Keepa API → keepa.com ($15/mo) → .env KEEPA_API_KEY
  14. Amazon Associates → affiliate-program.amazon.com (1-3 week approval)
  15. eBay Partner Network → partnernetwork.ebay.com (hours-days approval)
  16. CJ Affiliate → cj.com (1-3 week approval)

═══ WHAT HAPPENS NEXT ═══

Once items 1-6 above are done, paste Step 1a from Phase_1_Prompt_Package_v3.md
into Claude Code. The agent will:
  1. Read CLAUDE.md and all referenced docs
  2. Present a numbered execution plan
  3. Wait for your approval
  4. Build: PostgreSQL schema, FastAPI skeleton, Clerk auth, tests
```

---

## NOTES FOR THE AGENT

- If you encounter permission errors on `brew install`, suggest Mike run with `sudo` or fix Homebrew permissions
- If Docker containers fail to start, check `docker compose logs` and include the error in the report
- If ports 5432, 5433, or 6379 are already in use, report which process holds them (`lsof -i :5432`)
- If `.env` already has some real keys filled in, preserve those — never overwrite with placeholders
- If the Xcode project is at a different path than `/Desktop/BarkainApp/Barkain/`, ask Mike to confirm the correct path before proceeding
- The agent should NEVER modify anything inside `Barkain.xcodeproj/`, `Barkain/`, `BarkainTests/`, or `BarkainUITests/` — those are Xcode-managed
