# CLAUDE.md — Barkain

> **Purpose:** Root orientation for AI coding agents. This file alone should let a new session understand the project, find anything, and follow conventions.
> **Last updated:** April 2026 (v3.1 — Step 0 complete, infrastructure provisioned, Docker running, MCP servers configured)

---

## What This Is

Barkain is a native iOS app (with Python backend) that finds the absolute lowest total cost of any product by combining price comparison, identity-based discounts, credit card reward optimization, coupons, secondary market listings, shopping portal bonuses, and price prediction into a single AI-powered recommendation.

**Repo:** `github.com/molatunji3/barkain`
**Bundle ID:** `com.molatunji3.barkain`
**Minimum deployment:** iOS 17.0 | Xcode 16+ | Swift 5.9+

---

## Project Structure

```
barkain/
├── CLAUDE.md                          ← You are here
├── docker-compose.yml                 ← Local dev: PostgreSQL+TimescaleDB, Redis
├── .env.example                       ← All env vars with placeholder values
├── Barkain.xcodeproj                 # Xcode project
├── Barkain/                          # iOS source (created by Xcode)
│   ├── App/
│   │   ├── BarkainApp.swift      # @main entry point
│   │   ├── AppState.swift         # Global observable state
│   │   └── ContentView.swift      # Root TabView
│   ├── Features/
│   │   ├── Scanner/               # Barcode + image + receipt scanning
│   │   ├── Search/                # Product search + results
│   │   ├── Recommendation/        # Full-stack recommendation display
│   │   ├── Profile/               # Identity profile + card portfolio
│   │   ├── Savings/               # Dashboard + running totals
│   │   ├── Alerts/                # Price drop + spike notifications
│   │   └── Shared/
│   │       ├── Components/        # ProductCard, PriceRow, SavingsBadge
│   │       ├── Extensions/
│   │       ├── Utilities/
│   │       └── Modifiers/
│   ├── Services/
│   │   ├── Networking/
│   │   │   ├── APIClient.swift    # Typed API client to backend
│   │   │   ├── Endpoints.swift
│   │   │   └── APIError.swift
│   │   ├── Scanner/
│   │   │   ├── BarcodeScanner.swift
│   │   │   └── ReceiptScanner.swift
│   │   ├── Auth/
│   │   │   └── AuthService.swift  # Clerk SDK integration
│   │   └── StoreKit/
│   │       └── SubscriptionService.swift
│   ├── Resources/
│   │   ├── Assets.xcassets
│   │   └── Info.plist
│   └── Preview Content/
├── BarkainTests/
├── BarkainUITests/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI entry point
│   │   ├── config.py                  # Environment configuration (pydantic-settings)
│   │   ├── dependencies.py            # Dependency injection (DB session, Redis, auth)
│   │   └── middleware.py              # Auth, rate limiting, logging, error handling
│   ├── modules/
│   │   ├── m1_product/                # Product resolution (UPC → canonical)
│   │   ├── m2_prices/                 # Price aggregation + caching
│   │   │   └── adapters/             # Per-retailer adapters (bestbuy.py, ebay.py, keepa.py)
│   │   ├── m3_secondary/              # Secondary market (eBay used/refurb, BackMarket)
│   │   ├── m4_coupons/                # Coupon discovery + validation
│   │   ├── m5_identity/               # User identity + discount catalog + card portfolio
│   │   ├── m6_recommend/              # AI recommendation engine
│   │   ├── m7_predict/                # Price prediction + wait intelligence
│   │   ├── m8_scanner/                # Vision API calls for image/receipt
│   │   ├── m9_notify/                 # Push notifications
│   │   ├── m10_savings/               # Receipt tracking + savings calc
│   │   ├── m11_billing/               # Subscription management (RevenueCat)
│   │   └── m12_affiliate/             # Affiliate link routing + tracking
│   ├── ai/
│   │   ├── abstraction.py             # Model-agnostic LLM interface
│   │   ├── prompts/                   # Prompt templates per module
│   │   └── models.py                  # Model routing (Opus/Sonnet/Qwen/GPT)
│   ├── workers/
│   │   ├── price_ingestion.py         # Scheduled price fetching
│   │   ├── portal_rates.py            # Portal bonus rate scraping (every 6hr)
│   │   ├── discount_verification.py   # Identity discount program verification (weekly)
│   │   ├── coupon_validator.py        # Background coupon validation
│   │   └── prediction_trainer.py      # Price prediction model training
│   ├── tests/
│   │   ├── conftest.py                # Shared fixtures (Docker test DB, mock AI, fakeredis)
│   │   ├── modules/                   # Per-module test files
│   │   └── fixtures/                  # Canned API responses for mocking
│   ├── requirements.txt
│   └── requirements-test.txt
├── containers/                        # Per-retailer scraper containers (Phase 2)
│   ├── walmart/
│   │   ├── Dockerfile
│   │   ├── walmart-extract.sh
│   │   ├── extract.js
│   │   ├── config.json
│   │   └── test_fixtures.json
│   ├── target/
│   └── [one per retailer]
├── infrastructure/
│   ├── migrations/                    # Alembic database migrations
│   └── terraform/                     # AWS infrastructure as code
├── scripts/                           # Seeding, one-off utilities
├── prototype/                         # Visual prototype (HTML/CSS or static SwiftUI)
├── docs/                              ← Guiding files
│   ├── ARCHITECTURE.md
│   ├── PHASES.md
│   ├── FEATURES.md
│   ├── COMPONENT_MAP.md
│   ├── DATA_MODEL.md
│   ├── DEPLOYMENT.md
│   ├── TESTING.md
│   ├── AUTH_SECURITY.md
│   ├── CARD_REWARDS.md
│   ├── IDENTITY_DISCOUNTS.md
│   ├── SEARCH_STRATEGY.md
│   └── SCRAPING_AGENT_ARCHITECTURE.md
└── prompts/                           ← Prompt packages (NOT in repo)
```

