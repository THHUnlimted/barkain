# CLAUDE.md — Barkain

> **Purpose:** Root orientation for AI coding agents. This file alone should let a new session understand the project, find anything, and follow conventions.
> **Last updated:** April 2026 (v4.8 — Step 2h Background Workers complete)

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
**Step 2e-val — Card Portfolio Smoke Test: PASSED ✅ (2026-04-14, 0 bugs, branch `phase-2/step-2e-val`)** — full live-backend validation of the Step 2e pillar on iPhone 17 / iOS 26.4 simulator. All 6 phases green: onboarding (Veteran), card selection UI (30-card catalog + search + Freedom Flex added without false-positive category sheet + preferred star + Profile chips), scan flow (Samsung Galaxy Buds 2 → Gemini resolve → SSE stream → identity savings section → Walmart $199.99 + "Use Chase Sapphire Reserve for 1x ($4.00 back)" inline card subtitle), dollar-math verification (199.99 × 1.0 × 2.0 / 100 = $4.00, CSR correctly beats Freedom Flex on Walmart because Walmart isn't in Freedom Flex's Q2 rotating list), empty-cards CTA (remove both → re-scan → "Add your cards" CTA appears, keyed off backend `userHasCards=false`), second-scan state reset (Sony WH-1000XM5 → product/identity/price comparison view fully refreshed, zero stale card recommendations visible). Harness driven via `cliclick` + `osascript System Events` against Simulator window (XcodeBuildMCP UI automation not enabled in this environment). 5 observations logged in `Barkain Prompts/Error_Report_Step_2e_Card_Portfolio.md` appendix (not-bugs: preferred card does not auto-promote on remove, identity savings labels vary between products with/without retailer prices). Branch is docs-only. See `Barkain Prompts/Conversation_Summary_Step_2e_Card_Portfolio.md` appendix for full tooling discoveries + scan flow breakdown.
**Step 2f — M11 Billing + Feature Gating: COMPLETE** ✅ (2026-04-14, branch `phase-2/step-2f`) — Barkain's first monetization surface. Backend: new `m11_billing` module (`schemas.py` + `service.py` + `router.py` + `__init__.py`) exposes `GET /api/v1/billing/status` (server-authoritative tier; `is_active` computed from `tier == "pro" AND (expires_at IS NULL OR expires_at > now())`, expired-pro reports free without mutating the row) and `POST /api/v1/billing/webhook` (validates `Authorization: Bearer ${REVENUECAT_WEBHOOK_SECRET}`, dispatches on RC `event.type`, idempotent via Redis SETNX `revenuecat:processed:{event.id}` 7-day TTL, busts `tier:{user_id}` cache on every state change). 7 state-changing events handled (`INITIAL_PURCHASE`/`RENEWAL`/`PRODUCT_CHANGE`/`UNCANCELLATION` → pro+expiration, `NON_RENEWING_PURCHASE` → pro+NULL lifetime, `CANCELLATION` → pro+expiration kept, `EXPIRATION` → free+NULL); unknown types acknowledged 200 to prevent retry storms. Always SETs `subscription_expires_at` from the event payload (never `+= delta`) so replays are idempotent at the math layer too. `process_webhook` UPSERTs the users row first via `INSERT ... ON CONFLICT (id) DO UPDATE` so first INITIAL_PURCHASE for an unknown user works. Tier-aware rate limiter: new `_resolve_user_tier(user_id, redis, db)` reads `tier:{user_id}` from Redis (60s TTL) → DB SELECT on miss → `"free"` default for missing rows; cache writes happen even for free results so the SSE hot path never pays a Postgres roundtrip per event. `check_rate_limit` adds `db: AsyncSession = Depends(get_db)` and computes `limit = base * settings.RATE_LIMIT_PRO_MULTIPLIER if pro else base`. Existing 252 tests stay green because `user_test_123` (no users row) still resolves to free + base limit. New config fields: `REVENUECAT_WEBHOOK_SECRET: str = ""` and `RATE_LIMIT_PRO_MULTIPLIER: int = 2`. Migration 0004 (PF-1) takes ownership of `idx_card_reward_programs_product` from the seed-script `ensure_unique_index()` helper — uses `op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ...")` so existing dev/prod DBs upgrade cleanly. The `CardRewardProgram` model now also declares the index in `__table_args__` so test DBs built via `Base.metadata.create_all` get it without alembic. iOS: RevenueCat + RevenueCatUI added via SPM (purchases-ios-spm v5.67.2, 6 surgical pbxproj edits to add the dep cleanly without Xcode UI). New `Barkain/Services/Subscription/SubscriptionService.swift` — @MainActor @Observable, wraps `Purchases.configure(withAPIKey:appUserID:)` with idempotency + free-tier fallback when API key is empty, installs a private `PurchasesDelegateAdapter: NSObject, PurchasesDelegate` (RC v5.67.2 only exposes the delegate path, no closure listener), strong-references the adapter (RC holds it weakly), routes `receivedUpdated customerInfo` to a main-actor `apply(info:)` that updates `currentTier` from the `"Barkain Pro"` entitlement. New `Barkain/Services/Subscription/FeatureGateService.swift` — pure Swift (no RC import), @MainActor @Observable, init-injected `proTierProvider: () -> Bool`, `defaults: UserDefaults`, `clock: () -> Date` (test seam bypasses RC entirely). Daily scan counter persisted to UserDefaults via `barkain.featureGate.dailyScanCount` + `barkain.featureGate.lastScanDateKey` (yyyy-MM-dd string in LOCAL timezone — PST users get fresh quota at midnight local, not midnight UTC). Static constants `freeDailyScanLimit=10`, `freeIdentityDiscountLimit=3`. `BarkainApp.swift` constructs both services at init time, calls `subscription.configure(apiKey: AppConfig.revenueCatAPIKey, appUserId: AppConfig.demoUserId)` (demo user id `"demo_user"` matches backend `BARKAIN_DEMO_MODE` → webhook lands on the right `users` row when Clerk iOS lands later we just swap the constant), then `.environment(subscriptionService).environment(featureGateService)` (SwiftUI 17+ native @Observable injection, NOT custom EnvironmentKey — that pattern stays for the Sendable `apiClient`). New `Barkain/Features/Billing/PaywallHost.swift` (thin SwiftUI wrapper around `PaywallView()` with `.onPurchaseCompleted` / `.onRestoreCompleted` callbacks that refresh `subscription` then dismiss) and `CustomerCenterHost.swift` (thin wrapper around `CustomerCenterView()`). Two new upgrade-row components: `UpgradeLockedDiscountsRow.swift` (lock + "Upgrade to see X more discounts" tap-to-paywall) and `UpgradeCardsBanner.swift` (ONE banner above the retailer list, not 11 per-row placeholders — better visual UX). `ScannerViewModel` gains `featureGate` (init-injected, optional with internal default to free-only gate to keep existing tests building) + `showPaywall: Bool`. `handleBarcodeScan` gates AFTER successful product resolve: if `featureGate.scanLimitReached`, set `showPaywall = true` and return; otherwise `featureGate.recordScan()` then `await fetchPrices()`. No quota burn on resolve failures (better UX — failed barcode reads don't count). `ScannerView` reads `@Environment(FeatureGateService.self)`, passes it into the ViewModel init in `.task`, presents `PaywallHost` via a new `paywallBinding` computed property that collapses the optional viewModel to a `Binding<Bool>`. `PriceComparisonView` gains `@Environment(FeatureGateService.self)` + `onRequestUpgrade` callback. Identity discounts now slice to `visibleIdentityDiscounts` (full list for pro, `prefix(3)` for free) with `UpgradeLockedDiscountsRow(hiddenCount:)` rendered below when truncated — `IdentityDiscountsSection` stays presentation-only. New `cardUpgradeBanner` @ViewBuilder renders ONE `UpgradeCardsBanner` above the retailer list when free user has matching `cardRecommendations` they can't see; `PriceRow` instances get `cardRecommendation: nil` for free users so the per-row inline subtitle disappears. `ProfileView` gains `@Environment(SubscriptionService.self)` + `@Environment(FeatureGateService.self)` + `@State showPaywall`. New `subscriptionSection` @ViewBuilder rendered between header card and identity chips: pro users see "Manage subscription" NavigationLink → `CustomerCenterHost`; free users see "Scans today: X / 10 — Y left" + "Upgrade to Barkain Pro" button → `showPaywall = true`. New `tierBadge` capsule. `.sheet(isPresented: $showPaywall) { PaywallHost() }` mounted at body root. Both #Preview blocks now `.environment(SubscriptionService()).environment(FeatureGateService(proTierProvider: { false }))`. New `BillingStatus.swift` model (Decodable/Equatable/Sendable, decoded via APIClient's `.convertFromSnakeCase` strategy — no explicit CodingKeys). `APIClientProtocol` gains `getBillingStatus()`; 6 conformer fanout (concrete `APIClient`, `MockAPIClient`, 4 inline preview clients in PriceComparisonView/ProfileView/CardSelectionView/IdentityOnboardingView). `Endpoints.swift` adds `case getBillingStatus → "/api/v1/billing/status"` (GET). `Config/Debug.xcconfig` and `Release.xcconfig` add `REVENUECAT_API_KEY = ...` (debug = test public key, release = empty placeholder). `Info.plist` adds `REVENUECAT_API_KEY $(REVENUECAT_API_KEY)` substitution alongside `API_BASE_URL`. `AppConfig.swift` exposes `revenueCatAPIKey` (read from Info.plist, empty fallback) and `demoUserId = "demo_user"`. `.env.example` adds new "Billing / RevenueCat (Step 2f)" section with `REVENUECAT_WEBHOOK_SECRET=` placeholder. Tests: 14 new backend (`test_m11_billing.py`: 8 webhook tests covering all 5 state-changing event types + auth + unknown + idempotency, 3 status tests including expired-pro-downgrades-in-response with DB row unchanged, 2 rate limiter tests with monkeypatched `RATE_LIMIT_GENERAL=3` proving 4th request 429s for free + 7th request 429s for pro at 6, 1 migration test querying `pg_indexes` for `idx_card_reward_programs_product` indexdef containing UNIQUE/card_issuer/card_product). 10 new iOS (`FeatureGateServiceTests.swift`: 8 tests with per-test UUID-suffixed UserDefaults suites + mutable clock closures for deterministic daily rollover; 2 in `ScannerViewModelTests.swift`: scan_limit_triggers_paywall_blocks_fetchPrices, scan_quota_consumed_only_on_successful_resolve). `ScannerViewModelTests.setUp` updated to inject a per-test FeatureGateService with isolated UserDefaults — without this, all tests share `UserDefaults.standard` and accumulated scans break unrelated tests once cumulative count hits 10/day. 252→266 backend tests, 53→63 iOS tests. See `docs/CHANGELOG.md` §Step 2f.
**Step 2h — Background Workers: COMPLETE** ✅ (2026-04-15, branch `phase-2/step-2h`) — operational backbone so data stays fresh without user traffic. Backend-only; iOS untouched. Adds four workers backed by SQS (LocalStack in dev, real AWS in prod) plus a unified `scripts/run_worker.py` CLI runner mirroring `run_watchdog.py`. New `backend/workers/queue_client.py` wraps boto3 via `asyncio.to_thread` with a `_UNSET` sentinel so tests can pass explicit `endpoint_url=None` (bypassing the `.env` LocalStack override) to run hermetic under `moto[sqs]`. Three queues: `barkain-price-ingestion`, `barkain-portal-scraping`, `barkain-discount-verification`. `backend/workers/price_ingestion.py` splits into `enqueue_stale_products` (SQL `GROUP BY products HAVING MAX(last_checked) < cutoff` — one message per stale product; zero-price products skipped) and `process_queue` (long-poll consumer reusing `PriceAggregationService.get_prices(force_refresh=True)` — same pipeline user scans take, just initiated from SQS; zero duplication of container dispatch, Redis caching, or `price_history` append logic). Malformed + missing-product messages ack+skip; service exceptions leave the message on the queue so SQS visibility timeout handles retry naturally. `backend/workers/portal_rates.py` scrapes Rakuten, TopCashBack, BeFrugal via `httpx` + `BeautifulSoup` — a **deliberate deviation** from the `SCRAPING_AGENT_ARCHITECTURE.md` Job 1 pseudocode (which prescribes agent-browser) because portal rate pages are static-enough HTML tables that a full browser render is overkill and would couple the worker to the container infrastructure. Three pure-function parsers (`parse_rakuten` anchors on stable `aria-label="Find out more at <NAME> - Rakuten coupons and Cash Back"` ignoring hash-based CSS classes; `parse_topcashback` uses the stable `.nav-bar-standard-tenancy__value` span pattern; `parse_befrugal` uses `a[href^="/store/"] + img.alt + span.txt-bold.txt-under-store`). Rakuten's `"was X%"` marker feeds `PortalRate.previous_rate_percent` which seeds/refreshes `portal_bonuses.normal_value` so the Postgres `GENERATED ALWAYS STORED is_elevated` column fires correctly on spikes; other portals rely on the first-observation seed and never refresh the baseline (conscious tradeoff — a retailer whose normal rate drifts permanently upward will wrongly show `is_elevated=True` forever; rolling-average improvement deferred to Phase 3+). `RETAILER_NAME_ALIASES` hardcoded dict covers Phase-1 retailers + curly apostrophe variants. Chase Shop Through Chase + Capital One Shopping deferred (auth-gated); they appear in the result dict with count 0 for observability. Graceful per-portal failure: 403/429/503/network errors log WARNING and skip the portal without aborting the batch. `backend/workers/discount_verification.py` hits each stale `discount_programs.verification_url` with a Chrome UA via `httpx`, checks whether the program name appears in the response body, and distinguishes "flagged but not failed" (200 response without program name → soft flag, operator review, counter NOT incremented — program renames should not auto-deactivate) from hard failures (HTTP 4xx/5xx or network error → `consecutive_failures += 1`). 3 consecutive hard failures flip `is_active=False`. `consecutive_failures` resets to 0 on any successful verification. `last_verified` updates on every run regardless of outcome so the same stale program doesn't re-appear in `get_stale_programs` within the same week. `scripts/run_worker.py` unified CLI with 5 subcommands (`price-enqueue`, `price-process`, `portal-rates`, `discount-verify`, `setup-queues`); `scripts/setup_localstack.py` is also runnable standalone. Lazy imports inside each CLI handler so `setup-queues` doesn't pay the BeautifulSoup / price service import cost. Alembic migration 0005 adds `idx_portal_bonuses_upsert` unique index on `(portal_source, retailer_id)` + `discount_programs.consecutive_failures INTEGER NOT NULL DEFAULT 0` — both mirrored in `PortalBonus.__table_args__` and `DiscountProgram.consecutive_failures` so `Base.metadata.create_all` produces the same schema on fresh test DBs. New config fields: `SQS_ENDPOINT_URL`, `SQS_REGION`, `PRICE_INGESTION_STALE_HOURS`, `DISCOUNT_VERIFICATION_STALE_DAYS`, `DISCOUNT_VERIFICATION_FAILURE_THRESHOLD` (plus `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` in `.env` but NOT `config.py` — boto3 reads them directly from the environment). New deps: `boto3>=1.34.0` + `beautifulsoup4>=4.12.0` in `requirements.txt`, `moto[sqs]>=5.0.0` in `requirements-test.txt`. Docker-compose gains a `localstack` service (image `localstack/localstack:3`, port 4566, SERVICES=sqs, healthcheck via `curl http://localhost:4566/_localstack/health` because `awslocal` isn't in the base image). Tests: 21 new backend (4 SQS-client moto-wrapped + 4 price ingestion with moto + DB fixtures + 6 portal rates against committed HTML fixtures + 7 discount verification via `respx`) in `backend/tests/workers/`. Fixtures captured from live probes on 2026-04-14: Rakuten trimmed 1.7 MB → 66 KB around 30 `aria-label` anchors, TopCashBack 168 KB (23 tiles from /category/big-box-brands/), BeFrugal trimmed 710 KB → 110 KB around Best Buy / Amazon / Home Depot. Two bug fixes caught during test run: (1) `db_session.refresh()` doesn't autoflush so re-reading a row right after a worker in-memory mutation returned the pre-mutation state — dropped all `refresh()` calls and rely on SQLAlchemy's identity map so the in-memory instance is mutated in place; (2) initial SQSClient constructor used `endpoint_url or settings.SQS_ENDPOINT_URL or None` which couldn't distinguish "explicit None override" from "use settings fallback" — replaced with `_UNSET` sentinel so tests pass `endpoint_url=None` to force default boto3 resolution (the path moto intercepts). 280→301 backend tests; iOS unchanged at 66. See `docs/CHANGELOG.md` §Step 2h.
**Step 2g — M12 Affiliate Router + In-App Browser: COMPLETE** ✅ (2026-04-14, branch `phase-2/step-2g`) — Barkain's commission path. Backend: new `m12_affiliate` module (`schemas.py` + `service.py` + `router.py` + `__init__.py`) exposes `POST /api/v1/affiliate/click`, `GET /api/v1/affiliate/stats`, and `POST /api/v1/affiliate/conversion`. `AffiliateService.build_affiliate_url` is a pure `@staticmethod` — deterministic URL tagging without DB access, trivially unit-testable. Amazon → `?tag=barkain-20` (or `&tag=...` when the URL already has query params), eBay (`ebay_new` + `ebay_used`) → `https://rover.ebay.com/rover/1/711-53200-19255-0/1?mpre=<urlencoded>&campid=5339148665&toolid=10001`, Walmart → `https://goto.walmart.com/c/<WALMART_AFFILIATE_ID>/1/4/mp?u=<urlencoded>` (placeholder while ID is empty — passthrough with `is_affiliated=false`), everyone else (Best Buy included — their affiliate application was denied) passes through untagged. `log_click` upserts the users row first (demo-mode FK safety), then inserts into `affiliate_clicks` with `affiliate_network='passthrough'` as the NOT NULL sentinel for untagged entries. `get_user_stats` groups by retailer for a simple dashboard seed. `/conversion` is a placeholder: with `AFFILIATE_WEBHOOK_SECRET` set it requires `Authorization: Bearer <secret>` and 401s on mismatch; with it empty it accepts any request and logs the body — lets the endpoint be wired in staging before affiliate networks are configured. New config fields: `AMAZON_ASSOCIATE_TAG`, `EBAY_CAMPAIGN_ID`, `WALMART_AFFILIATE_ID`, `AFFILIATE_WEBHOOK_SECRET`. `.env` + `.env.example` gain a new Step 2g section with the real values for Amazon + eBay (live) and commented placeholders for Walmart + the conversion secret. iOS: new `Barkain/Features/Shared/Models/AffiliateURL.swift` with three Sendable structs (`AffiliateClickRequest`, `AffiliateURLResponse`, `AffiliateStatsResponse`) decoded via the existing `.convertFromSnakeCase` strategy. New `Barkain/Features/Shared/Components/InAppBrowserView.swift` — `SFSafariViewController` wrapper chosen over `WKWebView` because SFSafariVC shares cookies with Safari (affiliate tracking cookies persist) and ships with its own nav bar, reader mode, and TLS padlock without a custom WebView security surface. `IdentifiableURL` wrapper lives next to it so `.sheet(item:)` can accept a `URL` payload. `Endpoints.swift` gains `.getAffiliateURL(AffiliateClickRequest)` (POST, snake_case body) and `.getAffiliateStats` (GET); `APIClientProtocol` gains the two matching methods; 6-conformer fanout (concrete `APIClient`, `MockAPIClient`, 4 inline preview stubs in PriceComparisonView/ProfileView/IdentityOnboardingView/CardSelectionView). `ScannerViewModel.resolveAffiliateURL(for retailerPrice: RetailerPrice) async -> URL?` is the testable seam — calls `apiClient.getAffiliateURL`, falls back to the original URL string on any thrown error (network, 5xx, offline), returns nil only if the retailer row has no URL. Never throws. `PriceComparisonView` adds `@State browserURL: IdentifiableURL?` + a root-level `.sheet(item:)` that presents `InAppBrowserView`. The retailer-row `Button` now fires `Task { browserURL = IdentifiableURL(url: await viewModel.resolveAffiliateURL(for: retailerPrice)) }`. `openRetailerURL(_:)` and `UIApplication.shared.open(url)` are gone from `Features/Recommendation/*`. `IdentityDiscountsSection` and `IdentityDiscountCard` are refactored to accept `onOpen: (URL) -> Void`; `IdentityDiscountCard.resolvedURL` is the new testable computed property (prefers `verificationUrl`, falls back to `url`, nil when both missing). `PriceComparisonView` passes `onOpen: { browserURL = IdentifiableURL(url: $0) }` so identity discount taps land in the **same** in-app browser sheet — but they are NOT routed through `/affiliate/click` because verification pages are not affiliate links. Tests: 14 new backend in `test_m12_affiliate.py` (9 pure URL construction tests covering Amazon with/without existing query params, empty env passthrough, eBay new + used rover encoding, Walmart set/unset, Best Buy + Home Depot passthrough; 3 click/stats endpoint tests including the passthrough sentinel path; 2 conversion webhook tests for permissive + bearer modes). 6 new iOS (3 in `ScannerViewModelTests`: `test_resolveAffiliateURL_returnsTaggedURLOnSuccess`, `..._fallsBackOnAPIError`, `..._passesCorrectArguments`; 3 in the new `IdentityDiscountCardTests.swift`: `resolvedURL_prefersVerificationURL`, `..._fallsBackToURLWhenVerificationMissing`, `..._returnsNilWhenBothMissing`). 266→280 backend tests, 60→66 iOS tests. Migration 0004 is unchanged (table already exists from migration 0001). See `docs/CHANGELOG.md` §Step 2g.
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
- M12 Affiliate backend: ✅ (`backend/modules/m12_affiliate/{schemas,service,router}.py` — 3 endpoints at `/api/v1/affiliate/*`; pure `@staticmethod build_affiliate_url` for Amazon/eBay/Walmart; passthrough for Best Buy + unaffiliated retailers; placeholder `/conversion` webhook)
- iOS in-app browser: ✅ (`Barkain/Features/Shared/Components/InAppBrowserView.swift` — `SFSafariViewController` wrapper + `IdentifiableURL` helper; retailer + identity discount taps funnel through a single `browserURL: IdentifiableURL?` sheet in `PriceComparisonView`)
- iOS affiliate tap flow: ✅ (`ScannerViewModel.resolveAffiliateURL(for:)` testable seam calls `POST /api/v1/affiliate/click`, falls back to original URL on any thrown error; retailer-row Button in `PriceComparisonView` replaces `UIApplication.shared.open` → `Task { browserURL = IdentifiableURL(url: ...) }`)
- Background workers — SQS client: ✅ (`backend/workers/queue_client.py` — async-wrapped boto3, `_UNSET` sentinel for test overrides, 3 queue name constants in `ALL_QUEUES`)
- Background workers — LocalStack: ✅ (`docker-compose.yml` `localstack` service on port 4566, SERVICES=sqs, `/_localstack/health` healthcheck)
- Background workers — price ingestion: ✅ (`backend/workers/price_ingestion.py` — `enqueue_stale_products` via SQL `HAVING MAX(last_checked) < cutoff` + `process_queue` reusing `PriceAggregationService.get_prices(force_refresh=True)`)
- Background workers — portal rate scraping: ✅ (`backend/workers/portal_rates.py` — Rakuten/TopCashBack/BeFrugal via httpx+BS4; pure-function parsers; `normal_value` baseline preservation; Chase + Capital One deferred)
- Background workers — discount verification: ✅ (`backend/workers/discount_verification.py` — weekly URL check with "flagged vs hard-failed" distinction; 3-consecutive-failure deactivation threshold)
- Background workers — CLI runner: ✅ (`scripts/run_worker.py` — argparse subcommands `setup-queues` / `price-enqueue` / `price-process` / `portal-rates` / `discount-verify`, mirrors `run_watchdog.py` pattern)
- Background workers — migration 0005: ✅ (`idx_portal_bonuses_upsert` unique index + `discount_programs.consecutive_failures INTEGER NOT NULL DEFAULT 0`)

