# CLAUDE.md — Barkain

> **Purpose:** Root orientation for AI coding agents. This file alone should let a new session understand the project, find anything, and follow conventions.
> **Last updated:** April 2026 (v3.7 — first live 3-retailer scan-to-prices demo on physical iPhone; 7 live-run bug fixes landed on `phase-2/scan-to-prices-deploy`)

---

## What This Is

Barkain is a native iOS app (with Python backend) that finds the absolute lowest total cost of any product by combining price comparison, identity-based discounts, credit card reward optimization, coupons, secondary market listings, shopping portal bonuses, and price prediction into a single AI-powered recommendation.

**Repo:** `github.com/THHUnlimted/barkain`
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
│   │   ├── errors.py                  # Shared error response helpers
│   │   └── middleware.py              # Auth, rate limiting, logging, error handling
│   ├── modules/
│   │   ├── m1_product/                # Product resolution (UPC → canonical)
│   │   ├── m2_prices/                 # Price aggregation + caching
│   │   │   ├── adapters/             # Per-retailer adapters (bestbuy.py, ebay.py, keepa.py)
│   │   │   ├── health_monitor.py     # Retailer health monitoring service
│   │   │   └── health_router.py      # GET /api/v1/health/retailers endpoint
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
│   │   │   └── watchdog_heal.py       # Opus heal + diagnose prompts
│   │   └── models.py                  # Model routing (Opus/Sonnet/Qwen/GPT)
│   ├── workers/
│   │   ├── price_ingestion.py         # Scheduled price fetching
│   │   ├── portal_rates.py            # Portal bonus rate scraping (every 6hr)
│   │   ├── discount_verification.py   # Identity discount program verification (weekly)
│   │   ├── coupon_validator.py        # Background coupon validation
│   │   ├── prediction_trainer.py      # Price prediction model training
│   │   └── watchdog.py                # Watchdog supervisor agent (nightly health checks + self-healing)
│   ├── tests/
│   │   ├── conftest.py                # Shared fixtures (Docker test DB, mock AI, fakeredis)
│   │   ├── modules/                   # Per-module test files
│   │   └── fixtures/                  # Canned API responses for mocking
│   ├── requirements.txt
│   └── requirements-test.txt
├── containers/                        # Per-retailer scraper containers (Phase 2)
│   ├── base/                          # Shared container base image (Dockerfile, server.py, entrypoint.sh)
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

**AI Layer:** All LLM calls go through `backend/ai/abstraction.py`. Never call Claude/GPT directly from a module. The abstraction handles model routing, retry logic, and structured output parsing. Gemini calls use thinking (ThinkingConfig), Google Search grounding, and temperature=1.0 for maximum UPC resolution accuracy. Response parsing extracts text parts only, skipping thinking chunks. Anthropic calls use the `anthropic` SDK with async client, retry logic, JSON parsing, and token usage tracking. Watchdog self-healing uses Claude Opus (YC credits); recommendation synthesis uses Claude Sonnet.

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
**Step 1g — iOS App Shell + Scanner + API Client + Design System: COMPLETE** ✅ (2026-04-08)
**Step 1h — Price Comparison UI: COMPLETE** ✅ (2026-04-08)
**Step 1i — Hardening + Doc Sweep + Tag v0.1.0: COMPLETE** ✅ (2026-04-08)
**Phase 1 — Foundation: COMPLETE (tagged v0.1.0)**
**Step 2a — Watchdog Supervisor + Health Monitoring + Pre-Fixes: COMPLETE** ✅ (2026-04-10)
**Scan-to-Prices Live Demo (3 retailers): COMPLETE** ✅ (2026-04-10, branch `phase-2/scan-to-prices-deploy`)

