# CLAUDE.md — Barkain

> **Purpose:** Root orientation for AI coding agents. This file alone should let a new session understand the project, find anything, and follow conventions.
> **Last updated:** April 2026 (v4.2 — Step 2c-val SSE live smoke test complete)

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
│   ├── CHANGELOG.md                   ← Per-step file inventories + full decision log
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
**Step 2b — Demo Container Reliability: COMPLETE** ✅ (2026-04-11)
**Step 2b-val — Live Validation Pass: COMPLETE** ✅ (2026-04-12, branch `phase-2/step-2b`)
**Post-2b-val — Simulator + Relevance + Retailer-Status Hardening: COMPLETE** ✅ (2026-04-12)
**Chore — CHANGELOG.md created, CLAUDE.md slimmed from ~74K → ≤35K chars** ✅ (2026-04-13)
**Step 2b-final — Close Out (Gemini model field + post-2b-val test coverage + CI + EC2 verification): COMPLETE** ✅ (2026-04-13)
**Step 2c — Streaming Per-Retailer Results (SSE): COMPLETE** ✅ (2026-04-13, merged to main as PR #8 → `9ceafe1`)
**Step 2c-val — SSE Live Smoke Test: COMPLETE** ✅ (2026-04-13, 5 PASS / 1 FUNCTIONAL-PASS-UX-FAIL, no fixes applied — **new latent bug 2c-val-L6 found: iOS client always falls back to batch, never renders progressive stream events; see `docs/CHANGELOG.md` §Step 2c-val**)

- AI abstraction: ✅ (Gemini + Claude Opus)
- Watchdog supervisor: ✅ (nightly health checks, self-healing via Opus)
- Health monitor: ✅ (GET /api/v1/health/retailers)
- Watchdog CLI: ✅ (`scripts/run_watchdog.py`)
- Shared container base image: ✅ (`containers/base/`)
- Pre-fix: PriceHistory composite PK: ✅ (migration 0002)
- Pre-fix: Error response helper: ✅ (`backend/app/errors.py`)
- Pre-fix: Gemini null retry: ✅
- Pre-fix: Shorter Redis TTL: ✅ (30min for 0-result, 6hr for success)
- Pre-fix: Broadened UPC prompt: ✅ (all product categories)
- Architecture documents: ✅
- All guiding docs: ✅ (13 docs in `docs/`, v3 updated April 2026)
- Apple Developer account: ✅
- Clerk project: ✅
- Gemini API: ✅ (primary UPC resolution)
- Anthropic API: ✅ (Watchdog self-healing via Claude Opus)
- UPCitemdb API: ✅ (cross-validation second opinion; free tier 100/day)
- API sign-ups (Best Buy, eBay, Keepa): NOT STARTED (production optimization, not required for demo)
- Docker local dev: ✅ (`barkain-db`, `barkain-db-test`, `barkain-redis`)
- TimescaleDB: ✅ (v2.26.1)
- MCP servers: ✅ (Postgres Pro, Redis, Context7, Clerk, XcodeBuildMCP)
- GitHub repo: ✅ (private)
- CLI tools: ✅ (all 16 installed)
- Xcode: ✅ (26.4)
- Visual prototype: NOT STARTED
- Database schema: ✅ (21 tables, migration 0001, TimescaleDB hypertable on `price_history`)
- FastAPI skeleton: ✅ (health, CORS, security headers, structured errors)
- Clerk auth middleware: ✅ (JWT via `clerk-backend-api`, `get_current_user` dependency)
- Rate limiting: ✅ (Redis sliding window, per-user, 3 tiers)
- Retailer seed: ✅ (11 Phase 1 retailers)
- AI abstraction layer: ✅ (`backend/ai/abstraction.py` — google-genai async, thinking + grounding)
- UPC lookup prompt: ✅ (`backend/ai/prompts/upc_lookup.py` — cached system prompt, returns `device_name` + `model` shortest unambiguous identifier)
- M1 Product resolution: ✅ (POST `/api/v1/products/resolve` — Gemini + UPCitemdb cross-validation, Redis 24hr cache)
- Container template: ✅ (`containers/template/`)
- Container Dockerfile: ✅ (Chromium + agent-browser + Xvfb + FastAPI)
- Container client: ✅ (`backend/modules/m2_prices/container_client.py` — parallel dispatch, partial failure tolerance)
- M2 schemas: ✅
- Container config: ✅ (`CONTAINER_URL_PATTERN`, ports 8081–8091)
- Retailer containers batch 1: ✅ (Amazon, Walmart, Target, Sam's Club, FB Marketplace)
- Retailer containers batch 2: ✅ (Best Buy, Home Depot, Lowe's, eBay New, eBay Used, BackMarket)
- M2 Price Aggregation Service: ✅ (`backend/modules/m2_prices/service.py` — cache → dispatch → normalize → upsert → cache)
- M2 Price endpoint: ✅ (GET `/api/v1/prices/{product_id}`)
- M2 Price streaming (Step 2c): ✅ (GET `/api/v1/prices/{product_id}/stream` — SSE, `asyncio.as_completed`, per-retailer results arrive as they complete)
- M2 Redis caching: ✅ (3-tier: Redis → DB → containers)
- M2 Price upsert: ✅ (ON CONFLICT on product_id+retailer_id+condition)
- M2 Price history: ✅ (append-only TimescaleDB hypertable)
- iOS Xcode project: ✅ (`com.molatunji3.barkain`, iOS 17.6+, xcconfig Debug/Release)
- iOS design system: ✅ (Colors, Spacing, Typography)
- iOS data models: ✅ (Product, PriceComparison, RetailerPrice)
- iOS API client: ✅ (APIClientProtocol + APIClient async, typed)
- iOS SSE consumer (Step 2c): ✅ (`Barkain/Services/Networking/Streaming/SSEParser.swift` + `RetailerStreamEvent.swift` + `APIClient.streamPrices` returns `AsyncThrowingStream<RetailerStreamEvent, Error>`; `ScannerViewModel` mutates `priceComparison` in place as events land; fallback to batch on stream failure)
- iOS barcode scanner: ✅ (AVFoundation EAN-13/UPC-A + UPC-A normalization + manual entry sheet)
- iOS navigation shell: ✅ (TabView: Scan/Search/Savings/Profile)
- iOS scanner feature: ✅ (ScannerView + ScannerViewModel)
- iOS shared components: ✅ (ProductCard, PriceRow, SavingsBadge, EmptyState, LoadingState, ProgressiveLoadingView)
- iOS price comparison UI: ✅ (PriceComparisonView — per-retailer status rows for all 11 retailers)
- iOS scan→compare flow: ✅ (full demo loop)

**Test counts:** 192 backend (192 passed / 6 skipped), 32 iOS unit, 0 UI, 0 snapshot.
**Build status:** Backend + iOS build clean. Backend serves health + product resolve + batch price comparison + streaming price comparison + retailer health endpoints; Amazon + Best Buy containers on EC2 `t3.xlarge`; Walmart via Firecrawl v2 adapter. With Step 2c SSE, iOS now scans barcode → resolves via Gemini → streams 3 retailers → displays walmart result at ~12s, amazon ~30s, best_buy ~91s (each arriving independently instead of blocking for ~90-120s). Batch endpoint still available as fallback. `ruff check` clean. Manual entry sheet functional on simulator. GitHub Actions backend-tests workflow runs unit tests on every PR touching `backend/**` or `containers/**`.

**Live demo runtime profile (2026-04-10, physical iPhone):**
- Gemini UPC resolve: 2–4 s
- Amazon container (EC2): ~30 s end-to-end
- Best Buy container (EC2): ~90 s end-to-end (dominant leg)
- Walmart Firecrawl adapter: ~30 s
- iOS total: ~90–120 s, dominated by Best Buy

**Known demo caveats (see `Barkain Prompts/Error_Report_Scan_to_Prices_Deployment.md` and `Barkain Prompts/Step_2b_val_Results.md`):**
- ~~**fd-3 stdout pattern latent on 8 retailers (SP-L2, MEDIUM):**~~ **RESOLVED in Step 2c** — backfilled to all 9 remaining `extract.sh` files (target, home_depot, lowes, ebay_new, ebay_used, sams_club, backmarket, fb_marketplace, walmart). All 11 retailer extract.sh files now use `exec 3>&1; exec 1>&2` + `>&3` on the final output.
- **GitHub PAT leaked in EC2 git config (SP-L1, HIGH):** `gho_UUsp9ML…` is embedded in `~/barkain/.git/config` on stopped EC2 instance `i-09ce25ed6df7a09b2`. Must be rotated.
- **EC2 containers run stale code (2b-val-L1, MEDIUM):** `amazon/extract.js`, `best_buy/extract.js`, and `best_buy/base-extract.sh` are hot-patched via `docker cp` on the running instance. The image on disk is stale; next stop+start without redeploy will revert. Run `scripts/ec2_deploy.sh` before the next session.
- ~~**Best Buy ~91s per request, 78s in page loads (2b-val-L2, HIGH for UX):**~~ **RESOLVED in Step 2c** via SSE streaming. The 91s Best Buy leg no longer blocks the iPhone — walmart (~12s) and amazon (~30s) now render the moment they complete, while best_buy streams in when it finishes. A `domcontentloaded` wait strategy on Best Buy itself is still a potential further speedup but no longer a UX blocker.
- **Integration test env loading (2b-val-L4, LOW):** `backend/tests/integration/test_real_api_contracts.py` reads env vars at module load, so pytest needs `set -a && source ../.env && set +a` before `BARKAIN_RUN_INTEGRATION_TESTS=1 pytest -m integration`. Conftest.py auto-load would fix this — deferred.
- **Supplier codes persist in DB (v4.0-L1, LOW):** `_clean_product_name` strips codes like `(CBC998000002407)` at query/scoring time but leaves the raw Gemini/UPCitemdb name in the DB. The iOS app displays the raw (uncleaned) name. If you want the display to also be clean, strip on insert in `m1_product/service.py` — one-line change.
- **Sub-variants without digits (v4.0-L2, MEDIUM):** the variant-token check only fires on the known set `{pro, plus, max, mini, ultra, lite, slim, air, digital, disc, se, xl, cellular, wifi, gps, oled}`. Products like "Samsung Galaxy Buds Pro" (1st gen) vs "Galaxy Buds 2 Pro" still pass token overlap because neither "1st gen" nor a distinguishing digit is present in the 1st-gen product name. Requires richer Gemini output.
- **GPU SKUs not distinguished (v4.0-L3, LOW):** RTX 4090 vs RTX 4080 — neither `pattern 5` (Title word + digit) nor `pattern 6` (camelCase + digit) nor `pattern 7` (brand camelCase + digit) matches `RTX 4090` (space-separated letter group + digit group). Token overlap alone may let the wrong GPU through. Fix: add a pattern like `\b[A-Z]{2,5}\s+\d{3,5}\b` if GPUs become a demo category.

> Per-step file inventories: see `docs/CHANGELOG.md`

---

## What's Next

1. **Phase 1 COMPLETE** — tagged v0.1.0. Full barcode scan → 11-retailer price comparison demo operational.
2. **Step 2a COMPLETE.** Walmart adapter routing (walmart_http + walmart_firecrawl) landed dormant with `WALMART_ADAPTER=container` default — flip to `firecrawl` for demo, `decodo_http` for production.
3. **Scan-to-Prices Live Demo COMPLETE** (2026-04-10) — 3-retailer end-to-end validated on physical iPhone. 7 live-run bugs fixed on `phase-2/scan-to-prices-deploy`. EC2 instance `i-09ce25ed6df7a09b2` stopped, ready to start again with `aws ec2 start-instances`.
4. **Step 2b COMPLETE** (2026-04-11) — Demo container reliability: UPCitemdb cross-validation (SP-L4), relevance scoring (SP-10), Amazon title fallback (SP-9), Walmart first-party filter (SP-L5). 146 backend tests passing.
5. **Step 2b-val Live Validation COMPLETE** (2026-04-12) — 5-test protocol against real Gemini / UPCitemdb / Firecrawl / Amazon-BestBuy-Walmart containers. 6/6 UPCs resolved at confidence 1.0 `gemini_validated`. Three latent regressions caught and fixed on the same branch:
   - **SP-9 regression** — Amazon title chain returned brand-only "Sony". Amazon now splits brand/product into sibling spans inside `h2` / `[data-cy="title-recipe"]`, and the sponsored-noise regex used ASCII `'` vs Amazon's curly `'`. Fix: rewrote `extractTitle()` to join all spans + added `['\u2019]` character class to sponsored noise regex. `containers/amazon/extract.js`.
   - **SP-10 regression** — `_MODEL_PATTERNS[0]` couldn't match hyphenated letter+digit models like `WH-1000XM5`, extracting "WH1000XM" instead, so the hard gate failed against all listings. Fix: optional hyphen between letter group and digit group + trailing `\d*` after alpha suffix. `backend/modules/m2_prices/service.py`.
   - **SP-10b new** — word+digit model names (`Flip 6`, `Clip 5`, `Stick 4K`) matched nothing in the old pattern list, so hard gate was skipped and a JBL Clip 5 listing cleared the 0.4 token-overlap floor for a JBL Flip 6 query. Fix: added `\b[A-Z][a-z]{2,8}\s+\d+[A-Z]?\b` (Title-case only, no IGNORECASE). `backend/modules/m2_prices/service.py`.
6. **Post-2b-val hardening COMPLETE** (2026-04-12) — driven by live-sim testing of untested UPCs (iPhone 16, PS5, AirPods variants) from the iOS simulator. Ten additional fixes across backend + iOS on `phase-2/step-2b`. 146 tests still green. See `docs/CHANGELOG.md` § Post-2b-val Hardening for the full file list and `Barkain Prompts/Error_Report_Post_2b_val_Sim_Hardening.md` for the per-bug narrative. Headlines:
   - Manual UPC entry sheet in iOS scanner (enables simulator testing).
   - Per-retailer status system: `retailer_results` with `{success, no_match, unavailable}` — all 11 retailers render distinct visual states.
   - Error code → status mapping (bot blocks → `unavailable`, empty results → `no_match`).
   - Supplier-code cleanup in `_clean_product_name` (fixes iPhone 16 → iPhone SE fuzz match).
   - Word-boundary identifier regex (kills `iPhone 16` → `iPhone 16e` prefix match).
   - Accessory hard filter (kills screen-protector false positives).
   - Variant-token equality check (kills iPhone 16 → iPhone 16 Pro/Plus/Max matches, PS5 Slim Disc → Digital Edition, iPad Pro → iPad Air).
   - camelCase model regex patterns 6 + 7 (AirPods 2, PlayStation 5, MacBook 14, iPhone/iPad).
   - Amazon + Best Buy + Walmart: condition detection, carrier/installment filter, $X/mo stripping.
7. **Step 2b-final COMPLETE** (2026-04-13) — closes PR #3 loose ends before merge to main:
   - Gemini system instruction upgraded to emit `device_name` + `model` (shortest unambiguous identifier). `model` is threaded through `_cross_validate` → `source_raw.gemini_model` → `ProductResponse.model` → `_score_listing_relevance`.
   - `_MODEL_PATTERNS[5]` (GPU `\b[A-Z]{2,5}\s+\d{3,5}\b`) + `_ORDINAL_TOKENS` equality rule fix the F.5 generation-without-digit and GPU-SKU limitations.
   - 35 new unit tests: 2 M1 model-field, 5 M2 gemini_model relevance, 24 post-2b-val hardening (`_clean_product_name`, `_is_accessory_listing`, `_ident_to_regex`, variant equality, `_classify_error_status`, retailer_results end-to-end), 4 carrier-listing. `TESTING.md` "most load-bearing test-debt item" paid down.
   - `.github/workflows/backend-tests.yml` runs unit tests on every PR touching `backend/**` or `containers/**`. TimescaleDB + Redis services, fake API keys, `BARKAIN_DEMO_MODE=1`. Integration tests remain gated on `BARKAIN_RUN_INTEGRATION_TESTS=1`.
   - `scripts/ec2_deploy.sh` appends MD5 comparison of each container's `/app/extract.js` against the repo copy — makes hot-patch drift visible on next deploy.
   - `backend/tests/integration/conftest.py` auto-loads `.env` when `BARKAIN_RUN_INTEGRATION_TESTS=1`. `test_upcitemdb_lookup` opt-out via `UPCITEMDB_SKIP=1`.
8. **Step 2c — Streaming Per-Retailer Results (SSE) COMPLETE** (2026-04-13) — replaces the 90-120s blocking `GET /api/v1/prices/{id}` with an SSE stream so each retailer lands on the iPhone the moment it finishes (walmart ~12s, amazon ~30s, best_buy ~91s — all independently). Highlights:
   - Backend: new `GET /api/v1/prices/{product_id}/stream` endpoint (`modules/m2_prices/router.py`) returning `text/event-stream`. New `PriceAggregationService.stream_prices()` async generator uses `asyncio.as_completed` to yield `retailer_result` / `done` / `error` events as each retailer resolves. Cache hit (Redis or DB) replays all events instantly with `done.cached=true`. Batch endpoint `GET /api/v1/prices/{id}` unchanged and still wired as fallback.
   - New `backend/modules/m2_prices/sse.py` — `sse_event()` wire-format helper + `SSE_HEADERS` constant (`Cache-Control: no-cache`, `X-Accel-Buffering: no`, `Connection: keep-alive`).
   - iOS: new `Barkain/Services/Networking/Streaming/SSEParser.swift` (stateful `feed(line:)` parser + `events(from:URLSession.AsyncBytes)` async wrapper) and `RetailerStreamEvent.swift` typed events (`retailerResult`, `done`, `error`).
   - iOS: `APIClient.streamPrices(productId:forceRefresh:)` returns `AsyncThrowingStream<RetailerStreamEvent, Error>` backed by `URLSession.bytes(for:)`. Non-2xx responses drain error body and throw a matching `APIError` variant.
   - iOS: `ScannerViewModel.fetchPrices()` consumes the stream, lazy-seeds + mutates a local `PriceComparison` on every event, and falls back to `getPrices` (batch) on stream errors or if the stream closes without a `done` event. `PriceComparison` struct fields changed from `let` to `var` to support in-place mutation.
   - iOS: `PriceComparisonView` unchanged structurally — it already handles the growing retailer list. Added `.animation(.default, value:)` on the retailer list for smooth row transitions. `ProgressiveLoadingView` is no longer invoked in the scanner flow (the progressive UI IS the comparison view). `ScannerView.priceLoadingView` replaced with a minimal spinner for the brief window before the first event seeds `priceComparison`.
   - Pre-fix PF-1: fd-3 stdout backfill for the 9 remaining `extract.sh` files (see above).
   - Pre-fix PF-2: removed `pytestmark = pytest.mark.asyncio` from `backend/tests/modules/test_m2_prices.py` — silences 33 pytest warnings (`asyncio_mode = "auto"` is already set in `pyproject.toml`).
   - Tests: +11 backend stream tests (`backend/tests/modules/test_m2_prices_stream.py` — event order, success/no_match/unavailable payloads, Redis/DB cache short-circuit, force_refresh bypass, SSE content-type, 404 before stream, end-to-end wire parsing, unknown product raises), +5 SSE parser tests (`BarkainTests/Services/Networking/SSEParserTests.swift`), +6 scanner stream tests (`ScannerViewModelTests.swift` — incremental state, sortedPrices live updates, error event, thrown error fallback, closed-without-done fallback, bestPrice tracking).
9. **Remaining pre-fixes (not blockers):**
   - **Redeploy EC2 containers (2b-val-L1):** run `scripts/ec2_deploy.sh` to sync `i-09ce25ed6df7a09b2` with the repo — currently hot-patched via `docker cp` for `amazon/extract.js`, `bestbuy/extract.js`, and `bestbuy/base-extract.sh`. Next stop+start without redeploy will revert. Post-deploy MD5 verification block now flags drift automatically.
10. **Phase 2 continues:** Step 2d (M5 Identity Profile) or further container reliability work.

---

## Key Decisions Log

> Full decision log with rationale: see `docs/CHANGELOG.md`
>
> Quick reference (decisions still load-bearing on current code):
> - Container auth: VPC-only, no bearer tokens
> - Walmart adapter: `WALMART_ADAPTER` env var routes to container/firecrawl/decodo
> - fd-3 stdout convention: all extract.sh files must use `exec 3>&1; exec 1>&2`
> - EXTRACT_TIMEOUT: 180s default, env-overridable
> - Relevance scoring: model-number hard gate + variant-token equality + ordinal equality + brand match + 0.4 token overlap threshold
> - UPCitemdb cross-validation: always called alongside Gemini, brand agreement picks winner
> - Product-match relevance: required before any user-facing demo
> - Gemini output: `device_name` + `model` (shortest unambiguous identifier — generation markers, capacity, GPU SKUs); `model` is stored in `source_raw.gemini_model` and feeds relevance scoring
> - CI: `.github/workflows/backend-tests.yml` runs unit tests on every PR touching `backend/**` or `containers/**`; integration tests stay behind `BARKAIN_RUN_INTEGRATION_TESTS=1`