**Test counts:** 301 backend (301 passed / 6 skipped, +21 in Step 2h under `backend/tests/workers/`: 4 SQS client moto-wrapped in `test_queue_client.py` + 4 price ingestion with moto + DB fixtures in `test_price_ingestion.py` + 6 portal rate parsers/normalize/upsert against committed HTML fixtures in `test_portal_rates.py` + 7 discount verification via `respx` in `test_discount_verification.py`), 66 iOS unit (unchanged — no iOS changes in Step 2h), 0 UI, 0 snapshot.
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
12. **Step 2f — M11 Billing + Feature Gating COMPLETE** (2026-04-14) — Barkain's first monetization surface. Highlights:
    - Backend: new `m11_billing` module exposes `GET /api/v1/billing/status` (server-authoritative tier; expired-pro reports free without DB mutation) and `POST /api/v1/billing/webhook` (validates `Authorization: Bearer ${REVENUECAT_WEBHOOK_SECRET}`, idempotent via Redis SETNX `revenuecat:processed:{event.id}` 7-day TTL). Handles INITIAL_PURCHASE / RENEWAL / NON_RENEWING_PURCHASE / PRODUCT_CHANGE / UNCANCELLATION / CANCELLATION / EXPIRATION; everything else acknowledged 200. Always SETs expiration from the event payload (never `+= delta`) → idempotent at the math layer too. Busts `tier:{user_id}` Redis cache on every state change.
    - Tier-aware rate limiter: new `_resolve_user_tier(user_id, redis, db)` in `backend/app/dependencies.py` reads `tier:{user_id}` from Redis (60s TTL) → DB SELECT on miss → "free" for missing rows. `check_rate_limit` adds `db: AsyncSession = Depends(get_db)` and computes `limit = base * settings.RATE_LIMIT_PRO_MULTIPLIER if pro else base`. Defaults to free without erroring on cache/DB failures so the rate limiter never hard-fails on infrastructure blips. Existing 252 tests stay green because `user_test_123` (no users row) resolves to free + base limit.
    - Migration 0004 (PF-1) takes ownership of `idx_card_reward_programs_product` from the seed-script `ensure_unique_index()` helper. Migration uses `op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ...")` so existing dev/prod DBs upgrade cleanly. The `CardRewardProgram` model's `__table_args__` now mirrors the index so test DBs built via `Base.metadata.create_all` get it without alembic.
    - iOS: RevenueCat + RevenueCatUI added via SPM (purchases-ios-spm v5.67.2). Six surgical pbxproj edits (PBXBuildFile, PBXFrameworksBuildPhase, packageProductDependencies, packageReferences, XCRemoteSwiftPackageReference, XCSwiftPackageProductDependency) — verified via `xcodebuild -resolvePackageDependencies` before any build. New `Barkain/Services/Subscription/SubscriptionService.swift` (@MainActor @Observable wrapper, idempotent configure with empty-key fallback to free, private NSObject `PurchasesDelegateAdapter` strong-referenced by the service since RC v5.67.2 only exposes the delegate path). New `FeatureGateService.swift` — pure-Swift gate with init-injected `proTierProvider` closure + UserDefaults + clock for testability. Free tier: 10 scans/day in LOCAL timezone, 3 identity discounts max, no card recommendations.
    - `BarkainApp.swift` constructs both services in init and wires them via SwiftUI 17+ native `.environment(observableObject)` (the `@Environment(Type.self)` reader pattern, NOT custom EnvironmentKey). `subscription.configure(apiKey: AppConfig.revenueCatAPIKey, appUserId: AppConfig.demoUserId)` — demo user id `"demo_user"` matches `BARKAIN_DEMO_MODE` so RC webhooks land on the right `users` row until Clerk iOS lands.
    - New `PaywallHost` + `CustomerCenterHost` (thin wrappers around the RC built-in views). Two new upgrade rows: `UpgradeLockedDiscountsRow` (lock + "Upgrade to see X more discounts") and `UpgradeCardsBanner` (single banner above retailer list, NOT 11 per-row placeholders).
    - `ScannerViewModel.handleBarcodeScan` gates AFTER successful product resolve: if `featureGate.scanLimitReached`, set `showPaywall = true` and return (no quota burn on resolve failures). `ScannerView` reads `@Environment(FeatureGateService.self)` and presents `PaywallHost` via a `paywallBinding` computed property.
    - `PriceComparisonView` slices identity discounts to first 3 for free users and renders `UpgradeLockedDiscountsRow(hiddenCount:)` below; passes `nil` cardRecommendation to PriceRow when free + renders ONE `UpgradeCardsBanner` above the list. New `onRequestUpgrade` callback wired from `ScannerView` → `viewModel.showPaywall = true`.
    - `ProfileView` gains a new `subscriptionSection` between header card and identity chips. Pro users see "Manage subscription" → `CustomerCenterHost`. Free users see "Scans today: X / 10 — Y left" + "Upgrade to Barkain Pro" button → showPaywall = true. New `tierBadge` capsule.
    - 14 new backend tests (`test_m11_billing.py`: 8 webhook event types + auth + idempotency, 3 status, 2 rate-limit, 1 migration index check). 10 new iOS (`FeatureGateServiceTests.swift` × 8 + 2 new `ScannerViewModelTests`). `ScannerViewModelTests.setUp` updated to inject a per-test UUID-suffixed UserDefaults suite + FeatureGateService — without this, all tests share `UserDefaults.standard` and accumulated scans break unrelated tests once cumulative count hits 10/day.
