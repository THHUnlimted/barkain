# CLAUDE.md — Barkain

> **Purpose:** Root orientation for AI coding agents. This file alone should let a new session understand the project, find anything, and follow conventions.
> **Last updated:** April 2026 (v5.2 — Phase 2 closed at Step 2i-d; awaiting `v0.2.0` tag from Mike)

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
├── docker-compose.yml                 ← PostgreSQL+TimescaleDB, test DB, Redis, LocalStack
├── .env.example                       ← All env vars with placeholder values
├── Barkain.xcodeproj                  # Xcode project
├── Barkain/                           # iOS source
│   ├── BarkainApp.swift               # @main entry point
│   ├── ContentView.swift              # Root TabView
│   ├── Assets.xcassets
│   ├── Features/
│   │   ├── Scanner/                   # Barcode + manual UPC entry
│   │   ├── Search/
│   │   ├── Recommendation/            # PriceComparisonView
│   │   ├── Profile/                   # Identity + card portfolio
│   │   ├── Savings/
│   │   ├── Billing/                   # Paywall + Customer Center hosts
│   │   └── Shared/                    # Components, models, utilities
│   └── Services/
│       ├── Networking/                # APIClient, SSE parser, endpoints
│       ├── Scanner/                   # BarcodeScanner (AVFoundation)
│       └── Subscription/              # SubscriptionService, FeatureGateService
├── BarkainTests/
├── BarkainUITests/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI entry point
│   │   ├── config.py                  # pydantic-settings
│   │   ├── database.py                # Async engine + session
│   │   ├── dependencies.py            # DI (db, redis, auth, rate limit, tier)
│   │   ├── errors.py
│   │   ├── middleware.py
│   │   └── models.py                  # SQLAlchemy ORM (shared)
│   ├── modules/                       # m1_product, m2_prices, m3_secondary,
│   │                                  # m4_coupons, m5_identity, m9_notify,
│   │                                  # m10_savings, m11_billing, m12_affiliate
│   │   └── m2_prices/
│   │       ├── adapters/              # walmart_firecrawl, walmart_http, etc.
│   │       ├── health_monitor.py
│   │       ├── health_router.py
│   │       └── sse.py                 # SSE wire-format helper
│   ├── ai/
│   │   ├── abstraction.py             # Gemini + Anthropic async clients
│   │   └── prompts/                   # upc_lookup.py, watchdog_heal.py
│   ├── workers/
│   │   ├── queue_client.py            # Async-wrapped boto3 SQS
│   │   ├── price_ingestion.py         # Stale-product refresh (SQS)
│   │   ├── portal_rates.py            # Rakuten/TopCashBack/BeFrugal scrape
│   │   ├── discount_verification.py   # Weekly URL check
│   │   └── watchdog.py                # Nightly health + self-heal
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── modules/
│   │   ├── workers/
│   │   ├── integration/               # BARKAIN_RUN_INTEGRATION_TESTS=1
│   │   └── fixtures/
│   │       └── portal_rates/          # rakuten.html, topcashback.html, befrugal.html
│   ├── requirements.txt
│   └── requirements-test.txt
├── containers/                        # Per-retailer scrapers
│   ├── base/                          # Shared base image
│   ├── amazon/  best_buy/  walmart/  target/  home_depot/  lowes/
│   ├── ebay_new/  ebay_used/  sams_club/  backmarket/  fb_marketplace/
│   └── template/
├── infrastructure/
│   └── migrations/                    # Alembic
├── scripts/                           # run_worker.py, run_watchdog.py, seed_*, ec2_*
├── prototype/
└── docs/
    ├── ARCHITECTURE.md
    ├── CHANGELOG.md                   ← Full per-step history + decision log
    ├── PHASES.md
    ├── FEATURES.md
    ├── COMPONENT_MAP.md
    ├── DATA_MODEL.md
    ├── DEPLOYMENT.md
    ├── TESTING.md
    ├── AUTH_SECURITY.md
    ├── CARD_REWARDS.md
    ├── IDENTITY_DISCOUNTS.md
    ├── SEARCH_STRATEGY.md
    └── SCRAPING_AGENT_ARCHITECTURE.md