- AI abstraction: ✅ (Anthropic/Claude Opus added alongside Gemini — claude_generate, claude_generate_json, claude_generate_json_with_usage)
- Watchdog supervisor: ✅ (nightly health checks, failure classification, self-healing via Opus, escalation)
- Health monitor: ✅ (GET /api/v1/health/retailers, retailer_health table tracking)
- Watchdog CLI: ✅ (scripts/run_watchdog.py — --check-all, --heal, --status, --dry-run)
- Shared container base image: ✅ (containers/base/ — 11 retailer Dockerfiles refactored)
- Pre-fix: PriceHistory composite PK: ✅ (migration 0002 — composite PK on product_id, retailer_id, time)
- Pre-fix: Error response helper: ✅ (backend/app/errors.py — DRY error format)
- Pre-fix: Gemini null retry: ✅ (retry once with broader prompt before UPCitemdb fallback)
- Pre-fix: Shorter Redis TTL: ✅ (30min for 0-result, 6hr for success)
- Pre-fix: Broadened UPC prompt: ✅ (handles all product categories, not just electronics)
- Architecture documents: ✅
- Questionnaire (7 phases): ✅
- Cost analysis: ✅
- All guiding docs: ✅ (12 docs in docs/, v3 — updated April 2026)
- Specialized docs (CARD_REWARDS, IDENTITY_DISCOUNTS, SEARCH_STRATEGY, SCRAPING_AGENT_ARCHITECTURE): ✅
- Apple Developer account: ✅
- Clerk project: ✅ (keys in .env)
- Gemini API: ✅ (key in .env — primary UPC resolution)
- Anthropic API: ✅ (ANTHROPIC_API_KEY in .env — Watchdog self-healing via Claude Opus)
- UPCitemdb API: NOT STARTED (fallback — nice-to-have, free tier 100/day)
- API sign-ups (Best Buy, eBay, Keepa): NOT STARTED (production optimization — not required for demo)
- Docker local dev environment: ✅ (3 containers: barkain-db, barkain-db-test, barkain-redis)
- TimescaleDB extension: ✅ (v2.26.1 on both PostgreSQL instances)
- MCP servers: ✅ (5 configured: Postgres Pro, Redis, Context7, Clerk, XcodeBuildMCP)
- GitHub repo: ✅ (github.com/THHUnlimted/barkain, private)
- CLI tools: ✅ (all 16 installed — brew, git, gh, python3, pip3, node, npm, docker, compose, jq, xcodes, swiftlint, ruff, alembic, pytest, swift)
- Xcode: ✅ (26.4, xcode-select configured)
- Visual prototype: NOT STARTED
- Database schema: ✅ (21 tables via Alembic migration 0001, TimescaleDB hypertable on price_history)
- FastAPI skeleton: ✅ (health endpoint, CORS, security headers, structured error handling)
- Clerk auth middleware: ✅ (JWT validation via clerk-backend-api, get_current_user dependency)
- Rate limiting: ✅ (Redis sorted set sliding window, per-user, 3 tiers)
- Retailer seed: ✅ (11 Phase 1 retailers)
- Backend tests: ✅ (14 passing — health, auth, rate limiting, migrations, seed)
- AI abstraction layer: ✅ (`backend/ai/abstraction.py` — google-genai SDK with native async, retry logic, thinking (budget=-1), Google Search grounding, temperature=1.0, text-part extraction skipping thinking chunks)
- UPC lookup prompt: ✅ (`backend/ai/prompts/upc_lookup.py` — system instruction with 9-step reasoning (cached), user prompt is bare UPC + output format constraint, returns `device_name` only, maps to `name` in service with `source=gemini_upc`)
- M1 Product resolution: ✅ (POST /api/v1/products/resolve — Gemini `gemini-3.1-flash-lite-preview` with thinking+grounding primary, UPCitemdb backup, Redis 24hr cache. Gemini returns `device_name` only; brand/category/asin populated by UPCitemdb or future enrichment)
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
- iOS Xcode project: ✅ (Barkain.xcodeproj — bundle ID `com.molatunji3.barkain`, iOS 17.6+, Swift 5.0, xcconfig Debug/Release)
- iOS design system: ✅ (Colors, Spacing, Typography from HTML prototype)
- iOS data models: ✅ (Product, PriceComparison, RetailerPrice — Codable with snake_case decoding)
- iOS API client: ✅ (APIClientProtocol + APIClient — resolveProduct, getPrices, error mapping, custom date decoding)
- iOS barcode scanner: ✅ (AVFoundation — EAN-13/UPC-A, AsyncStream, 2s debounce, UPC-A normalization strips leading 0 from EAN-13)
- iOS navigation shell: ✅ (TabView: Scan/Search/Savings/Profile, each with NavigationStack)
- iOS scanner feature: ✅ (ScannerView + ScannerViewModel — scan barcode → resolve product → fetch prices)
- iOS shared components: ✅ (ProductCard, PriceRow, SavingsBadge, EmptyState, LoadingState, ProgressiveLoadingView)
- iOS price comparison UI: ✅ (PriceComparisonView — sorted price list, Best Barkain badge, SavingsBadge, tap-to-open URL, refresh, status bar)
- iOS progressive loading: ✅ (ProgressiveLoadingView spinner animation, pun rotation, 11-retailer status list)
- iOS scan→compare flow: ✅ (full demo loop: scan barcode → resolve product → fetch 11 retailer prices → display comparison)
- iOS tests: ✅ (21 passing — ScannerViewModel×14, APIClient×3, others)