13. **Step 2g — M12 Affiliate Router + In-App Browser COMPLETE** (2026-04-14) — Barkain's commission path. Highlights:
    - Backend: new `m12_affiliate` module exposes three endpoints under `/api/v1/affiliate/*`. `AffiliateService.build_affiliate_url` is a pure `@staticmethod` — deterministic URL tagging with no DB access. Amazon → `?tag=barkain-20`, eBay → `rover.ebay.com/rover/1/...?campid=5339148665&toolid=10001`, Walmart → `goto.walmart.com/c/<id>/1/4/mp?u=<encoded>` (placeholder while `WALMART_AFFILIATE_ID` is empty — passthrough with `is_affiliated=false`). Best Buy + everything else passes through untagged (denied application or no program). Unknown retailer → passthrough.
    - `log_click` upserts the users row first (FK safety), then inserts `affiliate_clicks` with `affiliate_network='passthrough'` sentinel for untagged clicks since the column is NOT NULL. `get_user_stats` groups by retailer. `/conversion` is a permissive placeholder when `AFFILIATE_WEBHOOK_SECRET` is empty, enforces `Authorization: Bearer <secret>` when set — mirrors `m11_billing` webhook pattern.
    - New config fields: `AMAZON_ASSOCIATE_TAG`, `EBAY_CAMPAIGN_ID`, `WALMART_AFFILIATE_ID`, `AFFILIATE_WEBHOOK_SECRET`. `.env` + `.env.example` gain a Step 2g section with real `AMAZON_ASSOCIATE_TAG=barkain-20` + `EBAY_CAMPAIGN_ID=5339148665` and commented placeholders for Walmart + the webhook secret.
    - iOS: new `Barkain/Features/Shared/Models/AffiliateURL.swift` (3 Sendable structs). New `Barkain/Features/Shared/Components/InAppBrowserView.swift` — `SFSafariViewController` wrapper (chosen over `WKWebView` for cookie sharing with Safari so affiliate tracking cookies persist) + `IdentifiableURL` helper for `.sheet(item:)`. `Endpoints.swift` gains `.getAffiliateURL(AffiliateClickRequest)` (POST, snake_case body) and `.getAffiliateStats` (GET). `APIClientProtocol` + 6 conformer fanout (concrete + Mock + 4 inline preview stubs).
    - `ScannerViewModel.resolveAffiliateURL(for retailerPrice: RetailerPrice) async -> URL?` is the testable seam — calls `apiClient.getAffiliateURL`, falls back to original URL on any thrown error, returns nil only if the retailer row has no URL. Never throws. `PriceComparisonView` adds `@State browserURL: IdentifiableURL?` + root-level `.sheet(item:)` that presents `InAppBrowserView`. Retailer-row Button action fires `Task { browserURL = IdentifiableURL(url: await viewModel.resolveAffiliateURL(for: retailerPrice)) }`. `openRetailerURL(_:)` and all `UIApplication.shared.open(url)` calls are gone from `Features/Recommendation/*`.
    - `IdentityDiscountsSection` + `IdentityDiscountCard` refactored to accept `onOpen: (URL) -> Void`. `IdentityDiscountCard.resolvedURL` is a new testable computed property (prefers `verificationUrl`, falls back to `url`, nil when both missing). `PriceComparisonView` passes `onOpen: { browserURL = IdentifiableURL(url: $0) }` so identity discount taps land in the **same** in-app browser sheet — but they are NOT routed through `/affiliate/click` because verification pages are not affiliate links.
    - 14 new backend tests in `test_m12_affiliate.py` (9 pure URL construction + 3 click/stats endpoint + 2 conversion webhook). 6 new iOS (3 `ScannerViewModelTests.test_resolveAffiliateURL_*` + 3 `IdentityDiscountCardTests.test_resolvedURL_*`). 266→280 backend tests, 60→66 iOS tests.