```

---

## Running Locally

```bash
# 1. Start infrastructure
docker compose up -d          # PostgreSQL+TimescaleDB, Test DB, Redis, LocalStack

# 2. Backend setup
cd backend
cp ../.env.example .env       # Fill in real values
pip install -r requirements.txt -r requirements-test.txt
cd ..
alembic upgrade head          # From project root (reads alembic.ini)
python3 scripts/seed_retailers.py
python3 scripts/seed_discount_catalog.py
python3 scripts/seed_card_catalog.py
python3 scripts/seed_rotating_categories.py

# 3. Run backend
cd backend && uvicorn app.main:app --reload --port 8000

# 4. Tests (from backend/)
pytest --tb=short -q          # 301 backend tests (Docker PG port 5433, NOT SQLite)
ruff check .

# 5. iOS — open Barkain.xcodeproj or use XcodeBuildMCP

# 6. Background workers (optional — needs LocalStack)
docker compose up -d localstack
python3 scripts/run_worker.py setup-queues
python3 scripts/run_worker.py price-enqueue     # one-shot
python3 scripts/run_worker.py price-process     # long-poll worker
```

---

## Architecture

**Pattern:** MVVM (iOS) + Modular Monolith (Backend) + Containerized Scrapers

**iOS:** SwiftUI + `@Observable` ViewModels. Views → ViewModels → APIClient → Backend.

**Backend:** FastAPI (Python 3.12+). Per-module layout: `router.py`, `service.py`, `schemas.py`. Modules communicate via direct imports. All LLM calls go through `backend/ai/abstraction.py` — never import `google.genai` / `anthropic` / `openai` directly from a module.

**Scrapers:** Per-retailer Docker containers (Chromium + agent-browser CLI + extraction script + Watchdog). Walmart uses an HTTP adapter (`WALMART_ADAPTER={container,firecrawl,decodo_http}`) instead of the browser container — PerimeterX defeats headless Chromium but the `__NEXT_DATA__` JSON is server-rendered before JS runs.

**Zero-LLM matching:** Identity discounts, card rewards, rotating categories, and portal bonuses are stored in PostgreSQL and resolved via pure SQL joins at query time. Claude Sonnet is only used for the final recommendation synthesis (Phase 3+).

**Data flow:**
```
User scans barcode (iOS)
  → APIClient POST /products/resolve
    → M1 resolves product (Gemini + UPCitemdb cross-validation → PG cache)
  → APIClient GET /prices/{id}/stream (SSE)
    → M2 dispatches to 11 retailers in parallel; each event lands as it completes
    → On done: APIClient GET /identity/discounts?product_id=
    →          APIClient GET /cards/recommendations?product_id=
  → PriceComparisonView renders: price / where / which card / identity discount
  → Tap retailer → POST /affiliate/click → SFSafariViewController with tagged URL