**Test counts:** 128 backend, 21 iOS unit, 0 UI, 0 snapshot (unchanged from Step 2a — scan-to-prices was a live validation, not a code-gen step)
**Build status:** Backend compiles and serves health + product resolve + price comparison + retailer health endpoints; Amazon + Best Buy containers build and return real listings end-to-end against live sites on EC2 `t3.xlarge`; Walmart path returns real listings via Firecrawl v2 adapter; iOS app scans barcode → resolves via Gemini → fetches 3 retailers → displays comparison on a physical iPhone in ~90–120 s; `ruff check` clean

**Live demo runtime profile (2026-04-10, physical iPhone):**
- Gemini UPC resolve: 2–4 s
- Amazon container (EC2): ~30 s end-to-end
- Best Buy container (EC2): ~90 s end-to-end (dominant leg)
- Walmart Firecrawl adapter: ~30 s
- iOS total: ~90–120 s, dominated by Best Buy

**Known demo caveats (see `Barkain Prompts/Error_Report_Scan_to_Prices_Deployment.md`):**
- **Product-match relevance (SP-10, HIGH):** each retailer's on-site search returns similar-but-not-identical products, and `_pick_best_listing` picks the cheapest regardless. Example: scanning an M4 Mac mini returned the correct SKU on Best Buy but a cheaper wrong-spec Mac mini on Amazon. Relevance guardrail is a hard prerequisite for any external demo — belongs in Step 2b design.
- **Gemini UPC resolution accuracy (SP-L4, HIGH):** 3/3 tested UPCs (`0027242927568`, `0027242922914`, `194253397953`) resolved to unrelated products (camera battery, lens hood, dining room set). Needs UPCitemdb second-opinion fallback when Gemini's output doesn't match the scanned category, or a confidence score, or a broader prompt.
- **Amazon extract.js title selector (SP-9, MEDIUM):** only captures brand (e.g. `"Sony"`) instead of full product title. Price, URL, image correct. Selector refactor or Watchdog heal pass needed.
- **fd-3 stdout pattern latent on 8 retailers (SP-L2, MEDIUM):** only `containers/amazon/extract.sh` and `containers/best_buy/extract.sh` were fixed this session. The other 8 retailer extract.sh files (target, home_depot, lowes, ebay_new, ebay_used, sams_club, backmarket, fb_marketplace, walmart_container) still have the same latent bug and must be backfilled before those retailers go live.
- **GitHub PAT leaked in EC2 git config (SP-L1, HIGH):** `gho_UUsp9ML…` is embedded in `~/barkain/.git/config` on stopped EC2 instance `i-09ce25ed6df7a09b2`. Must be rotated.

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