14. **Step 2h — Background Workers COMPLETE** (2026-04-15) — operational backbone for Barkain. Highlights:
    - Backend-only; iOS untouched. Four workers + unified CLI + LocalStack SQS in docker-compose + moto for hermetic tests.
    - `backend/workers/queue_client.py` wraps boto3 via `asyncio.to_thread`. `_UNSET` sentinel in `SQSClient.__init__` lets tests pass explicit `endpoint_url=None` to bypass `.env` LocalStack override (critical for `mock_aws` compatibility). Three queues: `barkain-price-ingestion`, `barkain-portal-scraping`, `barkain-discount-verification`.
    - `backend/workers/price_ingestion.py`: `enqueue_stale_products` runs `SELECT ... GROUP BY products HAVING MAX(last_checked) < cutoff`, sends one SQS message per stale product. `process_queue` long-polls and reuses `PriceAggregationService.get_prices(force_refresh=True)` — zero duplication of dispatch, caching, or `price_history` append. Malformed bodies + missing products ack+skip; service exceptions leave the message on the queue so SQS visibility timeout handles retry naturally. `max_iterations` kwarg + `wait_seconds=0` branch is the test seam.
    - `backend/workers/portal_rates.py`: httpx+BeautifulSoup (deliberate deviation from Job 1's agent-browser pseudocode — portal rate pages are static-enough). Three pure-function parsers anchored on stable attributes: Rakuten `aria-label="Find out more at <NAME> - Rakuten coupons and Cash Back"`, TopCashBack `.nav-bar-standard-tenancy__value`, BeFrugal `a[href^="/store/"] + img.alt + span.txt-bold.txt-under-store`. Rakuten's `"was X%"` marker feeds `PortalRate.previous_rate_percent` which seeds/refreshes `normal_value` for spike detection. Other portals rely on first-observation seed. `is_elevated` is GENERATED ALWAYS STORED — never written directly. Chase + Capital One deferred (auth-gated, emit 0 counts for observability). Graceful per-portal degradation on 403/429/503/network.
    - `backend/workers/discount_verification.py`: weekly httpx GET with Chrome UA, mentions-name body check. Distinguishes "flagged_missing_mention" (soft — operator review, counter NOT incremented) from hard 4xx/5xx/network failures (counter +1). 3 consecutive hard failures → `is_active=False`. Counter resets on any success. `last_verified` updates on every run so stale programs don't re-appear within the same week.
    - `scripts/run_worker.py` argparse CLI with 5 subcommands (`price-enqueue`, `price-process`, `portal-rates`, `discount-verify`, `setup-queues`), mirrors `run_watchdog.py`. Lazy imports per handler so `setup-queues` doesn't pay BS4/service import cost.
    - Migration 0005: `idx_portal_bonuses_upsert` unique index on `(portal_source, retailer_id)` + `discount_programs.consecutive_failures INTEGER NOT NULL DEFAULT 0`. Both mirrored in the SQLAlchemy models so `Base.metadata.create_all` produces the same schema on fresh test DBs.
    - Docker-compose gains `localstack` service (image `localstack/localstack:3`, SERVICES=sqs, port 4566, healthcheck via `curl /_localstack/health` because `awslocal` isn't in the base image).
    - New config: `SQS_ENDPOINT_URL`, `SQS_REGION`, `PRICE_INGESTION_STALE_HOURS`, `DISCOUNT_VERIFICATION_STALE_DAYS`, `DISCOUNT_VERIFICATION_FAILURE_THRESHOLD`. `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` land in `.env` but NOT `config.py` (boto3 reads them directly from env).
    - New deps: `boto3` + `beautifulsoup4` in `requirements.txt`, `moto[sqs]` in `requirements-test.txt`.
    - 21 new backend tests under `backend/tests/workers/` (4 SQS-client via moto, 4 price ingestion, 6 portal rates against committed HTML fixtures captured from live probes, 7 discount verification via respx). Two bug fixes during test run: `db_session.refresh()` doesn't autoflush (removed all refresh calls; rely on SQLAlchemy identity map), `SQSClient` constructor `_UNSET` sentinel (tests must force `endpoint_url=None` to bypass the `.env` LocalStack URL for `mock_aws` compat). 280→301 backend tests, 66 iOS unchanged.
15. **Remaining pre-fixes (not blockers):**
    - **Redeploy EC2 containers (2b-val-L1):** run `scripts/ec2_deploy.sh` to sync `i-09ce25ed6df7a09b2` with the repo — currently hot-patched via `docker cp` for `amazon/extract.js`, `bestbuy/extract.js`, and `bestbuy/base-extract.sh`. Next stop+start without redeploy will revert. Post-deploy MD5 verification block now flags drift automatically.
16. **Phase 2 continues:** Step 2i (v0.2.0 hardening sweep) next — guiding-doc audit, TESTING.md updates, tag v0.2.0. Deferred from Step 2h: live smoke test against real LocalStack + real DB (one-shot manual run post-merge), DLQ wiring on the SQS queues, rolling-average `normal_value` refresh for portal rate spike detection, aioboto3 swap if throughput ever exceeds ~10k messages/hour, per-portal SQS fan-out (queues exist but workers are currently one-shot orchestrators). Deferred from Step 2g: Walmart Impact Radius affiliate approval (Mike post-merge task — fill `WALMART_AFFILIATE_ID` in `.env` once approved), real conversion webhook processing (structure in place, actual commission tracking when networks start sending callbacks), CJ Affiliate or additional networks (→ separate step). Deferred from Step 2f: RevenueCat dashboard configuration (Mike), real Clerk iOS auth (separate step), App Store / TestFlight (Phase 4).

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
> - **Step 2f** Two sources of truth, by design. iOS `SubscriptionService` reads RC SDK for UI gating (offline, instant). Backend `users.subscription_tier` is the rate-limit authority. They converge via `POST /api/v1/billing/webhook` with up to 60s of accepted drift (tier cache TTL). Alternative — every gate is a backend round-trip — breaks offline scanning. Documented in `SubscriptionService.swift` header.
> - **Step 2f** RevenueCat `app_user_id` is bound to `AppConfig.demoUserId = "demo_user"` to match `BARKAIN_DEMO_MODE` → `get_current_user`'s hardcoded return. When Clerk iOS lands (out of scope), replace the constant with the live Clerk user id and call `Purchases.shared.logIn(id)` on sign-in + `Purchases.shared.logOut()` on sign-out. Webhook events use the `app_user_id` from the event payload, so the mapping must agree on both sides.
> - **Step 2f** RevenueCat v5.67.2 only exposes `delegate: PurchasesDelegate` for customer info updates, NOT a closure listener. (Context7 surfaced an outdated `customerInfoUpdateListener` snippet — caught by `xcodebuild` not Context7.) `@Observable final class SubscriptionService` can't subclass NSObject cleanly, so a private `PurchasesDelegateAdapter: NSObject, PurchasesDelegate` adapter routes the callback through a closure that the service strong-references (RC holds the delegate weakly). Always trust `xcodebuild`, not Context7 alone.
> - **Step 2f** `FeatureGateService` is `@MainActor`. Default-value parameter expressions in Swift evaluate in the *caller's* actor context, so `init(featureGate: FeatureGateService = FeatureGateService(...))` fails to build from a nonisolated caller. Workaround in `ScannerViewModel`: parameter is `featureGate: FeatureGateService? = nil` and the init body resolves the default — `FeatureGateService(proTierProvider: { false })` then runs in the (`@MainActor`-isolated) init body context.
> - **Step 2f** Tier resolution caches in Redis with a 60s TTL: `tier:{user_id}` → `"free"` or `"pro"`. The cache write happens even for "free" results to avoid thundering-herd on the SSE hot path. `m11_billing.service.process_webhook` busts the key on every state-changing event so upgrades take effect within the cache window. Falls open to free on Redis or DB errors — the rate limiter never hard-fails an authenticated request because of an infrastructure blip.
> - **Step 2f** Webhook idempotency: SETNX dedup (`revenuecat:processed:{event.id}` with 7-day TTL) AND SET-not-delta math. Even if the dedup layer fails, the actual state mutations always SET `subscription_expires_at` from the event payload, so a replayed RENEWAL produces the same final row. Two layers of defense; replays are safe at both. Always returns 200 when auth passes — RC treats anything non-2xx as failure and infinite-retries.
> - **Step 2f** Daily scan quota stored as a `yyyy-MM-dd` STRING (not Date) in LOCAL timezone via `DateFormatter` with `.current` timezone. PST users scanning at 11:59pm PST and 12:01am PST get a fresh quota at midnight local — not midnight UTC. Acceptable bypass vectors documented (reinstall, clock manipulation, multi-device); server-side tracking deferred until abuse is observed.
> - **Step 2f** Scan quota is gated AFTER successful product resolve, NOT before. Better UX than burning quota on barcode-read failures or unknown UPCs. Counted scans = "real" scans of resolved products; free users can retry a fuzzy barcode without losing a scan. Plan agent Trap 9 codified.
> - **Step 2f** ScannerViewModelTests inject a per-test UUID-suffixed `UserDefaults(suiteName:)` into FeatureGateService. Without this, all tests share `UserDefaults.standard` → accumulate scans across the suite → eventually hit the 10/day cap → `test_reset_clearsPriceState` (and any test that runs late) silently breaks because `handleBarcodeScan` short-circuits at the gate. Caught during this step's first test run; documented for future ViewModel tests that touch UserDefaults state.
> - **Step 2f** Migration 0004 owns `idx_card_reward_programs_product` from the seed-script `ensure_unique_index()` helper. Migration uses `op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ...")` so existing dev/prod DBs (which already have the index from the seed-script lazy-create path) upgrade cleanly. The `CardRewardProgram` model's `__table_args__` mirrors the index so test DBs built via `Base.metadata.create_all` (NOT alembic) get it on fresh schemas. Two definitions kept in sync — model is the source of truth for SQLAlchemy/test, migration is the source of truth for production deployments.
> - **Step 2f** SwiftUI 17+ native environment injection (`.environment(observableObject)` + `@Environment(Type.self)`), NOT custom EnvironmentKey, for `@Observable` services. Existing `apiClient` keeps its custom EnvironmentKey because `APIClient` is a Sendable protocol that can't be observed. For @Observable classes the native pattern propagates observation correctly out of the box.
> - **Step 2f** `idx_card_reward_programs_product` is OWNED by Alembic migration 0004 (Step 2f), NOT by `scripts/seed_card_catalog.py`. The seed script's `ensure_unique_index()` helper has been removed; module docstring points at migration 0004. Supersedes the Step 2e decision that the seed script owned the constraint until a migration formalized it.
> - **Step 2g** Affiliate URL construction is **backend-only**. iOS never builds tagged URLs locally — every retailer tap round-trips through `POST /api/v1/affiliate/click`, which returns the tagged URL and logs the click in the same call. Alternative (build on-device, log separately) was rejected because it duplicates the tagging logic across platforms and loses the atomic click-log-and-tag guarantee. The iOS client treats the backend as the single source of truth for commission URLs.
> - **Step 2g** `SFSafariViewController` (not `WKWebView`) for the in-app browser. Reason: SFSafariVC shares cookies with Safari, so affiliate tracking cookies set by Amazon / eBay / Impact Radius persist even after the sheet dismisses. WKWebView uses an isolated data store, so every affiliate click would start with a clean session and commission attribution would be unreliable. Secondary benefits: built-in nav bar, reader mode, TLS padlock, no custom WebView security surface.
> - **Step 2g** Fail-open on `getAffiliateURL`. Any throw (network, 5xx, offline) → `ScannerViewModel.resolveAffiliateURL` returns the original `retailerPrice.url` wrapped in a URL so the user is never blocked from clicking through. Missing env vars (`AMAZON_ASSOCIATE_TAG=""`, etc.) → service returns `is_affiliated=false` and the original URL — no 500s. Never raise on the hot path: the commission is a nice-to-have, the click-through is not.
> - **Step 2g** `AffiliateService.build_affiliate_url` is a pure `@staticmethod` so unit tests don't need a DB fixture and URL-tagging logic is the same shape as pure functions in other languages. `build_affiliate_url("amazon", "https://...")` is fully deterministic given `settings.AMAZON_ASSOCIATE_TAG`.
> - **Step 2g** `affiliate_clicks.affiliate_network` is NOT NULL in the migration 0001 schema, so untagged clicks (Best Buy, Home Depot, etc.) log with the sentinel value `"passthrough"` — NOT an empty string, NOT NULL. The stats endpoint groups by retailer not network, so the sentinel doesn't leak into client surfaces. Adding a migration to relax the constraint was rejected: the sentinel is descriptive and the constraint is load-bearing for downstream analytics.
> - **Step 2g** Identity discount verification URLs are **NOT** routed through `/affiliate/click`. Verification pages (ID.me, SheerID, UNiDAYS, WeSalute) are not affiliate links — they exist to prove the user is eligible, not to convert. They open in the **same** in-app browser sheet as retailer taps (better UX — user stays in the app) but via a direct `IdentifiableURL` construction, not an API call. Log cost + latency savings on every discount tap.
> - **Step 2g** `IdentityDiscountsSection` + `IdentityDiscountCard` were refactored to accept `onOpen: (URL) -> Void` so the presenting view (`PriceComparisonView`) owns the sheet state. Alternative (have `IdentityDiscountCard` own its own sheet) was rejected because it would mean two sheets competing for presentation — retailer tap + identity tap — and iOS only allows one sheet at a time per presenter. Funneling both flows through a single `browserURL: IdentifiableURL?` @State on `PriceComparisonView` keeps the sheet logic coherent. `IdentityDiscountCard.resolvedURL` is now a testable computed property (prefers `verificationUrl`, falls back to `url`, nil when both missing).
> - **Step 2g** Test seam for the retailer tap flow: `ScannerViewModel.resolveAffiliateURL(for:)` is a public async method that takes a `RetailerPrice` and returns a `URL?`. `PriceComparisonView` calls it from a `Task { }` in the Button action, then sets `browserURL`. The public helper is trivially unit-testable against a `MockAPIClient`. The alternative (testing the full tap → sheet presentation path) requires a SwiftUI view testing harness (ViewInspector, etc.) which the project doesn't have.
> - **Step 2g** `AFFILIATE_WEBHOOK_SECRET` is empty by default — the `/api/v1/affiliate/conversion` endpoint runs in permissive placeholder mode (accept any request, log the payload at INFO) until the secret is set. Once the secret is set, it enforces `Authorization: Bearer <secret>` and 401s on mismatch, mirroring the `m11_billing` webhook pattern. The permissive mode lets the endpoint be wired in staging before real affiliate networks are configured; the bearer mode lets it flip to production without a code change.
> - **Step 2h** `moto[sqs]` + `mock_aws` context for SQS tests, NOT a running LocalStack container. LocalStack is perfect for integration smoke and ops, but painful in CI (start time, port conflicts, occasional flakiness on hosted runners). moto 5.x stubs boto3 at the transport layer with zero setup, so every worker test is hermetic. Live smoke against real LocalStack is still done via `docker compose up localstack` + `python3 scripts/run_worker.py setup-queues` for manual verification.
> - **Step 2h** `SQSClient` uses an `_UNSET = object()` sentinel in `__init__` so callers can pass `endpoint_url=None` to explicitly force the default boto3 credential chain. Without the sentinel, `endpoint_url or settings.SQS_ENDPOINT_URL or None` coerces `None → settings fallback`, which breaks moto-backed tests when `.env` has `SQS_ENDPOINT_URL=http://localhost:4566` — boto3 tries to hit that URL before moto can intercept. The sentinel lets tests short-circuit the settings fallback cleanly.
> - **Step 2h** boto3 wrapped with `asyncio.to_thread`, NOT aioboto3. One fewer dep, and the thread-pool hop is negligible at tens-to-hundreds of messages/hour. Documented in the `queue_client.py` module docstring so a future maintainer can swap to aioboto3 if throughput ever exceeds ~10k messages/hour. The public API (`async def send_message` / `receive_messages` / `delete_message`) is identical between the two implementations, so the migration would be a drop-in.
> - **Step 2h** Price ingestion worker reuses `PriceAggregationService.get_prices(force_refresh=True)` wholesale. No duplicated dispatch, no duplicated caching, no duplicated `price_history` append logic. The worker's only job is translating SQS messages → service calls and enforcing the SQS ack/retry contract. One code path, one test target, one place to fix bugs.
> - **Step 2h** `process_queue` relies on SQS visibility timeout for retry on service failures. When `PriceAggregationService.get_prices` raises, the worker deliberately does NOT delete the message. SQS hides it for the visibility timeout (default 30s) then re-delivers. No counter table, no DLQ yet, no backoff math. Malformed bodies (non-UUID `product_id`) and missing products (valid UUID not in `products`) are ack+skipped because retrying bad data just retries the same crash. DLQ wiring is a post-2h ops hardening task.
> - **Step 2h** Portal rate scraping via `httpx` + `BeautifulSoup`, NOT agent-browser — a **deliberate deviation** from `SCRAPING_AGENT_ARCHITECTURE.md` Job 1 pseudocode. Rationale: portal rate pages are static-enough HTML tables that a browser render is overkill, and agent-browser would couple this worker to the scraper container infrastructure (making local dev painful). Pure-function parsers are trivially unit-testable against committed HTML fixtures with no browser machinery. The deviation is flagged in both the `portal_rates.py` module docstring and in the annotated Job 1 pseudocode block in SCRAPING_AGENT_ARCHITECTURE.md so future readers don't get confused.
> - **Step 2h** Per-portal parsers anchor on stable attributes, not hash-based CSS classes. Rakuten's tiles have class names like `css-z47yg2`/`css-105ngdy`/`css-1ynb68i` which will drift on every deploy — the parser uses the stable `aria-label="Find out more at <NAME> - Rakuten coupons and Cash Back"` pattern instead. TopCashBack uses `.nav-bar-standard-tenancy__value` (semantic, stable). BeFrugal uses `a[href^="/store/"] + img.alt + span.txt-bold`. If any portal's DOM shifts materially, refresh the committed HTML fixture — do NOT edit the parser without first confirming the live page changed shape.
> - **Step 2h** `portal_bonuses.normal_value` is preserved across runs once seeded, so the Postgres GENERATED ALWAYS STORED `is_elevated` column works. Rakuten's `"was X%"` marker is extracted into `PortalRate.previous_rate_percent` and used to seed/refresh `normal_value` — because Rakuten is telling us what the "old" rate was, which is exactly the "normal" baseline we want. TopCashBack + BeFrugal don't expose a previous-rate field, so those portals rely on the first-observation seed and never refresh. Known trade-off: if a retailer's normal rate drifts permanently upward on a portal without a `"was"` marker, `is_elevated` will wrongly claim "spike" forever. Latent recommendation: rolling 30-day average via TimescaleDB continuous aggregate in Phase 3+.
> - **Step 2h** `is_elevated` is `Computed("bonus_value > COALESCE(normal_value, 0) * 1.5", persisted=True)` in the `PortalBonus` model and `GENERATED ALWAYS AS (...) STORED` in migration 0001. Never written by the worker — any INSERT/UPDATE that names the column raises a Postgres error. The upsert tests read it back to confirm the spike math end-to-end through SQLAlchemy → asyncpg → Postgres.
> - **Step 2h** Discount verification uses "flagged but not failed" as a third state beyond "verified"/"failed". A 200 response that doesn't mention the program name → `flagged_missing_mention` — logs a WARNING for operator review but does NOT increment `consecutive_failures`. Rationale: program renames (e.g. "Student Discount" → "Verified Student Pricing") should not cause auto-deactivation. Only hard 4xx/5xx/network errors count toward the 3-consecutive-failure deactivation threshold. This preserves the "3 CDN blips don't kill a valid discount" invariant while still surfacing potentially-stale programs to humans.
> - **Step 2h** `discount_programs.consecutive_failures` is a new `INTEGER NOT NULL DEFAULT 0` column added by migration 0005. Alternatives (encode counter in `notes` TEXT field as JSON; sidecar `worker_failures` table) were rejected — the dedicated column is simpler, indexable, and mirrors the pattern the Step 2f migration 0004 uses for `idx_card_reward_programs_product`. The model declares BOTH `default=0` (for freshly constructed in-memory instances) AND `server_default="0"` (for fresh `Base.metadata.create_all` schemas + alembic upgrades) so every code path agrees.
> - **Step 2h** `last_verified` updates on every discount verification run regardless of outcome (verified / flagged / failed). This prevents the same stale program from re-appearing in next-run's `get_stale_programs` query within the same week. One attempt per cadence, not a tight retry loop. A program that fails hard this week waits a full week before the next retry attempt; if it's still failing on the 3rd consecutive week, `is_active` flips to False.
> - **Step 2h** `scripts/run_worker.py` lazy-imports each handler's dependencies inside the handler function, NOT at module load. `setup-queues` doesn't pay the `PriceAggregationService` or `BeautifulSoup` import cost — only the SQS client. This matters most when the CLI is invoked from cron and you want a fast cold start for the simple commands.
> - **Step 2h** `db_session.refresh()` does NOT autoflush pending changes — discovered the hard way during discount verification test runs. Calling `refresh(program)` after the worker mutates `program.last_verified` in-memory returns the **pre-mutation** row from the DB because the UPDATE is still in SQLAlchemy's dirty queue, not yet on the wire. Fix: drop all `refresh()` calls and rely on SQLAlchemy's identity map so the test's `program` reference IS the same instance the worker mutates. Documented in the CHANGELOG §Step 2h decision #16 + the Step 2h error report as a latent footgun for future worker tests.