```

**Concurrency:** Python `async`/`await` throughout. Swift structured concurrency on iOS.

---

## Conventions

### Backend (Python)
- **FastAPI** with Pydantic v2 models for all request/response schemas
- **Alembic** migrations in `infrastructure/migrations/` — backward-compatible only
- **SQLAlchemy 2.0** async ORM; `Base.metadata.create_all` is used by the test DB, so every constraint added via migration must be mirrored in the model's `__table_args__`
- Each module has: `router.py`, `service.py`, `schemas.py`
- All AI calls through `ai/abstraction.py`
- Background workers use SQS (LocalStack in dev, real AWS in prod) + standalone scripts invoked via `scripts/run_worker.py <subcommand>`. Not Celery.
- Per-retailer adapters in `m2_prices/adapters/` normalize to a common price schema
- **`session.refresh()` does NOT autoflush** — rely on the SQLAlchemy identity map for in-memory mutation assertions in tests (2h learning)
- **Three-mode optional params** (unset / override / force-None): use `_UNSET = object()` sentinel, not `or`-chains (2h learning)
- **Workers translate queue messages to existing service calls** — reuse services, don't duplicate logic (price_ingestion reuses `PriceAggregationService.get_prices(force_refresh=True)`)
- **SQS error handling:** don't ack on service failure (rely on visibility-timeout retry); ack+delete only permanently-bad data
- **BeautifulSoup** for structured HTML parsing; `re` for simple pattern extraction
- **Divergence documentation:** when a worker or service intentionally diverges from a planning doc, document it in three places — code docstring, architecture doc annotation, CHANGELOG entry (example: `workers/portal_rates.py` uses httpx+BS4 instead of the Job 1 agent-browser pseudocode)

### iOS (Swift)
- **SwiftUI** declarative views, `@Observable` ViewModels (iOS 17+)
- **No force unwraps** except in Preview providers
- `// MARK: -` sections in every file
- Extract subviews when body exceeds ~40 lines
- Services injected via `.environment(...)` (SwiftUI 17+ native for `@Observable`); `APIClient` uses a custom `EnvironmentKey` because it's a Sendable protocol
- **SPM only** — no CocoaPods
- **SSE consumer:** use a manual byte-level splitter over `URLSession.AsyncBytes`, NOT `bytes.lines` — `.lines` buffers aggressively for small payloads (2c-val-L6)
- **Simulator `API_BASE_URL`:** use `http://127.0.0.1:8000`, NOT `localhost:8000` — skips IPv6 happy-eyeballs fallback
- **SSE debugging:** `com.barkain.app`/`SSE` os_log category captures every line + parse + decode + fallback. Watch with `xcrun simctl spawn booted log stream --level debug --predicate 'subsystem == "com.barkain.app" AND category == "SSE"'`