### Key Files Created (Step 1g)
```
Config/Debug.xcconfig                                  # API_BASE_URL = http://localhost:8000
Config/Release.xcconfig                                # API_BASE_URL = https://api.barkain.ai
Barkain/Services/Networking/AppConfig.swift             # #if DEBUG URL switching
Barkain/Services/Networking/APIError.swift              # Error types matching backend format
Barkain/Services/Networking/Endpoints.swift             # URL builder for resolve + prices + health
Barkain/Services/Networking/APIClient.swift             # APIClientProtocol + APIClient (async, typed)
Barkain/Services/Scanner/BarcodeScanner.swift           # AVFoundation EAN-13/UPC-A scanner with AsyncStream
Barkain/Features/Shared/Extensions/Colors.swift         # Color palette from HTML prototype
Barkain/Features/Shared/Extensions/Spacing.swift        # Spacing + corner radius constants
Barkain/Features/Shared/Extensions/Typography.swift     # Font styles (system approximations)
Barkain/Features/Shared/Extensions/EnvironmentKeys.swift # APIClient environment injection
Barkain/Features/Shared/Models/Product.swift            # Product (Codable, snake_case CodingKeys)
Barkain/Features/Shared/Models/PriceComparison.swift    # PriceComparison + RetailerPrice + APIErrorResponse
Barkain/Features/Shared/Components/ProductCard.swift    # Product display card (image, name, brand)
Barkain/Features/Shared/Components/PriceRow.swift       # Retailer price row (name, price, sale badge)
Barkain/Features/Shared/Components/SavingsBadge.swift   # Savings pill badge
Barkain/Features/Shared/Components/EmptyState.swift     # Generic empty/error state
Barkain/Features/Shared/Components/LoadingState.swift   # Spinner + message
Barkain/Features/Shared/Components/ProgressiveLoadingView.swift # 11-retailer progressive status list
Barkain/Features/Scanner/ScannerView.swift              # Camera preview + scan overlay + results
Barkain/Features/Scanner/ScannerViewModel.swift         # @Observable — scan → resolveProduct
Barkain/Features/Scanner/CameraPreviewView.swift        # UIViewRepresentable for AVCaptureVideoPreviewLayer
Barkain/Features/Search/SearchPlaceholderView.swift     # Placeholder (coming soon)
Barkain/Features/Savings/SavingsPlaceholderView.swift   # Placeholder (coming soon)
Barkain/Features/Profile/ProfilePlaceholderView.swift   # Placeholder (coming soon)
BarkainTests/Helpers/MockAPIClient.swift                # Protocol-based mock with Result configuration
BarkainTests/Helpers/MockURLProtocol.swift              # URLProtocol subclass for API client tests
BarkainTests/Helpers/TestFixtures.swift                 # Sample Product, PriceComparison, JSON payloads
BarkainTests/Features/Scanner/ScannerViewModelTests.swift # 5 tests (resolve, error, loading, clear, reset)
BarkainTests/Services/APIClientTests.swift              # 3 tests (decode product, 404, decode prices)
```

### Key Files Modified/Created (Step 1h)
```
Barkain/Features/Recommendation/PriceComparisonView.swift  # NEW — price comparison results screen
Barkain/Features/Scanner/ScannerViewModel.swift            # Extended — priceComparison, isPriceLoading, fetchPrices(), computed helpers
Barkain/Features/Scanner/ScannerView.swift                 # Updated — new state machine (price loading → results → error), onDisappear cleanup
Barkain/Features/Shared/Components/ProgressiveLoadingView.swift # Fixed — spinner animation, pun rotation timer
BarkainTests/Features/Scanner/ScannerViewModelTests.swift  # 14 tests (5 existing + 9 new price comparison tests)
BarkainTests/Helpers/MockAPIClient.swift                   # Extended — forceRefresh tracking, getPricesDelay
BarkainTests/Helpers/TestFixtures.swift                    # Extended — cached, empty, partial PriceComparison fixtures
```

### Key Files Modified/Created (Post-Phase 1 — Demo + Hardening)
```
Info.plist                                                 # NEW — ATS local networking exception + API_BASE_URL from xcconfig
Config/Debug.xcconfig                                      # API_BASE_URL (change to Mac IP for physical device testing)
Barkain/Services/Networking/AppConfig.swift                 # Reads API_BASE_URL from Info.plist with hardcoded fallback
Barkain/Services/Scanner/BarcodeScanner.swift               # UPC-A normalization (strip leading 0 from EAN-13), clearLastScan()
Barkain/Features/Scanner/ScannerView.swift                  # onChange(of: scannedUPC) clears scanner on reset, scanner.clearLastScan in error view
backend/app/dependencies.py                                 # BARKAIN_DEMO_MODE=1 auth bypass for local testing
backend/ai/abstraction.py                                   # Thinking (budget=-1), Google Search grounding, temperature=1.0, _extract_text() skips thinking parts, JSON fallback regex extraction
backend/ai/prompts/upc_lookup.py                            # System instruction: full 9-step reasoning (cached). User prompt: bare UPC + output format only
backend/modules/m1_product/service.py                       # Simplified: parses device_name only, source=gemini_upc, brand/category/asin=None
backend/tests/fixtures/gemini_upc_response.json             # Simplified to {"device_name": "..."}
backend/tests/test_integration.py                           # Updated GEMINI_PRODUCT_DATA to device_name only
backend/tests/modules/test_m1_product.py                    # Updated assertions for gemini_upc source
Barkain.xcodeproj/project.pbxproj                           # Added INFOPLIST_FILE=Info.plist to Debug+Release target configs
prompts/DEMO_GUIDE.md                                       # NEW — comprehensive demo walkthrough with physical device instructions
```