---

## Running Locally

```bash
# 1. Start infrastructure
docker compose up -d          # PostgreSQL+TimescaleDB, Redis, Test DB

# 2. Backend
cd backend
cp ../.env.example .env       # Fill in real values
pip install -r requirements.txt -r requirements-test.txt
cd ..
alembic upgrade head          # Run migrations (from project root, reads alembic.ini)
python scripts/seed_retailers.py  # Seed 11 retailers

# 3. Run backend
cd backend
uvicorn app.main:app --reload --port 8000

# 4. Tests (from backend/)
pytest --tb=short -q          # Backend tests (Docker PostgreSQL port 5433, NOT SQLite)
ruff check .                  # Lint

# 5. iOS
# Open Barkain.xcodeproj in Xcode
# Or use XcodeBuildMCP for build/test from Claude Code
```

---

## Architecture

**Pattern:** MVVM (iOS) + Modular Monolith (Backend) + Containerized Scrapers

**iOS:** SwiftUI + @Observable ViewModels. Views → ViewModels → APIClient → Backend.

**Backend:** FastAPI (Python 3.12+). 12 modules, each with its own router, service, models, schemas. Modules communicate via direct imports (monolith).

**Scrapers:** Per-retailer Docker containers, each running: Chrome + agent-browser CLI + extraction script (DOM eval pattern) + AI health agent (Watchdog). Backend sends requests to containers; containers return structured JSON.

**AI Layer:** All LLM calls go through `backend/ai/abstraction.py`. Never call Claude/GPT directly from a module. The abstraction handles model routing, retry logic, and structured output parsing via Instructor. Watchdog self-healing uses Claude Opus (YC credits); recommendation synthesis uses Claude Sonnet.

**Data flow:**
```
User scans barcode/image (iOS)
  → APIClient sends to backend
    → M1 resolves product (Gemini API UPC lookup → PostgreSQL cache)
    → M2 sends to agent-browser containers (11 retailers, all scraped)
    → M3 checks secondary markets (eBay used/refurb, BackMarket, FB Marketplace) [parallel]
    → M5 overlays identity discounts (from discount_programs table)
    → M5 matches optimal card (from card_reward_programs + rotating_categories)
    → M5 finds best portal bonus (from portal_bonuses table)
    → M6 AI synthesizes recommendation (Claude Sonnet) [Phase 3]
  → Result returned to iOS
  → User sees: best price, where, which card, portal instruction, savings
```

