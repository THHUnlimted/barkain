# CLAUDE.md — Barkain

> **Purpose:** Root orientation for AI coding agents. This file alone should let a new session understand the project, find anything, and follow conventions.
> **Last updated:** April 2026 (v4.5 — Step 2e M5 Card Portfolio + reward matching complete)

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
**Step 2c-val — SSE Live Smoke Test: COMPLETE** ✅ (2026-04-13, 5 PASS / 1 FUNCTIONAL-PASS-UX-FAIL — latent bug 2c-val-L6 found, **RESOLVED in Step 2c-fix below**; see `docs/CHANGELOG.md` §Step 2c-val)
**Step 2c-fix — iOS SSE Consumer Fix: COMPLETE** ✅ (2026-04-13, branch `fix/ios-sse-consumer`) — root-caused 2c-val-L6 via new `com.barkain.app`/`SSE` os_log category; replaced `URLSession.AsyncBytes.lines` with a manual byte-level line splitter over raw `AsyncSequence<UInt8>`; fixed 2c-val-L7 with `API_BASE_URL=http://127.0.0.1:8000`; deleted dead `ProgressiveLoadingView.swift`. Live-verified against real backend: stream delivers events incrementally (897ms gap between fast retailers and Walmart on a non-cached run), `sawDone=true` fires, **zero** fallback-to-batch events on the happy path. 36/32→36 iOS tests green, 192 backend tests unchanged. See `docs/CHANGELOG.md` §Step 2c-fix.
**Step 2d — M5 Identity Profile + Discount Catalog: COMPLETE** ✅ (2026-04-14, branch `phase-2/step-2d`) — first feature that differentiates Barkain from coupon/cashback apps: identity-verified discount discovery layered on the live price stream. Backend: migration 0003 adds `is_government` column to `user_discount_profiles` (16 booleans total); new `m5_identity/{schemas,service,router}.py` with 4 endpoints (`GET/POST /api/v1/identity/profile`, `GET /api/v1/identity/discounts?product_id=`, `GET /api/v1/identity/discounts/all`); pure-SQL matching < 150ms with `(retailer_id, program_name)` dedup so Samsung's 8-eligibility-row program surfaces as 1 card. `scripts/seed_discount_catalog.py` seeds 8 brand-direct retailers (samsung_direct, apple_direct, hp_direct, dell_direct, lenovo_direct, microsoft_direct, sony_direct, lg_direct) + 52 discount program rows (11 templates expanded per eligibility_type). `scripts/seed_retailers.py` flipped `amazon.supports_identity=True`. iOS: new `IdentityProfile.swift` model (4 structs), 3 APIClient methods on all 3 protocol conformers, `IdentityOnboardingView` + `IdentityOnboardingViewModel` (3-step wizard, enum-driven), replaced `ProfilePlaceholderView` with full `ProfileView` (chips summary + edit button), onboarding sheet mounts from `ContentView` gated by `@AppStorage("hasCompletedIdentityOnboarding")` (swipe-down dismiss does NOT set the flag — re-shows next launch). `ScannerViewModel.fetchIdentityDiscounts` fires at two call sites (post-SSE-success AND post-batch-fallback) — never inside the `.done` case, to avoid racing the still-streaming retailer rows. Non-fatal: discount fetch failure never sets `priceError`. `PriceComparisonView` reveals `IdentityDiscountsSection` (with `.animation(.easeInOut)`) after the stream done event; when no discounts AND user hasn't onboarded, an `IdentityOnboardingCTARow` surfaces with a tap-to-open-sheet callback wired via `ScannerView`. Tests: 30 new backend (18 in `test_m5_identity.py` including profile CRUD, multi-group union, dedup, percentage/cap/fixed savings math, performance gate; 12 in `test_discount_catalog_seed.py` lint asserting eligibility vocabulary, verification methods, discount types, no dup tuples, military coverage). 7 new iOS (4 in `IdentityOnboardingViewModelTests`, 3 in `ScannerViewModelTests` for the SSE-done-then-fetch flow). 192→222 backend tests, 36→43 iOS tests. See `docs/CHANGELOG.md` §Step 2d.
**Step 2e — M5 Card Portfolio + Reward Matching: COMPLETE** ✅ (2026-04-14, branch `phase-2/step-2e`) — completes Barkain's second pillar: a single scan now surfaces price + identity discount + card reward in one view. Backend: `scripts/seed_card_catalog.py` seeds 30 Tier 1 cards (`CARDS` list; creates `idx_card_reward_programs_product` unique index on `(card_issuer, card_product)` since migration 0001 lacks one); `scripts/seed_rotating_categories.py` seeds Q2 2026 for Freedom Flex + Discover it ONLY (Cash+ / Customized Cash remain user-selected-only, resolved via `user_category_selections`). `m5_identity/card_{schemas,service,router}.py` — `CardService` with 8 methods + `_RETAILER_CATEGORY_TAGS` in-code map bridging category strings to retailer ids; 7 endpoints under `/api/v1/cards/*` (`catalog`, `my-cards` GET/POST, `my-cards/{id}` DELETE, `my-cards/{id}/preferred` PUT, `my-cards/{id}/categories` POST, `recommendations?product_id=`). Zero-LLM matching: single four-query preload (user cards joined with programs, active rotating, active user selections, retailer prices joined with retailer names) then in-memory max over (base, rotating, user-selected, static) with winning `is_rotating_bonus`/`is_user_selected_bonus`/`activation_required`/`activation_url` preserved. Target <50ms, measured <150ms CI. Pre-fix: PF-1 URL sweep rotated Lenovo's broken `/discount-programs` + `/education-store` URLs to the current `/us/en/d/deals/*` paths; PF-2 added commented `DATABASE_URL` to `.env.example`. iOS: new `CardReward.swift` with 6 Sendable structs (no raw JSONB on the client — `user_selected_allowed` is flattened server-side). `APIClientProtocol` gains 7 methods; 4 conformers (concrete + Mock + 3 previews). New `Endpoints.swift` cases; `.put` / `.delete` HTTPMethod added; `requestVoid` helper for 204 / `{"ok": true}` responses. `CardSelectionViewModel` + `CardSelectionView` (List grouped by issuer, star-toggle for preferred, swipe-to-delete, search) + `CategorySelectionSheet` (drives off `pendingCategorySelection` when adding a Cash+/Customized Cash card). `ProfileView` gains "My Cards" chip section with preferred-star badge + Add/Manage buttons. `PriceRow` accepts optional `cardRecommendation` and renders an inline subtitle ("Use Chase Freedom Flex for 5x ($12.50 back)") plus an "Activate" Link when rotating. `PriceComparisonView` threads `viewModel.cardRecommendations` into each success row by retailer_id and surfaces an `addCardsCTA` button (keyed off `!userHasCards && recommendations.isEmpty`) that opens `CardSelectionView` via the new `onRequestAddCards` callback wired from `ScannerView`. `ScannerViewModel.fetchCardRecommendations` chains at the END of `fetchIdentityDiscounts` — inheriting 2d's two-call-site pattern (post-SSE-done AND post-batch-fallback) for free. Non-fatal on failure: never sets `priceError`, never clears `userHasCards` on transient errors. Tests: 30 new backend (22 in `test_m5_cards.py`: catalog/CRUD/matching/perf gate + `_quarter_to_dates` unit test; 8 in `test_card_catalog_seed.py`: lint asserting vocab, dup detection, Cash+/Customized Cash NOT in rotating). 10 new iOS (7 in `CardSelectionViewModelTests.swift`: load/filter/add/remove/preferred/categories/user-selected category sheet priming; 3 in `ScannerViewModelTests.swift`: fires-after-identity, empty-on-failure-non-fatal, cleared-on-new-scan). 222→252 backend tests, 43→53 iOS tests. See `docs/CHANGELOG.md` §Step 2e.

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
- iOS price comparison UI: ✅ (PriceComparisonView — per-retailer status rows for all 11 retailers + identity discounts section revealed after stream done)
- iOS scan→compare flow: ✅ (full demo loop)
- M5 Identity backend: ✅ (`backend/modules/m5_identity/{schemas,service,router}.py` — 4 endpoints, zero-LLM SQL matching < 150ms, dedup by `(retailer_id, program_name)`)
- Discount catalog: ✅ (8 brand-direct retailers + 52 discount_program rows via `scripts/seed_discount_catalog.py`)
- Identity migration: ✅ (migration 0003 adds `is_government` column)
- iOS onboarding flow: ✅ (`IdentityOnboardingView` 3-step wizard + `IdentityOnboardingViewModel` + `@AppStorage("hasCompletedIdentityOnboarding")` gate on ContentView)
- iOS Profile tab: ✅ (`ProfileView` replaces placeholder — chips summary + edit button, auto-loads profile via `GET /api/v1/identity/profile`)
- iOS identity discounts reveal: ✅ (`IdentityDiscountsSection` + `IdentityDiscountCard` + `IdentityOnboardingCTARow`, fetched after SSE `done` OR after batch fallback success — non-fatal failure)
- M5 Card Portfolio backend: ✅ (`backend/modules/m5_identity/card_{schemas,service,router}.py` — 7 endpoints under `/api/v1/cards/*`, zero-LLM <50ms matching, `_RETAILER_CATEGORY_TAGS` in-code map)
- Card catalog: ✅ (30 Tier 1 cards across 8 issuers via `scripts/seed_card_catalog.py` — Chase ×7, Amex ×5, Capital One ×4, Citi ×4, Discover ×2, BofA ×3, Wells Fargo ×2, US Bank ×3)
- Rotating categories: ✅ (`scripts/seed_rotating_categories.py` — Q2 2026 for Freedom Flex + Discover it only; Cash+ / Customized Cash / Shopper Cash Rewards stay user-selected via `user_category_selections`)
- iOS card portfolio UI: ✅ (`CardSelectionView` + `CardSelectionViewModel` + `CategorySelectionSheet` — List grouped by issuer, star-preferred, swipe-delete, per-card user-selected category picker)
- iOS Profile "My Cards" section: ✅ (chips with preferred star + Add/Manage buttons)
- iOS per-retailer card subtitle: ✅ (`PriceRow.cardRecommendation` — "Use [card] for [rate]x ($[amount] back)" + Activate link when rotating)
- iOS "Add your cards" CTA: ✅ (`PriceComparisonView.addCardsCTA` keyed off backend `userHasCards` field — no local `@AppStorage` flag)
- iOS card recommendations fetch chain: ✅ (`ScannerViewModel.fetchCardRecommendations` chained after `fetchIdentityDiscounts`, inheriting 2d's two-call-site pattern)

**Test counts:** 252 backend (252 passed / 6 skipped, +30 in Step 2e: 22 m5_cards + 8 seed-lint), 53 iOS unit (+10 in Step 2e: 7 CardSelectionViewModel + 3 fetchCardRecommendations), 0 UI, 0 snapshot.
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
9. **Step 2d — M5 Identity Profile + Discount Catalog COMPLETE** (2026-04-14) — first feature that differentiates Barkain from commodity coupon/cashback apps. Highlights:
   - Backend: migration 0003 adds `is_government` column. `m5_identity/{schemas,service,router}.py` expose 4 endpoints at `/api/v1/identity/*`. `IdentityService` does zero-LLM pure-SQL matching < 150ms, hitting `idx_discount_programs_eligibility` and deduping by `(retailer_id, program_name)` — Samsung's 8-eligibility-type program surfaces as ONE card for any matched user. `get_or_create_profile` upserts the `users` row first so Clerk stubs + demo mode never hit FK violations. `update_profile` is full-replace: missing fields fall to `False`.
   - Seed: `scripts/seed_discount_catalog.py` creates 8 brand-direct retailers (`samsung_direct`, `apple_direct`, `hp_direct`, `dell_direct`, `lenovo_direct`, `microsoft_direct`, `sony_direct`, `lg_direct`) and 52 discount_program rows from 17 templates expanded per-eligibility-type. `scripts/seed_retailers.py` flipped `amazon.supports_identity=True` (single source of truth). Prime Student seeded for Amazon; Prime Access skipped (no backing profile flag); Samsung "employees of partner companies" skipped (same reason).
   - iOS: new `IdentityProfile.swift` model (4 Sendable structs), 3 new `APIClientProtocol` methods on all 3 conformers (concrete, Mock, Preview). `Endpoints.swift` adds `getIdentityProfile`, `updateIdentityProfile(IdentityProfileRequest)`, `getEligibleDiscounts(productId:)` cases with snake_case key encoding for the POST body.
   - iOS profile flow: `ProfilePlaceholderView.swift` deleted. New `ProfileView` auto-loads via `GET /api/v1/identity/profile` and renders identity-group / membership / verification chips in a `FlowLayout` wrap-HStack, with an "Edit profile" button that re-opens the onboarding sheet pre-populated from the current profile. `IdentityOnboardingView` is enum-driven 3-step (`identityGroups` → `memberships` → `verification`) with Skip/Continue buttons; the final step calls `save()` which flips `hasCompletedIdentityOnboarding=true` and dismisses. Swipe-down dismiss does NOT set the flag, so the sheet re-presents on next launch until the user explicitly skips-through or saves. `ContentView` mounts the sheet from an `@AppStorage` `.task`.
   - iOS discounts reveal: `ScannerViewModel.identityDiscounts: [EligibleDiscount]` + private `fetchIdentityDiscounts(productId:)` fire at TWO call sites — AFTER the `for try await event in stream` loop exits successfully (line ~122 in `fetchPrices()`) AND AFTER `fallbackToBatch()` successfully returns (line ~191). Never inside the `.done` case — firing there would race the still-consuming retailer_result events. Failures are non-fatal: `sseLog.warning` + empty array; `priceError` is never set. `PriceComparisonView` gains an `identityDiscountsSection` inserted between `savingsSection` and `sectionHeader`, animated via `.easeInOut(duration: 0.3)` on `viewModel.identityDiscounts`. When the list is empty AND `hasCompletedIdentityOnboarding=false`, an `IdentityOnboardingCTARow` renders instead — tap calls a new `onRequestOnboarding` closure the ScannerView wires to its own `@State showOnboardingFromCTA` sheet.
   - Tests: +30 backend (18 `test_m5_identity.py`: profile CRUD, multi-group union, Samsung-9-row dedup, inactive exclusion, percentage savings math, $10000×10% capped at $400, fixed_amount math, no-product-id/no-prices null savings, `/discounts` + `/discounts/all` endpoints, 150ms performance gate seeded with 66 programs — median of 5 runs; 12 `test_discount_catalog_seed.py`: lint assertions on eligibility vocabulary, retailer ids, verification methods, discount types, duplicate detection, and military brand coverage regression guard). +7 iOS (4 `IdentityOnboardingViewModelTests`: save flag propagation, skip saves defaults, failure sets error, edit-flow preserves initial profile; 3 `ScannerViewModelTests`: discounts fire after done event, empty on failure does NOT set priceError, cleared on new scan).
10. **Step 2e — M5 Card Portfolio + Reward Matching COMPLETE** (2026-04-14) — completes Barkain's second pillar. Highlights:
    - Backend: `scripts/seed_card_catalog.py` seeds 30 Tier 1 cards (Chase ×7, Amex ×5, Capital One ×4, Citi ×4, Discover ×2, BofA ×3, Wells Fargo ×2, US Bank ×3) with idempotent ON CONFLICT upsert. Creates `idx_card_reward_programs_product` unique index on `(card_issuer, card_product)` since migration 0001 doesn't have one. `scripts/seed_rotating_categories.py` seeds Q2 2026 for Freedom Flex ([amazon, chase_travel, feeding_america], 5x, cap 1500) + Discover it ([restaurants, home_depot, lowes, home_improvement], 5x, cap 1500) ONLY. Cash+ / Customized Cash / Shopper Cash Rewards carry their user_selected rate in `card_reward_programs.category_bonuses` JSONB and resolve per-user via `user_category_selections`.
    - Backend service: `m5_identity/card_{schemas,service,router}.py`. `CardService` with 8 methods + in-code `_RETAILER_CATEGORY_TAGS: dict[str, frozenset[str]]` mapping 19 retailer ids (11 Phase 1 + 8 brand-direct) to category tag sets. 7 endpoints under `/api/v1/cards/*`. `get_best_cards_for_product` does four preload queries (user cards joined with programs, active rotating, active user_category_selections, prices joined with retailer names) then iterates in-memory over cards × retailers, `max()`-ing across (base_rate, rotating bonus, user-selected bonus, static JSONB category bonus). Winner preserves `is_rotating_bonus`/`is_user_selected_bonus`/`activation_required`/`activation_url`. Dollar value = `purchase_amount * rate * point_value_cents / 100`. Target <50ms; measured <150ms CI gate.
    - Pre-fix PF-1: URL verification sweep of 27 unique URLs in `scripts/seed_discount_catalog.py`. System-curl (not Python urllib) as oracle — most 403/429/503 responses are bot-detection, not dead. Only Lenovo's `/discount-programs` + `/education-store` were genuinely dead; replaced with `/us/en/d/deals/discount-programs/`, `/us/en/d/deals/military/`, `/us/en/d/deals/student/`.
    - Pre-fix PF-2: added commented `DATABASE_URL` block to `.env.example` before Demo Mode section — shape visible to new developers even though `backend/app/config.py` has a sane default.
    - iOS: new `CardReward.swift` with 6 Sendable structs — no raw JSONB on iOS (backend flattens `category_bonuses[user_selected].allowed` into a top-level `user_selected_allowed` response field). `APIClientProtocol` gains 7 methods; concrete + Mock + 3 preview clients all updated. `Endpoints.swift` adds 7 cases; `.put` + `.delete` HTTPMethod. New `requestVoid(endpoint:)` helper for 204 / `{"ok": true}` endpoints with the same error-mapping path as `request<T>()`.
    - iOS card portfolio UI: `CardSelectionViewModel` (@MainActor @Observable, loads catalog + user cards via `async let`, `filteredGroups` groups by issuer alphabetically with `displayIssuer` special-case for `us_bank` → "US Bank" and `bank_of_america` → "Bank of America", `addCard` flips `pendingCategorySelection` when the added card has a non-empty `userSelectedAllowed`). `CardSelectionView` — NavigationStack + List with search bar, "My Cards" section (swipe-delete, star-toggle for preferred) above the catalog grouped by issuer. `CategorySelectionSheet` — standalone sheet rendering the card's `allowed` list with multi-select checkmarks; Save disabled until selection non-empty.
    - iOS Profile integration: `ProfileView` gains a `cardsSection` below the identity chips — empty-state CTA card if `userCards.isEmpty`, or a FlowLayout of chips with preferred-star badge + "Manage cards" button otherwise. `.task` loads cards via `apiClient.getUserCards()`; `onDismiss` of the card sheet re-loads so chips stay fresh.
    - iOS price comparison integration: `ScannerViewModel.cardRecommendations: [CardRecommendation]` + `userHasCards: Bool`. `fetchCardRecommendations` is called from the END of `fetchIdentityDiscounts` — inheriting 2d's two-call-site pattern (post-SSE-done + post-batch-fallback) for free. Non-fatal on failure: never sets `priceError`, never resets `userHasCards` on transient errors (stale-false is a better failure mode than stale-true). `PriceRow` accepts optional `cardRecommendation: CardRecommendation?`; when non-nil renders "Use [card] for [rate]x ($[amount] back)" below the price with an "Activate" Link when `activation_required`. `PriceComparisonView` threads `viewModel.cardRecommendations.first { $0.retailerId == retailerPrice.retailerId }` into each success row; new `addCardsCTA` @ViewBuilder surfaces when `!userHasCards && recommendations.isEmpty`, wired via `onRequestAddCards` closure to a new ScannerView sheet that presents `CardSelectionView`.
    - Tests: +30 backend (22 `test_m5_cards.py`: catalog + CRUD + matching + perf gate + `_quarter_to_dates`; 8 `test_card_catalog_seed.py`: lint on 30-card count, issuer vocab, currency vocab, no-dup tuples, category_bonuses shape + user_selected-requires-allowed, all 8 Tier 1 issuers, base rates positive, points cards have cpp, rotating references valid cards, rotating non-empty, Q2 2026 dates, Cash+/Customized Cash NOT in rotating regression guard). +10 iOS (7 `CardSelectionViewModelTests`: load/filter/add/remove/preferred/categories/user-selected category sheet priming; 3 `ScannerViewModelTests`: fires-after-identity, empty-on-failure-non-fatal, cleared-on-new-scan). 252 backend tests / 53 iOS.
11. **Remaining pre-fixes (not blockers):**
    - **Redeploy EC2 containers (2b-val-L1):** run `scripts/ec2_deploy.sh` to sync `i-09ce25ed6df7a09b2` with the repo — currently hot-patched via `docker cp` for `amazon/extract.js`, `bestbuy/extract.js`, and `bestbuy/base-extract.sh`. Next stop+start without redeploy will revert. Post-deploy MD5 verification block now flags drift automatically.
12. **Phase 2 continues:** Step 2f (M11 Billing / RevenueCat) or Step 2g (M12 Affiliate Router). Deferred from Step 2e: quarterly rotating category scraping (→ Phase 3), purchase interstitial overlay (→ Phase 3), activation reminders (→ Phase 3), spend-cap tracking (needs receipts + transactions), live-backend XCUITest for scan → stream → identity → cards flow (same reason as 2c-fix / 2d — no UI test target yet).

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
> - iOS SSE consumer: use a manual byte-level `\n`/`\r\n` splitter over `URLSession.AsyncBytes`, NOT `bytes.lines`. The `.lines` accessor buffers aggressively for small SSE payloads and won't yield lines until the connection closes — events that should arrive seconds apart land all at once at stream-close, causing the SSE consumer to miss its `done` event and fall back to the batch endpoint. Rewrite path: `SSEParser.parse(bytes:)` takes any `AsyncSequence<UInt8>` so the test suite can drive it without a real URLSession (added Step 2c-fix).
> - iOS `API_BASE_URL` for simulator runs: use `http://127.0.0.1:8000`, NOT `http://localhost:8000`. `localhost` triggers IPv6 happy-eyeballs, and uvicorn binding to `0.0.0.0` is IPv4-only, so `::1` is refused and iOS has to fall back to IPv4 — ~50ms per-request penalty. Explicit IPv4 literal skips DNS + the dual-stack race entirely.
> - SSE debugging: the `com.barkain.app` subsystem, category `SSE` logger captures every raw line, every parsed/decoded event, and every fallback trigger. Run `xcrun simctl spawn <booted> log stream --level debug --predicate 'subsystem == "com.barkain.app" AND category == "SSE"' --style compact` to watch the full SSE state machine in real time.
> - Identity matching: zero-LLM, pure SQL. `DiscountProgram.eligibility_type` is a single text column (one row per eligibility), so the seed script expands each program template per-eligibility-type and the service `IdentityService.get_eligible_discounts` deduplicates by `(retailer_id, program_name)` tuple before returning. Every eligibility_type string must match the 9-string `ELIGIBILITY_TYPES` constant in `backend/modules/m5_identity/schemas.py` — the seed lint test `test_discount_catalog_seed.py` enforces this to prevent silent vocabulary drift.
> - Identity discounts fetch: fire from `ScannerViewModel.fetchIdentityDiscounts` AFTER the SSE loop exits OR AFTER `fallbackToBatch` success — NEVER inside the `.done` case. Firing in `.done` races the still-consuming retailer_result events (the loop doesn't exit on `.done`; it exits when the stream closes). Failure is non-fatal — never set `priceError` on identity discount errors.
> - Identity onboarding gate: `@AppStorage("hasCompletedIdentityOnboarding")` in `ContentView`. Swipe-down dismiss does NOT set it — only explicit "Save" or "Skip through to final step and save" path does. Re-entry via Profile → "Edit profile" uses the same onboarding view pre-populated from the current profile via `IdentityProfileRequest(from: IdentityProfile)`.
> - `is_government` column: added by migration 0003 (Step 2d). Samsung/Dell/HP/LG/Microsoft all have real government-employee discount programs; dropping the field would have cost the most lucrative discount tier.
> - Card matching: zero-LLM, pure SQL + in-memory arithmetic. `CardService._RETAILER_CATEGORY_TAGS` hardcoded map bridges rotating/static category strings to retailer ids — trivially editable, version-controlled with the matching logic. Moving to a `retailers.category_tags TEXT[]` column is a Phase 3 cleanup. `get_best_cards_for_product` does four preloads then `max()` across (base, rotating, user_selected, static) per card × retailer. Winner preserves `is_rotating_bonus` / `is_user_selected_bonus` / `activation_required` / `activation_url` for UI display.
> - Card seed catalog unique index: created by `scripts/seed_card_catalog.py` via `CREATE UNIQUE INDEX IF NOT EXISTS idx_card_reward_programs_product ON card_reward_programs (card_issuer, card_product)` at the top of the run — NOT by a migration. Migration 0001 lacks the constraint; the seed script owns it until a future migration formalizes. Idempotent + safe to re-run.
> - Cash+ / Customized Cash / Shopper Cash Rewards are NOT seeded in `rotating_categories`. Their rates live in `card_reward_programs.category_bonuses` under `{"category": "user_selected", "rate": N, "cap": M, "allowed": [...]}` and resolve per-user via `user_category_selections`. Seeding them with a placeholder default would either silently activate a rate they didn't pick (bad UX) or render an empty row that never matches (dead code). The `test_card_catalog_seed.py::test_rotating_user_selected_cards_not_seeded` regression guard enforces this.
> - Card catalog: 30 Tier 1 cards across 8 issuers — see `scripts/seed_card_catalog.py::CARDS`. `CARD_ISSUERS` and `REWARD_CURRENCIES` vocabularies live in `backend/modules/m5_identity/card_schemas.py` and are enforced by the seed lint tests.
> - iOS CardRewardProgram does NOT decode the raw `category_bonuses` JSONB. Backend `CardRewardProgramResponse` flattens `category_bonuses[user_selected].allowed` into a top-level `user_selected_allowed: list[str] | None` field. iOS `CategorySelectionSheet` reads `program.userSelectedAllowed` and the picker Just Works.
> - `userHasCards: Bool` on `CardRecommendationsResponse` drives the "Add cards" CTA in `PriceComparisonView`. No @AppStorage flag — backend is the source of truth. Stale false-negative (CTA briefly visible after adding cards, until the next scan) is a better failure mode than stale false-positive.
> - `ScannerViewModel.fetchCardRecommendations` is chained from the END of `fetchIdentityDiscounts` — NOT in parallel, NOT at a new call site. This automatically inherits 2d's two-call-site pattern (post-SSE-done AND post-batch-fallback) without duplicating the trigger logic. Non-fatal on failure, never sets `priceError`.
> - `HTTPMethod` gained `.put` and `.delete` cases in 2e. `APIClient.requestVoid(endpoint:)` handles 204 / `{"ok": true}` endpoints with the same error-mapping path as `request<T>()` but discards the body. Use for DELETE + `POST .../categories` which don't return a payload.