### Key Files Modified/Created (Step 1i)
```
backend/ai/abstraction.py                              # Migrated google-generativeai → google-genai (native async)
backend/requirements.txt                                # google-generativeai → google-genai
backend/pyproject.toml                                  # Added [tool.ruff.lint] E741, pytest filterwarnings
backend/tests/test_integration.py                       # NEW — 12 integration tests (full flow + error format audit)
Barkain/Features/Shared/Components/SavingsBadge.swift   # Fixed: originalPrice now used for percentage display
backend/modules/m2_prices/models.py                     # D4 comment — TimescaleDB PK documented
backend/modules/m1_product/service.py                   # D5 comment — rollback safety documented
backend/modules/m2_prices/service.py                    # D9, D11 comments — cache and listing selection documented
backend/modules/m2_prices/container_client.py           # D10 comment — circuit-breaker deferred
containers/*/server.py (12 files)                       # D6 TODO — auth deferred to Phase 2
containers/README.md                                    # D7 note — server.py duplication documented
```

### Key Files Created/Modified (Step 2a)
```
backend/ai/abstraction.py                              # Extended — Anthropic/Claude Opus (claude_generate, claude_generate_json, claude_generate_json_with_usage)
backend/ai/prompts/watchdog_heal.py                    # NEW — Opus heal + diagnose prompt templates
backend/workers/watchdog.py                            # NEW — Watchdog supervisor agent (health checks, classification, self-healing, escalation)
backend/modules/m2_prices/health_monitor.py            # NEW — Retailer health monitoring service
backend/modules/m2_prices/health_router.py             # NEW — GET /api/v1/health/retailers endpoint
backend/app/errors.py                                  # NEW — Shared error response helpers (DRY format)
containers/base/                                       # NEW — Shared container base image (Dockerfile, server.py, entrypoint.sh)
scripts/run_watchdog.py                                # NEW — Watchdog CLI (--check-all, --heal, --status, --dry-run)
infrastructure/migrations/versions/0002_price_history_composite_pk.py  # NEW — Composite PK migration
backend/ai/prompts/upc_lookup.py                       # Updated — broadened for all product categories
backend/modules/m1_product/service.py                  # Updated — Gemini null retry with broader prompt
backend/modules/m2_prices/service.py                   # Updated — shorter Redis TTL (30min for 0-result)
```

### Key Files Created/Modified (Scan-to-Prices Live Demo, 2026-04-10)

Branch: `phase-2/scan-to-prices-deploy`. 5 commits, 9 files, ~700 lines.