**Demo vs Production:** Phase 1 demo uses agent-browser containers for ALL retailers. Production adds free APIs (Best Buy Products API, eBay Browse API) and Keepa as a speed optimization layer — API results return in ~500ms vs 3-8s for containers.

**Zero-LLM query-time matching:** Identity discounts, card rewards, rotating categories, and portal bonuses are all stored in PostgreSQL and matched via pure SQL joins at query time. The AI layer (Claude Sonnet) is only used for the final recommendation synthesis — everything before it is deterministic.

**Concurrency:** Python async/await throughout. Swift structured concurrency on iOS.

---

## Conventions

### Backend (Python)
- **FastAPI** with Pydantic v2 models for all request/response schemas
- **Alembic** for database migrations — backward-compatible only. Path: `infrastructure/migrations/`
- **SQLAlchemy 2.0** async ORM
- Each module has: `router.py`, `service.py`, `models.py`, `schemas.py`
- All AI calls through `ai/abstraction.py` — never import anthropic/openai directly in modules
- Background workers use SQS + standalone scripts, not Celery
- Per-retailer adapters in `m2_prices/adapters/` — normalize to common price schema

### iOS (Swift)
- **SwiftUI** declarative views, `@Observable` ViewModels (iOS 17+)
- **No force unwraps** except in Preview providers
- `// MARK: -` sections in every file
- Extract subviews when body exceeds ~40 lines
- Services injected via `@Environment`, not singletons
- **SPM only** — no CocoaPods