### Git
- Branch per step: `phase-N/step-Na`
- Conventional commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`
- Tags at phase boundaries: `v0.N.0`
- Developer handles all git operations — agent never commits without an explicit request

### Classification Rule
Before implementing any feature, check `docs/FEATURES.md` for its AI/Traditional/Hybrid classification. If classified as Traditional, do NOT use LLM calls. If Hybrid, AI generates and code validates/executes.

---

## Development Methodology

This project uses a **two-tier AI workflow:**

1. **Planner (Claude Opus via claude.ai):** Architecture, prompt engineering, step reviews, deployment troubleshooting
2. **Executor (Claude Code / Sonnet or Opus):** Implementation — writes code, runs tests, follows structured prompt packages

**The loop:** Planner creates prompt package → Developer pastes step into coding agent → Agent plans, builds, tests → Developer writes error report → Planner reviews and evolves prompt → Repeat.

**Key rules:**
- Every step includes a FINAL section that mandates guiding-doc updates
- Pre-fix blocks carry known issues from prior steps into the next step's prompt
- This file must pass the "new session" test after every step
- Error reports are structured (numbered issues, not narrative)
- Prompt packages live in `prompts/` (NOT in repo)

---

## Tooling

### MCP Servers
- **Postgres MCP Pro** — schema inspection, query testing, migration validation
- **Redis MCP** — cache key inspection, TTL verification
- **Context7** — library documentation lookup
- **Clerk** — user management, JWT inspection
- **XcodeBuildMCP** — iOS build, test, clean, UI automation

### CLIs
- Day 1: `gh`, `docker`, `ruff`, `alembic`, `pytest`, `swiftlint`, `jq`, `xcodes`
- First deploy: `aws`, `railway`
- Phase 4+: `fastlane`, `vercel`

---

## Current State

**Phase 1 — Foundation: COMPLETE** (tagged `v0.1.0`, 2026-04-08)
Barcode scan → Gemini UPC resolution → 11-retailer agent-browser price comparison → iOS display. Amazon + Best Buy + Walmart validated on physical iPhone (2026-04-10).

**Phase 2 — Intelligence Layer: COMPLETE** (all steps merged, awaiting `v0.2.0` tag via Step 2i)

| Step | What | Backend tests | iOS tests | PR |
|------|------|:-:|:-:|:-:|
| 2a | Watchdog supervisor + health monitoring + shared base image | +20 | — | #3 |
| Walmart HTTP adapter (post-2a) | `WALMART_ADAPTER` routing: container / firecrawl / decodo_http | +24 | — | — |
| 2b | Demo reliability: UPCitemdb cross-validation + relevance scoring | +24 | — | #5 |
| 2b-final | Gemini `model` field + CI workflow + 35 hardening tests | +35 | — | #7 |
| 2c | SSE streaming (`/prices/{id}/stream`, progressive per-retailer reveal) | +11 | +11 | #8 |
| 2c-fix | iOS manual byte-level SSE splitter (fixed `AsyncBytes.lines` buffering) | — | +4 | #10 |
| 2d | M5 Identity Profile + 52-program discount catalog + migration 0003 | +30 | +7 | #11 |
| 2e | M5 Card Portfolio + 30-card reward matching + rotating categories | +30 | +10 | #12 |
| 2f | M11 Billing (RevenueCat SDK + feature gating + migration 0004) | +14 | +10 | #14 |
| 2g | M12 Affiliate Router (Amazon/eBay/Walmart) + in-app browser | +14 | +6 | #15 |
| 2h | Background Workers (SQS + price ingest + portal rates + discount verify) + migration 0005 | +21 | — | #16 |
| 2i-a | CLAUDE.md compaction + guiding-doc sweep | — | — | #17 |
| 2i-b | Code quality sweep: `DEMO_MODE` rename, dead branches removed, `_classify_retailer_result` extraction, migration 0006 | +1 | — | #18 |
| 2i-c | Operational validation: LocalStack workers end-to-end (caught + fixed worker model-registry FK bug), conftest schema-drift auto-recreate, CI `ruff check`, Phase 2 consolidation docs | — | — | #19 |
| 2i-d | Operational validation: EC2 redeploy (11/11 containers, MD5 clean) + PAT scrub + Watchdog live `--check-all` (caught + fixed `CONTAINERS_ROOT` path bug) + deferred retailer validation (3/4 pass) + BarkainUITests E2E smoke test (manual UPC → SSE → affiliate sheet, `tag=barkain-20` verified in DB) | — | +1 UI | (this step) |

**Test totals:** **302 backend** (302 passed / 6 skipped) + **66 iOS unit** + **2 iOS UI** = **370 tests**.
`ruff check` clean. `xcodebuild` clean.

**Migrations:** 0001 (initial schema, 21 tables) → 0002 (price_history composite PK) → 0003 (is_government) → 0004 (card catalog unique index) → 0005 (portal bonus upsert index + `discount_programs.consecutive_failures`) → 0006 (`chk_subscription_tier` CHECK on `users.subscription_tier`).

> Per-step file inventories, detailed test breakdowns, and full decision rationale: see `docs/CHANGELOG.md`.

---

## Known Issues

> Full history in `docs/CHANGELOG.md`. Only items affecting active development are listed here.

| ID | Severity | Issue | Owner |
|----|----------|-------|-------|
| SP-L1-b | HIGH | Leaked PAT `gho_UUsp9ML7…` stripped from EC2 `.git/config` in 2i-d, but **not yet revoked** in GitHub Settings → Developer settings. Anyone with the token can still read `molatunji3/barkain` | Mike (GitHub UI only) |
| 2i-d-L2 | MEDIUM | `lowes` container extract times out (>120 s); classified as `selector_drift` but root cause is hang, not missing selectors. Probably Xvfb / Chromium init issue on the specific container | Phase 3 |
| 2i-d-L3 | LOW | `ebay_new` / `fb_marketplace` / `walmart` still flagged `selector_drift` after live re-run with real Anthropic key. `ebay_used` heal_staged successfully (2399 Opus tokens → `containers/ebay_used/staging/extract.js`). Residual drift is unrelated to the path bug fix | Phase 3 |
| 2i-d-L4 | MEDIUM | Watchdog heal prompt passes `page_html=error_details` at `backend/workers/watchdog.py:251` — Opus never sees the real DOM, only the error string from the failed extract, so it cannot usefully repair selectors. Fix requires wiring a browser fetch into the heal path. Not blocking for `v0.2.0` — the `_handle_selector_drift` pipeline itself is now end-to-end verified | Phase 3 |
| 2b-val-L2 | UX | Best Buy leg ~91 s dominates total runtime; SSE masks it but `domcontentloaded` wait strategy remains a win | Phase 3 |
| v4.0-L2 | MEDIUM | Sub-variants without digits (Galaxy Buds Pro 1st gen) still pass token overlap — needs richer Gemini output | Phase 3 |
| 2h-ops | LOW | SQS queues have no DLQ wiring; per-portal fan-out deferred (workers are one-shot orchestrators today) | Phase 3 ops |

---

## What's Next

1. **Step 2i — Hardening sweep COMPLETE:**
   - **2i-a** ✅ — CLAUDE.md compaction + guiding-doc sweep (#17)
   - **2i-b** ✅ — Code quality + dead-code removal + renames + dedup extraction (#18)
   - **2i-c** ✅ — Operational validation (LocalStack workers) + conftest drift detection + CI ruff + Phase 2 consolidation (#19)
   - **2i-d** ✅ — Operational validation (EC2 redeploy 11/11 containers, MD5 clean; Watchdog `CONTAINERS_ROOT` path bug caught+fixed; BarkainUITests E2E smoke test lands; PAT scrubbed from EC2 `.git/config`) (this PR)
   - **`v0.2.0` tag** — Mike action post-merge: revoke leaked PAT `gho_UUsp9ML7…` in GitHub UI (SP-L1-b), then `git checkout main && git pull && git tag -a v0.2.0 -m "Phase 2: Intelligence Layer" && git push origin v0.2.0`. Real `ANTHROPIC_API_KEY` was populated mid-step 2i-d and heal pipeline is already verified end-to-end.
2. **Phase 3 — Recommendation Intelligence:** AI synthesis via Claude Sonnet, stacking rules, portal bonus display, coupon discovery, receipt scanning
3. **Phase 4 — Production Optimization:** Best Buy / eBay Browse / Keepa API adapters for speed, App Store submission, Sentry error tracking
4. **Phase 5 — Growth:** Push notifications (APNs), web dashboard, Android (KMP)

---

## Key Decisions Log

> Full decision log with rationale: see `docs/CHANGELOG.md`. Only load-bearing quick-refs live here.

### Phase 1

> - **Container auth:** VPC-only, no bearer tokens
> - **Walmart adapter:** `WALMART_ADAPTER` env var routes to `container` / `firecrawl` / `decodo_http`
> - **fd-3 stdout convention:** all `extract.sh` files must `exec 3>&1; exec 1>&2` and emit final JSON via `>&3`
> - **`EXTRACT_TIMEOUT=180`** (was 60) — Best Buy warmup + scroll + DOM eval needs it on `t3.xlarge`
> - **Relevance scoring:** model-number hard gate + variant-token equality + ordinal equality + brand match + 0.4 token overlap threshold
> - **UPCitemdb cross-validation:** always called alongside Gemini; brand agreement picks winner
> - **Gemini output:** `device_name` + `model` (shortest unambiguous identifier — generation markers, capacity, GPU SKUs). `model` is stored in `products.source_raw.gemini_model` and feeds M2 relevance scoring

### Phase 2

> - **SSE streaming:** `text/event-stream` with `asyncio.as_completed`; per-retailer events arrive progressively. iOS consumer uses a manual byte splitter (not `AsyncBytes.lines`) and falls back to the batch endpoint on any stream error (2c, 2c-fix)
> - **Identity discounts:** zero-LLM pure-SQL matching < 150 ms; deduped by `(retailer_id, program_name)`; fetched AFTER the SSE loop exits OR AFTER batch fallback — never inside `.done` (would race still-streaming events); failure is non-fatal (2d)
> - **Card matching priority:** rotating > user-selected > static > base rate, per card × retailer, `max()` in memory; inline subtitle on `PriceRow`. Cash+ / Customized Cash / Shopper Cash Rewards resolve per-user via `user_category_selections`, NOT seeded in `rotating_categories` (2e)
> - **Two sources of truth for billing tier, by design:** iOS `SubscriptionService` reads RC SDK for UI gating (offline, instant); backend `users.subscription_tier` is the rate-limit authority; they converge via the RC webhook with up to 60 s accepted drift. RC demo app user id `"demo_user"` matches `settings.DEMO_MODE` (renamed from `BARKAIN_DEMO_MODE` in 2i-b) (2f)
> - **Webhook idempotency:** SETNX dedup (`revenuecat:processed:{event.id}`, 7-day TTL) AND SET-not-delta math — replays produce the same final row (2f)
> - **Tier-aware rate limit:** `_resolve_user_tier(user_id, redis, db)` caches `tier:{user_id}` for 60 s; pro = base × `RATE_LIMIT_PRO_MULTIPLIER`; missing user → free (not an error); falls open to free on infra blips (2f)
> - **Migration 0004 owns `idx_card_reward_programs_product`** — previously created by the seed script; model `__table_args__` mirrors the index so fresh test DBs get it without alembic (2f)
> - **Affiliate URLs:** backend-only construction via `AffiliateService.build_affiliate_url` (pure `@staticmethod`). Amazon `?tag=barkain-20`, eBay rover `campid=5339148665`, Walmart Impact Radius placeholder. Untagged clicks log `affiliate_network='passthrough'` sentinel (2g)
> - **In-app browser:** `SFSafariViewController` (not `WKWebView`) — shares cookies with Safari so affiliate tracking persists (2g)
> - **Fail-open affiliate resolver:** `ScannerViewModel.resolveAffiliateURL` never throws; falls back to original URL on any API error; identity-discount verification URLs open in the same sheet but bypass `/affiliate/click` (they're not affiliate links) (2g)
> - **Background workers:** LocalStack SQS for dev, `moto[sqs]` for tests (hermetic, no container), boto3 wrapped in `asyncio.to_thread`. Workers reuse existing services — `process_queue` calls `PriceAggregationService.get_prices(force_refresh=True)` (2h)
> - **Portal rate scraping via `httpx` + `BeautifulSoup`** — deliberate deviation from Job 1's agent-browser pseudocode (portal pages are static-enough; avoids coupling to scraper containers). Parsers anchor on stable attributes (`aria-label`, semantic class names), NOT hash-based CSS classes. Rakuten's `"was X%"` marker refreshes `portal_bonuses.normal_value`; other portals rely on first-observation seed (2h)
> - **`is_elevated` is `GENERATED ALWAYS STORED`** — never written by the worker; reading it after upsert confirms the spike math end-to-end (2h)
> - **Discount verification:** three-state outcome — `verified` / `flagged_missing_mention` (soft, counter NOT incremented — program renames shouldn't auto-deactivate) / `hard_failed` (4xx/5xx/network → `consecutive_failures += 1`). 3 consecutive hard failures flip `is_active=False`. `last_verified` updates on every run regardless of outcome (2h)
> - **`SQSClient` uses an `_UNSET` sentinel** so tests can pass explicit `endpoint_url=None` to bypass the `.env` LocalStack override — `or`-chains collapse `None → settings fallback` and break moto (2h)
> - **`DEMO_MODE` is read at call-time, not import-time:** `settings.DEMO_MODE` lives on the pydantic-settings `Settings` instance and is resolved inside `get_current_user` per-request, so tests can `monkeypatch.setattr(settings, 'DEMO_MODE', True)` without import-ordering games. The previous `_DEMO_MODE = os.getenv("BARKAIN_DEMO_MODE") == "1"` module constant cached the value and broke testability (2i-b)
> - **`_classify_retailer_result` is the single classification authority** for both `get_prices()` and `stream_prices()` — extracted in 2i-b to delete ~80 duplicated lines that had already drifted (the stream version embedded `retailer_name` in the price payload directly while the batch version added it in a later loop). The two methods still differ in iteration strategy (`as_completed` vs serial dict iteration) and emission semantics (yields events vs accumulates a dict), which is why they're not merged (2i-b)
> - **`device_name` rename to `product_name` deferred:** 26 backend occurrences across 9 files including the load-bearing Gemini system instruction in `backend/ai/prompts/upc_lookup.py`. A mechanical rename would require a coordinated prompt + service-parse + test-assertion update and risks breaking the LLM contract during a hardening step. iOS already uses `name` so there's no consumer pressure. Tracked in Phase 3 if still desired (2i-b)
> - **Migration 0006 — `chk_subscription_tier` CHECK constraint** on `users.subscription_tier IN ('free', 'pro')`. Mirrored on `User.__table_args__` in `app/core_models.py` so `Base.metadata.create_all` (test DB) matches alembic. Idempotent via `DO $$ ... END $$` block keyed on `pg_constraint.conname` (2i-b)
> - **Worker scripts MUST import `from app import models`** so cross-module FKs resolve at flush time. Latent FK bug discovered by 2i-c Group A's first real LocalStack run: `run_worker.py` imported `AsyncSessionLocal` but never the central model registry, so `Base.metadata` didn't know about `Retailer` when `PortalBonus.retailer_id` tried to flush. The 2h moto test suite passed because every fixture imports models explicitly — only the standalone CLI path exposed it. Same one-line fix applied preemptively to `run_watchdog.py` (2i-c)
> - **Test DB schema drift is auto-detected** in `backend/tests/conftest.py:_ensure_schema` via a `chk_subscription_tier` marker probe before `Base.metadata.create_all`. Missing → drop+recreate the public schema. Update the marker query whenever a new migration adds a column or constraint (2i-c)
> - **Watchdog `CONTAINERS_ROOT` must use `parents[2]` not `parents[1]`** — `backend/workers/watchdog.py` previously resolved to `backend/containers/` (nonexistent), so every `selector_drift` heal failed with "extract.js not found" before reaching Opus. The 2h unit tests stubbed the filesystem layer and passed; only the 2i-d live `--check-all` against real containers exposed the gap. Symmetry with 2i-c: both bugs were latent path/registry assumptions that unit tests mocked away, caught by operational validation on first real run (2i-d)
> - **XCUITest target is now wired** — `BarkainUITests/BarkainUITests.swift` runs `testManualUPCEntryToAffiliateSheet` end-to-end: enters UPC `194252818381`, waits for an SSE-streamed retailer row via `retailerRow_<id>` accessibility IDs, taps it, and asserts the affiliate sheet presents. The final assertion uses an OR of three independent signals (SFSafari webview visible, "Done" button present, or original row no longer hittable) because iOS 26's SFSafariViewController chrome lives in a separate accessibility tree that XCUITest cannot traverse from the host app. Authoritative proof of the affiliate path is the `affiliate_clicks` DB row — we queried it post-run and confirmed `tag=barkain-20` appended and `affiliate_network='amazon_associates'` (2i-d)
> - **Deploy via rsync when GitHub auth is broken** — 2i-d Group A discovered the EC2 `.git/config` embeds a leaked PAT and deploy keys are disabled on the `THHUnlimted/barkain` repo. Fix without touching GitHub settings: `rsync -az --delete --exclude='.git/'` the local checkout to `ubuntu@ec2:~/barkain/`, then run the Phase C/D portions of `scripts/ec2_deploy.sh` inline (skip `git pull` — the rsync already synced). MD5 check still validates the container extract.js against the rsync'd host copy, so `2b-val-L1` is verifiable without a working `git pull` (2i-d)