```
containers/amazon/extract.sh                           # Updated — exec 3>&1 / exec 1>&2, python3 JSON dump via >&3, fallback echo via >&3 (SP-1)
containers/best_buy/extract.sh                          # Updated — same fd-3 pattern + uses new a.sku-title walker (SP-1)
containers/best_buy/extract.js                          # Updated — a.sku-title walker replaces .sku-item selector (live Best Buy React/Tailwind migration, 2026-04-10)
containers/base/server.py                              # Updated — EXTRACT_TIMEOUT env-overridable, default 60s → 180s (SP-2)
containers/base/entrypoint.sh                          # Updated — rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 before Xvfb, sleep 1s → 2s (SP-3)
backend/modules/m2_prices/adapters/walmart_firecrawl.py # Fixed — Firecrawl v2 API: top-level `country` → nested `location.country` (SP-4)
backend/modules/m2_prices/service.py                   # Fixed — `_pick_best_listing` filters `price > 0` before min() to skip parse-failure listings (SP-7)
Barkain/Services/Networking/APIClient.swift             # Fixed — dedicated URLSession with timeoutIntervalForRequest=240, timeoutIntervalForResource=300 (SP-8)
Config/Debug.xcconfig                                   # Updated — Mac LAN IP for physical device testing with switch-back comment
scripts/ec2_deploy.sh                                   # NEW — build + run barkain-base + 3 retailer containers with health checks
scripts/ec2_tunnel.sh                                   # NEW — forward ports 8081-8091 from Mac to EC2 with verification
scripts/ec2_test_extractions.sh                         # NEW — live extraction smoke test (Sony WH-1000XM5 + AirPods Pro) with pass/fail markdown table
containers/walmart/TROUBLESHOOTING_LOG.md               # NEW — prior-session Walmart PerimeterX notes
Barkain Prompts/Scan_to_Prices_Validation_Results.md    # NEW — chronological record of the run
Barkain Prompts/Error_Report_Scan_to_Prices_Deployment.md  # NEW — 10 issues + 8 latent, viability rated
Barkain Prompts/Conversation_Summary_Scan_to_Prices_Deployment.md  # NEW — session summary with decisions + learnings
```

**Env-only overrides applied to Mike's `.env` (not committed; documented so future sessions apply the same):**
- `CONTAINER_URL_PATTERN=http://localhost:{port}` (was `http://localhost:808{port}` from Step 1c — silently rotted when Step 1d changed port format, SP-5)
- `CONTAINER_TIMEOUT_SECONDS=180` (was 30 — too short for live Best Buy, SP-6)
- `BARKAIN_DEMO_MODE=1` (bypasses Clerk auth for physical device testing)

### Key Files Created/Modified (Walmart Adapter Routing, post-Step-2a)
```
backend/modules/m2_prices/adapters/__init__.py         # NEW — adapters subpackage marker
backend/modules/m2_prices/adapters/_walmart_parser.py  # NEW — shared __NEXT_DATA__ → ContainerResponse logic (challenge detection, itemStacks walker, sponsored filter, condition inference, price shape coercion)
backend/modules/m2_prices/adapters/walmart_http.py     # NEW — Decodo residential proxy adapter (httpx, Chrome 132 headers, username auto-prefix, password URL-encode, 1-retry on challenge, per-request wire_bytes logging)
backend/modules/m2_prices/adapters/walmart_firecrawl.py # NEW — Firecrawl managed API adapter (demo default; same parser)
backend/modules/m2_prices/container_client.py          # Updated — added `_extract_one` router, `_resolve_walmart_adapter`, `walmart_adapter_mode` attr, `_cfg` hold
backend/app/config.py                                  # Updated — added WALMART_ADAPTER, FIRECRAWL_API_KEY, DECODO_PROXY_USER, DECODO_PROXY_PASS, DECODO_PROXY_HOST
.env.example                                           # Updated — documented each new env var with comments describing when it's required and how to obtain
backend/tests/fixtures/walmart_next_data_sample.html   # NEW — realistic __NEXT_DATA__ fixture (4 real products + 1 sponsored placement)
backend/tests/fixtures/walmart_challenge_sample.html   # NEW — minimal "Robot or human?" PX challenge page
backend/tests/modules/test_walmart_http_adapter.py     # NEW — 15 tests (proxy URL builder, happy path, challenge retry semantics, error surfaces, parser edge cases)
backend/tests/modules/test_walmart_firecrawl_adapter.py # NEW — 9 tests (happy path, request-shape, error surfaces)
backend/tests/modules/test_container_client.py         # Updated — `_setup_client` fixture sets `walmart_adapter_mode = "container"`
backend/tests/modules/test_container_retailers.py      # Updated — same fixture update (walmart in ports dict triggers router)
```

---

## What's Next