### Git
- Branch per step: `phase-N/step-Na`
- Conventional commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`
- Tags at phase boundaries: `v0.N.0`
- Developer handles all git operations — agent never commits

### Classification Rule
Before implementing any feature, check `docs/FEATURES.md` for its AI/Traditional/Hybrid classification. If classified as Traditional, do NOT use LLM calls. If Hybrid, AI generates and code validates/executes.

---

## Development Methodology

This project uses a **two-tier AI workflow:**

1. **Planner (Claude Opus via claude.ai):** Architecture, prompt engineering, step reviews, deployment troubleshooting
2. **Executor (Claude Code / Sonnet):** Implementation — writes code, runs tests, follows structured prompt packages

**The loop:** Planner creates prompt package → Developer pastes step into coding agent → Agent plans, builds, tests → Developer writes error report → Planner reviews and evolves prompt → Repeat.

**Key rules:**
- Every step includes a FINAL section that mandates guiding doc updates
- Pre-fix blocks carry known issues from prior steps into the next step's prompt
- This file (CLAUDE.md) must pass the "new session" test after every step
- Error reports are structured (numbered issues, not narrative)
- Prompt packages live in `prompts/` (NOT in repo)

---

## Tooling

### MCP Servers (live service connections for Claude Code)
- **Postgres MCP Pro** (Docker, crystaldba) — schema inspection, query testing, migration validation, unrestricted access mode
- **Redis MCP** (Docker, official mcp/redis image) — cache key inspection, TTL verification
- **Context7** — library documentation lookup (FastAPI, SQLAlchemy, SwiftUI, Clerk SDK, etc.)
- **Clerk** (HTTP transport, mcp.clerk.com) — user management, JWT inspection, session debugging
- **XcodeBuildMCP** — iOS build, test, clean, scheme inspection
- **LocalStack** (Docker) — mock SQS/S3/SNS [Phase 2 — added to docker-compose when needed]

### CLIs
- Day 1: `gh`, `docker`, `ruff`, `alembic`, `pytest`, `swiftlint`, `jq`, `xcodes`
- First deploy: `aws`, `railway`
- Phase 4+: `fastlane`, `vercel`

---

## Current State

**Phase 0 — Planning Complete** ✅
**Step 0 — Infrastructure Provisioning: COMPLETE** ✅ (2026-04-06)
**Step 1a — Database Schema + FastAPI Skeleton + Auth: COMPLETE** ✅ (2026-04-07)
**Step 1b — M1 Product Resolution + AI Abstraction: COMPLETE** ✅ (2026-04-07)
**Step 1c — Container Infrastructure + Backend Client: COMPLETE** ✅ (2026-04-07)
**Step 1d — Retailer Containers Batch 1: COMPLETE** ✅ (2026-04-07)
**Step 1e — Retailer Containers Batch 2: COMPLETE** ✅ (2026-04-07)
**Step 1f — M2 Price Aggregation + Caching: COMPLETE** ✅ (2026-04-08)
**Phase 1 — Foundation: IN PROGRESS**

- Architecture documents: ✅
- Questionnaire (7 phases): ✅
- Cost analysis: ✅
- All guiding docs: ✅ (12 docs in docs/, v3 — updated April 2026)
- Specialized docs (CARD_REWARDS, IDENTITY_DISCOUNTS, SEARCH_STRATEGY, SCRAPING_AGENT_ARCHITECTURE): ✅
- Apple Developer account: ✅
- Clerk project: ✅ (keys in .env)
- Gemini API: ✅ (key in .env — primary UPC resolution)
- UPCitemdb API: NOT STARTED (fallback — nice-to-have, free tier 100/day)
- API sign-ups (Best Buy, eBay, Keepa): NOT STARTED (production optimization — not required for demo)
- Docker local dev environment: ✅ (3 containers: barkain-db, barkain-db-test, barkain-redis)
- TimescaleDB extension: ✅ (v2.26.1 on both PostgreSQL instances)
- MCP servers: ✅ (5 configured: Postgres Pro, Redis, Context7, Clerk, XcodeBuildMCP)
- GitHub repo: ✅ (github.com/molatunji3/barkain, private)
- CLI tools: ✅ (all 16 installed — brew, git, gh, python3, pip3, node, npm, docker, compose, jq, xcodes, swiftlint, ruff, alembic, pytest, swift)
- Xcode: ✅ (26.4, xcode-select configured)
- Visual prototype: NOT STARTED
- Database schema: ✅ (21 tables via Alembic migration 0001, TimescaleDB hypertable on price_history)
- FastAPI skeleton: ✅ (health endpoint, CORS, security headers, structured error handling)
- Clerk auth middleware: ✅ (JWT validation via clerk-backend-api, get_current_user dependency)
- Rate limiting: ✅ (Redis sorted set sliding window, per-user, 3 tiers)
- Retailer seed: ✅ (11 Phase 1 retailers)
- Backend tests: ✅ (14 passing — health, auth, rate limiting, migrations, seed)
- AI abstraction layer: ✅ (`backend/ai/abstraction.py` — Gemini API wrapper with retry logic)
- M1 Product resolution: ✅ (POST /api/v1/products/resolve — Gemini primary, UPCitemdb backup, Redis 24hr cache)
- M1 tests: ✅ (12 new — validation, auth, resolution chain, caching, fallback, 404)
- Container template: ✅ (`containers/template/` — Dockerfile, server.py, base-extract.sh, extract.js, config.json, test_fixtures.json)
- Container Dockerfile: ✅ (builds successfully, health endpoint responds, Chromium + agent-browser + Xvfb + FastAPI)
- Container client: ✅ (`backend/modules/m2_prices/container_client.py` — parallel dispatch, 30s timeout, 1 retry, partial failure tolerance)
- M2 schemas: ✅ (ContainerExtractRequest, ContainerListing, ContainerResponse, ContainerHealthResponse)
- Container config: ✅ (CONTAINER_URL_PATTERN `http://localhost:{port}`, CONTAINER_PORTS mapping 11 retailers to full port numbers 8081-8091)
- Container client tests: ✅ (14 new — extract success/timeout/error/retry, extract_all parallel/partial/all-fail, health check, URL resolution, normalization)
- Retailer containers batch 1: ✅ (5 containers: Amazon, Walmart, Target, Sam's Club, Facebook Marketplace)
- Amazon container: ✅ (`containers/amazon/` — DOM eval, `[data-component-type]` + `data-asin`, title fallback chain, sponsored noise stripping)
- Walmart container: ✅ (`containers/walmart/` — PerimeterX workaround: Chrome launches directly with search URL, never `agent-browser open`)
- Target container: ✅ (`containers/target/` — `load` wait strategy, not `networkidle`; `[data-test]` selectors)
- Sam's Club container: ✅ (`containers/sams_club/` — best-guess selectors, needs live validation)
- Facebook Marketplace container: ✅ (`containers/fb_marketplace/` — login modal CSS hide, URL-pattern anchor, all items "used")
- Retailer container tests: ✅ (10 new — response parsing per retailer, parallel dispatch, mixed success/failure, metadata validation)
- Retailer containers batch 2: ✅ (6 containers: Best Buy, Home Depot, Lowe's, eBay New, eBay Used, BackMarket)
- Best Buy container: ✅ (`containers/best_buy/` — `.sku-item` anchor, standard networkidle flow)
- Home Depot container: ✅ (`containers/home_depot/` — `[data-testid="product-pod"]` anchor, needs live validation)
- Lowe's container: ✅ (`containers/lowes/` — multi-fallback selectors, needs live validation)
- eBay New container: ✅ (`containers/ebay_new/` — `.s-item` anchor, condition filter `LH_ItemCondition=1000`)
- eBay Used container: ✅ (`containers/ebay_used/` — `.s-item` anchor, condition filter for used+refurb, extracts condition text)
- BackMarket container: ✅ (`containers/backmarket/` — all items "refurbished", seller extraction)
- Batch 2 container tests: ✅ (9 new — response parsing per retailer, all-6 parallel dispatch, partial failure, seller validation)
- Container URL pattern fix: ✅ (changed from `http://localhost:808{port}` to `http://localhost:{port}` with full port numbers)
- M2 Price Aggregation Service: ✅ (`backend/modules/m2_prices/service.py` — full pipeline: cache check → container dispatch → normalize → upsert → cache → return)
- M2 Price endpoint: ✅ (GET /api/v1/prices/{product_id} — auth, rate limiting, force_refresh, sorted ascending)
- M2 Redis caching: ✅ (6hr TTL, key pattern `prices:product:{product_id}`, 3-tier cache: Redis → DB → containers)
- M2 Price upsert: ✅ (ON CONFLICT DO UPDATE on product_id+retailer_id+condition)
- M2 Price history: ✅ (append-only to TimescaleDB hypertable, source=agent_browser)
- M2 tests: ✅ (13 new — cache hit/miss, force_refresh, sorting, partial failure, upsert, is_on_sale, 404, 422, auth)

**Test counts:** 72 backend, 0 iOS unit, 0 UI, 0 snapshot
**Build status:** Backend compiles and serves health + product resolve + price comparison endpoints; container template + 11 retailer containers build and respond to GET /health; `ruff check` clean

### Key Files Created (Step 1a)
```
backend/app/main.py              # FastAPI app + health endpoint
backend/app/config.py             # pydantic-settings config
backend/app/database.py           # SQLAlchemy Base + engine
backend/app/core_models.py        # User, Retailer, RetailerHealth, WatchdogEvent, PredictionCache
backend/app/models.py             # Model registry (imports all models)
backend/app/dependencies.py       # get_db, get_redis, get_current_user, get_rate_limiter
backend/app/middleware.py         # CORS, security headers, logging, error handling
backend/modules/m*/models.py      # 8 module model files (21 tables total)
alembic.ini                       # Alembic config (script_location = infrastructure/migrations)
infrastructure/migrations/env.py  # Async Alembic env
infrastructure/migrations/versions/0001_initial_schema.py  # All 21 tables
scripts/seed_retailers.py         # 11 retailer upsert
backend/tests/conftest.py         # Test fixtures (Docker PG port 5433, fakeredis, auth bypass)
backend/tests/test_*.py           # 5 test files, 14 tests
```

### Key Files Created (Step 1b)
```
backend/ai/__init__.py            # AI package init
backend/ai/abstraction.py         # Gemini API wrapper (lazy init, retry, JSON parsing)
backend/ai/prompts/__init__.py    # Prompts package init
backend/ai/prompts/upc_lookup.py  # UPC→product prompt template
backend/modules/m1_product/schemas.py   # ProductResolveRequest, ProductResponse
backend/modules/m1_product/service.py   # ProductResolutionService (Redis→PG→Gemini→UPCitemdb→404)
backend/modules/m1_product/router.py    # POST /api/v1/products/resolve
backend/modules/m1_product/upcitemdb.py # UPCitemdb backup client
backend/tests/modules/test_m1_product.py  # 12 tests
backend/tests/fixtures/gemini_upc_response.json   # Canned Gemini response
backend/tests/fixtures/upcitemdb_response.json     # Canned UPCitemdb response
```

### Key Files Created (Step 1c)
```
containers/template/Dockerfile         # Base image: Node 20 + Chromium + Python/FastAPI + Xvfb
containers/template/entrypoint.sh      # Start Xvfb + uvicorn
containers/template/server.py          # FastAPI with GET /health + POST /extract
containers/template/base-extract.sh    # 9-step extraction skeleton with placeholders
containers/template/extract.js.example # DOM eval JavaScript template
containers/template/config.json.example    # Per-retailer config schema
containers/template/test_fixtures.json.example  # Test queries with expected outputs
containers/README.md                   # Build/run/test documentation + port assignments
backend/modules/m2_prices/schemas.py   # Pydantic models for container communication
backend/modules/m2_prices/container_client.py  # HTTP dispatch to scraper containers
backend/tests/modules/test_container_client.py # 14 tests (respx mocking)
backend/tests/fixtures/container_extract_response.json  # Canned container response
```

### Key Files Created (Step 1d)
```
containers/amazon/                      # Amazon scraper (port 8081)
  Dockerfile, server.py, entrypoint.sh, extract.sh, extract.js, config.json, test_fixtures.json
containers/walmart/                     # Walmart scraper (port 8083) — PerimeterX workaround
  Dockerfile, server.py, entrypoint.sh, extract.sh, extract.js, config.json, test_fixtures.json
containers/target/                      # Target scraper (port 8084) — load wait strategy
  Dockerfile, server.py, entrypoint.sh, extract.sh, extract.js, config.json, test_fixtures.json
containers/sams_club/                   # Sam's Club scraper (port 8089)
  Dockerfile, server.py, entrypoint.sh, extract.sh, extract.js, config.json, test_fixtures.json
containers/fb_marketplace/              # Facebook Marketplace scraper (port 8091) — modal hide
  Dockerfile, server.py, entrypoint.sh, extract.sh, extract.js, config.json, test_fixtures.json
backend/tests/modules/test_container_retailers.py  # 10 tests for batch 1 retailers
backend/tests/fixtures/amazon_extract_response.json
backend/tests/fixtures/walmart_extract_response.json
backend/tests/fixtures/target_extract_response.json
backend/tests/fixtures/sams_club_extract_response.json
backend/tests/fixtures/fb_marketplace_extract_response.json
```

### Key Files Created (Step 1e)
```
containers/best_buy/                    # Best Buy scraper (port 8082)
containers/home_depot/                  # Home Depot scraper (port 8085)
containers/lowes/                       # Lowe's scraper (port 8086)
containers/ebay_new/                    # eBay New scraper (port 8087) — condition filter
containers/ebay_used/                   # eBay Used/Refurb scraper (port 8088) — condition extraction
containers/backmarket/                  # BackMarket scraper (port 8090) — all refurbished
  Each: Dockerfile, server.py, entrypoint.sh, extract.sh, extract.js, config.json, test_fixtures.json
backend/tests/modules/test_container_retailers_batch2.py  # 9 tests for batch 2
backend/tests/fixtures/{best_buy,home_depot,lowes,ebay_new,ebay_used,backmarket}_extract_response.json
```

### Key Files Created (Step 1f)
```
backend/modules/m2_prices/service.py    # PriceAggregationService (cache→dispatch→normalize→upsert→cache→return)
backend/modules/m2_prices/router.py     # GET /api/v1/prices/{product_id} with auth + rate limiting
backend/tests/modules/test_m2_prices.py # 13 tests (cache, dispatch, upsert, sorting, errors)
```

---

## What's Next

1. **Visual prototype:** 6 static screens in prototype/ (Scan, Search, Savings, Profile, Recommendation Result, Loading State) — before Step 1g
2. **Phase 1:** PostgreSQL schema, FastAPI backend, Clerk auth, product resolution (Gemini API UPC lookup), agent-browser container infrastructure, 11 retailer extraction scripts, iOS app shell with barcode scanner, price comparison UI
3. Target: 6-8 weeks to working barcode scan → 11-retailer price comparison demo (all scraped)

---

## Key Decisions Log

| Decision | Choice | Why | Date |
|----------|--------|-----|------|
| Primary platform | iOS (SwiftUI) | Advanced Swift skills; native camera APIs; iOS-first validation | Mar 2026 |
| Backend framework | FastAPI (Python) | Async-native; best AI/ML ecosystem; advanced proficiency | Mar 2026 |
| Database | PostgreSQL (AWS RDS) + TimescaleDB | YC credits; relational + time-series in one engine | Mar 2026 |
| AI models | Claude (primary) + GPT (fallback) | YC credits for both; abstraction layer enables hot-swap | Mar 2026 |
| Auth | Clerk | Existing Pro subscription; handles users + API keys; MCP for dev | Mar 2026 |
| Revenue model | Subscription via StoreKit/RevenueCat | Avoids Apple IAP disputes; predictable revenue | Mar 2026 |
| Hosting (MVP) | Railway (backend) + Vercel (web) | Existing subscriptions; minimal ops for solo dev | Mar 2026 |
| Hosting (scale) | AWS (ECS + RDS + ElastiCache) | $10K credits; migrate when Railway limits hit | Mar 2026 |
| Amazon data source | Keepa API ($15/mo) | PA-API deprecated April 30, 2026. Creators API requires 10 sales/month. Keepa has no sales gate | Apr 2026 |
| Scraping tool | agent-browser (DOM eval pattern) | Outperforms Playwright on all tested sites (35+ tests). Shell-scriptable, better anti-detection | Apr 2026 |
| Phase 1 retailers | 11 retailers, all scraped via agent-browser containers | Demo uses scrapers for everything. APIs (Best Buy, eBay Browse, Keepa) added as production speed optimization later | Apr 2026 |
| Phase 1 approach | Scrapers-first, APIs later | Building container infra in Phase 1 eliminates Phase 2 container work. APIs layer on top for production speed | Apr 2026 |
| Watched items | Phase 4 (paired with price prediction) | Natural pairing — tracking prices needs prediction to be useful | Apr 2026 |
| Tooling philosophy | Docker MCPs for services, CLIs for everything else | No custom skills — guiding docs are the single source of truth | Apr 2026 |
| Watchdog AI model | Claude Opus (YC credits) | Highest quality selector rediscovery; YC AI credits make cost viable | Apr 2026 |
| Browser Use | Dropped — fully replaced by agent-browser | agent-browser handles all scraping + Watchdog healing | Apr 2026 |
| Claude Haiku | Dropped — no assigned tasks | Tiered strategy: Opus (healing), Sonnet (quality), Qwen/ERNIE (cheap parsing) | Apr 2026 |
| Open Food Facts | Deferred — not relevant for Phase 1 electronics | Add when grocery categories are supported | Apr 2026 |
| LocalStack | Deferred to Phase 2 | Not needed until background workers (SQS) are built | Apr 2026 |
| Product cache | Redis only (24hr TTL) | Single-layer cache; PostgreSQL stores products persistently but not as a cache | Apr 2026 |
| UPC lookup | Gemini API (primary) + UPCitemdb (backup) | OpenAI charges $10/1K calls — unacceptable. Gemini API is cost-effective for UPC→product resolution, high accuracy, 4-6s latency. UPCitemdb as fallback (free tier 100/day). YC credits cover Gemini cost | Apr 2026 |
| user_cards.is_preferred | User-set preferred card for comparisons | Not "default" — user explicitly sets their preferred card | Apr 2026 |
| Postgres MCP | Postgres MCP Pro (crystaldba, Docker) | Unrestricted access mode; better schema inspection than basic server | Apr 2026 |
| Redis MCP | Official mcp/redis Docker image | No auth for local dev; Docker-based for consistency with other MCP servers | Apr 2026 |
| Clerk MCP | HTTP transport (mcp.clerk.com) | Simplest setup; no local npm packages needed | Apr 2026 |
| UPCitemdb priority | Nice-to-have, not blocker | Gemini API is primary for UPC resolution; UPCitemdb is fallback only | Apr 2026 |