1. **Phase 1 COMPLETE** — tagged v0.1.0. Full barcode scan → 11-retailer price comparison demo operational.
2. **Step 2a COMPLETE.** Walmart adapter routing (walmart_http + walmart_firecrawl) landed dormant with `WALMART_ADAPTER=container` default — flip to `firecrawl` for demo, `decodo_http` for production.
3. **Scan-to-Prices Live Demo COMPLETE** (2026-04-10) — 3-retailer end-to-end validated on physical iPhone. 7 live-run bugs fixed on `phase-2/scan-to-prices-deploy`. EC2 instance `i-09ce25ed6df7a09b2` stopped, ready to start again with `aws ec2 start-instances`.
4. **Blockers before Step 2b can start (HIGH priority):**
   - **Product-match relevance scoring (SP-10):** design session needed. Retailer on-site search returns similar-but-not-identical products; `_pick_best_listing` needs a relevance guardrail before any user-facing demo. See `Barkain Prompts/Error_Report_Scan_to_Prices_Deployment.md` SP-10 for approach options.
   - **Gemini UPC accuracy (SP-L4):** 3/3 test UPCs resolved wrong. Needs UPCitemdb second-opinion fallback or confidence scoring.
   - **Rotate leaked GitHub PAT (SP-L1):** `gho_UUsp9ML…` in `~/barkain/.git/config` on EC2.
5. **Lower-priority pre-fixes for Step 2b:** backfill fd-3 stdout pattern to the other 8 retailer extract.sh files (SP-L2), Amazon extract.js title selector regression (SP-9), Walmart first-party filter in `_walmart_parser.py` (SP-L5), streaming per-retailer results to iPhone instead of blocking (SP-L7), real-API contract tests for vendor adapters (SP-4 test gap).
6. **Phase 2 continues:** Step 2b (M5 Identity Profile), after the above blockers are addressed.

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
| AI SDK | google-genai (from google-generativeai) | Deprecated package; new SDK has native async, no asyncio.to_thread needed | Apr 2026 |
| UPC lookup model | gemini-3.1-flash-lite-preview | Faster and cheaper for UPC resolution; thinking + Google Search grounding for accuracy | Apr 2026 |
| UPC prompt architecture | System instruction (reasoning, cached) + user prompt (UPC + format constraint) | System instruction is cached by Gemini, minimizing per-call tokens. User prompt is just the UPC + output format | Apr 2026 |
| Gemini output | `device_name` only (no reasoning/brand/category in output) | Simpler parsing, faster responses. Brand/category populated by UPCitemdb fallback or future enrichment | Apr 2026 |
| Container scraping on ARM | Not viable for local demo | x86 emulation too slow (60-180s); containers work on native x86 cloud instances (5-8s). Demo relies on Gemini product resolution only | Apr 2026 |
| App Transport Security | NSAllowsLocalNetworking=true | Permits HTTP to LAN IPs for physical device testing against local backend | Apr 2026 |
| API base URL | Configurable via xcconfig → Info.plist → AppConfig.swift | Debug.xcconfig sets localhost; change to Mac IP for physical device testing. Runtime reads from Bundle.main.infoDictionary | Apr 2026 |
| Demo mode auth bypass | BARKAIN_DEMO_MODE=1 env var | Bypasses Clerk JWT in dependencies.py for local testing. NOT for production | Apr 2026 |
| AI SDK (Anthropic) | anthropic SDK (async) | Same lazy singleton + retry pattern as Gemini. YC credits cover Opus cost for Watchdog | Apr 2026 |
| HTTP-only retailer adapters | amazon, target, ebay_new can drop browser containers | 10-retailer AWS EC2 probe (2026-04-10): these 3 pass curl+Chrome-headers 5/5 from datacenter IPs with `__NEXT_DATA__` or direct HTML product data. 14-35× faster, ~490 MB RAM saved per retailer, ~1 050 LOC net deleted. See `docs/SCRAPING_AGENT_ARCHITECTURE.md` Appendix A | Apr 2026 |
| Firecrawl for 7 tough retailers | walmart, best_buy, sams_club, backmarket, ebay_used, home_depot, lowes via Firecrawl managed service | Firecrawl probe (2026-04-10): 10/10 retailers pass including all 5 that failed AWS direct-HTTP and both "inconclusive" ones. HD + Lowe's now known to have `__APOLLO_STATE__` SSR data. ~1.5 credits per scrape, ~$0.0088 per 10-retailer comparison on Standard tier ($83/mo). ~31s P50 cold, ~1s hot-cached. See Appendix B | Apr 2026 |
| Production scraping architecture | Collapse browser containers to local-dev-only; use Firecrawl for production | Containers don't work from any cloud (IP blocks at edge). Firecrawl solves all 10 retailers from anywhere. Hybrid plan: direct HTTP for amazon/target/ebay_new ($0), Firecrawl for the other 7 ($0.0088/comparison). Containers become local-dev + emergency fallback. Adapter interface in M2 with per-retailer mode config. See Appendix B.7-B.8 | Apr 2026 |
| Decodo residential proxy for walmart-only production path | Decodo rotating residential (US-targeted) as post-demo walmart path | 5/5 Walmart scrapes PASS via Decodo US residential pool (Verizon Fios). Wire body ~121 KB/scrape → 8,052 scrapes/GB. $0.000466/scrape at $3.75/GB (3 GB tier) → **2.7× cheaper than Firecrawl** per request, no concurrency cap. See Appendix C. Username auto-prefixed with `user-` and suffixed with `-country-us` by the adapter | Apr 2026 |
| walmart_http adapter lands now, dormant until launch | `WALMART_ADAPTER={container,firecrawl,decodo_http}` feature flag | Demo default = `firecrawl`; flip to `decodo_http` post-demo. All 3 paths return `ContainerResponse`, routed by `ContainerClient._extract_one`. Other 10 retailers still use the container dispatch unchanged. 24 new tests (15 walmart_http + 9 firecrawl), 128 total passing. See Appendix C.6–C.8 | Apr 2026 |
| extract.sh fd-3 stdout convention | Every retailer extract.sh must reserve fd 3 as real stdout via `exec 3>&1; exec 1>&2`, and emit final JSON via `>&3` | `agent-browser` writes progress lines ("✓ Done", "✓ <page title>", "✓ Browser closed") to STDOUT. Phase 1 respx-mocked tests never exercised this boundary, so every retailer extract.sh shipped with a latent `PARSE_ERROR` bug. Discovered on first live run (SP-1). See `docs/SCRAPING_AGENT_ARCHITECTURE.md` § Required extract.sh conventions | Apr 2026 |
| EXTRACT_TIMEOUT baseline | 180 s default, env-overridable via `EXTRACT_TIMEOUT` | Live Best Buy runs at ~90 s end-to-end (warmup + scroll + DOM eval on t3.xlarge); Amazon ~30 s; old 60 s default tripped Best Buy every time. 180 s gives 2× headroom. | Apr 2026 |
| Xvfb lock cleanup in entrypoint | Always `rm -f /tmp/.X99-lock /tmp/.X11-unix/X99` before starting Xvfb | Without it, `docker restart <retailer>` leaves a stale lock, Xvfb refuses to bind :99, uvicorn starts without X, and every extraction dies with `Missing X server or $DISPLAY`. Idempotent guard costs nothing on first boot. (SP-3) | Apr 2026 |
| iOS URLSession timeout | Dedicated session with `timeoutIntervalForRequest=240`, `timeoutIntervalForResource=300` | Default 60 s trips before ~94 s backend round-trip. Progressive loading UI is still cosmetic — streaming per-retailer results is the real long-term fix (SP-L7). (SP-8) | Apr 2026 |
| Zero-price listing guard | `_pick_best_listing` filters `price > 0` before `min()` | extract.js occasionally parses price as 0 when DOM node is missing/lazy (Amazon especially). `min(key=price)` then returns the zero-price listing as "cheapest". Defensive guard at service boundary; extract.js root-cause fix deferred. (SP-7) | Apr 2026 |
| EC2 dev iteration pattern | Local Mac backend + SSH tunnel (8081–8091) → EC2 x86 container runtime | Local backend keeps hot reload / breakpoints / real env; containers run on EC2 for real x86 Chromium (ARM is non-viable per L13). `scripts/ec2_tunnel.sh` forwards ports, `CONTAINER_URL_PATTERN=http://localhost:{port}` unchanged. See `docs/DEPLOYMENT.md` § Live dev loop | Apr 2026 |
| Product-match relevance scoring | Required before any user-facing demo | SP-10: each retailer's on-site search returns similar-but-not-identical products and `_pick_best_listing` picks cheapest regardless. Example: M4 Mac mini scan returned correct SKU on Best Buy but wrong-spec Mac mini on Amazon. Approach TBD (lexical / structural / embedding / retailer-weighted) — belongs in Step 2b design. | Apr 2026 |
