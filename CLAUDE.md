# CLAUDE.md — Barkain

> **Purpose:** Root orientation for AI coding agents. This file alone should let a new session understand the project, find anything, and follow conventions.
> **Last updated:** 2026-04-22 (v5.14 — fb-marketplace-location: `LocationPickerSheet` + per-city `/stream` params + `:loc:…` cache bucket)

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
│   ├── amazon/  best_buy/  walmart/  target/  home_depot/
│   ├── ebay_new/  ebay_used/  backmarket/  fb_marketplace/
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

**Scrapers:** Per-retailer Docker containers (Chromium + agent-browser CLI + extraction script + Watchdog). Walmart uses an HTTP adapter (`WALMART_ADAPTER={decodo_http (default),firecrawl,container}`) instead of the browser container — PerimeterX defeats headless Chromium but the `__NEXT_DATA__` JSON is server-rendered before JS runs. Firecrawl is currently non-functional (100% CHALLENGE response) as of 2026-04-17; kept selectable for future recovery.

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
- **Hiding a `.searchable` nav bar:** `.searchable(isPresented:)` with `.navigationBarDrawer(.always)` only toggles focus, **not** visibility. To actually remove the bar, apply `.toolbar(.hidden, for: .navigationBar)` on the root view (SearchView hides its whole nav chrome — title + drawer — during price streaming, then restores on pull-down / stream close) (ui-refresh-v1)

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
Barcode scan → Gemini UPC resolution → 9-retailer price comparison (was 11; lowes + sams_club scrapers retired 2026-04-18) → iOS display. Amazon + Best Buy + Walmart validated on physical iPhone (2026-04-10).

**Phase 2 — Intelligence Layer: COMPLETE** (tagged `v0.2.0`, 2026-04-16). 2a–2i shipped across PRs #3–#21: Watchdog supervisor, Walmart HTTP adapter, UPCitemdb cross-val, SSE streaming + iOS byte splitter, M5 Identity + 52-program catalog, Card portfolio + 30 cards, M11 Billing (RC + webhook), M12 Affiliate router, Background workers (SQS), code-quality sweep (`_classify_retailer_result` extraction, migrations 0004–0006), EC2 redeploy + UITests smoke. Full per-step breakdown in `docs/CHANGELOG.md`.

**Phase 3 — Recommendation Intelligence: IN PROGRESS**

| Step | What | Backend tests | iOS tests | PR |
|------|------|:-:|:-:|:-:|
| 3a | M1 Product Text Search: `POST /products/search` + pg_trgm + Gemini fallback + SearchView | +10 | +6 unit/+1 UI | #22, #23 |
| 3b | eBay Browse API adapter (replaces `ebay_new`/`ebay_used` containers, sub-second) + GDPR deletion webhook + FastAPI deploy on scraper EC2 (Caddy+LE) | +13 | — | #24 |
| demo-prep | Walmart `decodo_http` default + CHALLENGE retry + SP-decodo-scoping (fb_marketplace bandwidth fix) + scraper timing trim + SP-samsclub-decodo + Best Buy Products API adapter | +113 | — | #25–#30 |
| post-demo-prep | Walmart bare-host fix + lowes/sams_club retired + Decodo Scraper API adapter for Amazon (~3 s vs ~53 s) | +14 | — | #31 |
| 3c | M1 Search v2: 3-tier cascade (DB → [BBY+UPCitemdb parallel] → Gemini), brand-only routing, `force_gemini` deep-search, variant collapse, price-stream `?query=` override, eBay affiliate fix (rover pixel → EPN params) | +14 | +5 | #32 |
| 3c-hardening | Amazon platform-suffix + service/repair filter; Walmart 5× CHALLENGE retry; BBY 429/5xx retry + `_sanitize_query`; Redis device→UPC 24h + scoped query cache 30 min; iOS sheet-anchoring fix | +26 | — | #32 |
| 3d | Autocomplete: `actor AutocompleteService` (sorted-array binary search) + `.searchable` + `RecentSearches` + `scripts/generate_autocomplete_vocab.py` (4,448 terms / 128 KB). Removed 300 ms auto-debounce; submit-driven | +23 | +34 / +1 UI | #34 |
| 3d-noise-filter | `_is_tier2_noise` category+title denylist → Gemini escalation when Tier 2 is accessories-only. Extended in ui-refresh-v2-fix with brand+model relevance | +4 | — | #36 |
| ui-refresh-v1 | HTML-style-guide design pass: warm-gold palette, rounded system fonts, shadow/shimmer helpers. Glowing-paw `SniffingHeroSection` during price loading. Retailer rows stream in live with spring price-sort (Best Barkain tracks current cheapest). Nav bar hides during streaming | — | — | #37 |
| ui-refresh-v2 | Whole-app makeover: new Home tab (hero + quick-actions + "Recently sniffed" rail backed by `RecentlyScannedStore`). Scanner overlay redesign. Profile → "The Kennel" with real `/affiliate/stats` gradient card. Savings "coming soon" hero. Onboarding gradient stepper. Shared `UITabBarAppearance` blur | — | — | #38 |
| ui-refresh-v2-fix | SearchView mid-stream dismissal (`.searchable` setter fires `""` on nav-bar hide — guarded) + Tier 2 off-brand fuzzy match noise (`_is_tier2_noise` strict-majority + model-code verbatim gate) | +4 | — | #39, #40 |
| 3e | M6 Recommendation Engine (deterministic, no LLM). `POST /api/v1/recommend` stacks identity + card + portal via `asyncio.gather`, p95 < 150 ms. Brand-direct callout ≥15 % `*_direct`. iOS hero gated on 3 settle flags; silent fallback on failure. `scripts/seed_portal_bonuses_demo.py` (3g replaces). M6 reclassified AI → T | +14 | +8 / +1 UI | #41 |
| 3f (+hotfix) | Purchase Interstitial + Activation Reminder. `PurchaseInterstitialSheet` from hero CTA + row taps. `POST /affiliate/click` gains `activation_skipped` (migration 0008). Pre-fixes: `BarePreviewAPIClient` + `_db_url.py` + `without_demo_mode`. Hotfix: per-retailer `estimated_savings` w/ highest-scraped fallback; migration 0009 adds `discount_programs.scope`; Prime Student → `membership_fee` | +7 | +9 | #42 |
| Benefits Expansion (+follow-ups) | +10 student-tech + Prime YA (`scope='membership_fee'`), +4 `*_direct`, `is_young_adult` axis (0010). 52→63 programs / 8→12 retailers / 9→10 eligibility types. Follow-ups: `program_type='membership'` retired; `_dedup_best_per_retailer_scope` + `BRAND_ALIASES` name-gate (ThinkPad hides Asus/Razer); iOS `scopeBadge` + price `lineLimit` + pills `VStack`; `/resolve` → `/resolve-from-search` on Gemini UPC hallucination | +10 | +7 | #45, #46 |
| fb-marketplace-location | iOS `LocationPickerSheet` (CoreLocationUI + CLGeocoder→slug + 5/10/25/50/100 mi). `/stream?fb_location_slug&fb_radius_miles` → fb_marketplace container only; cache key `:loc:<slug>:r<radius>` + DB-fresh skipped when location set so cross-city users can't collide | +9 | +14 | TBD |

**Test totals:** 529 backend + 138 iOS unit + 6 iOS UI. `ruff check` clean. `xcodebuild` clean.

**Migrations:** 0001 (initial, 21 tables) → 0002 (price_history composite PK) → 0003 (is_government) → 0004 (card catalog unique index) → 0005 (portal bonus upsert + failure counter) → 0006 (`chk_subscription_tier` CHECK) → 0007 (pg_trgm + trgm GIN idx) → 0008 (`affiliate_clicks.metadata` JSONB) → 0009 (`discount_programs.scope` — product / membership_fee / shipping) → 0010 (`is_young_adult` on `user_discount_profiles`). Drift marker in `tests/conftest.py::_ensure_schema` now checks `user_discount_profiles.is_young_adult`.

> Per-step file inventories, detailed test breakdowns, and full decision rationale: see `docs/CHANGELOG.md`.

---

## Known Issues

> Full history in `docs/CHANGELOG.md`. Only items affecting active development are listed here.

| ID | Severity | Issue | Owner |
|----|----------|-------|-------|
| SP-L1-b | HIGH | Leaked PAT `gho_UUsp9ML7…` stripped from EC2 `.git/config` (2i-d) but **not yet revoked** in GitHub UI | Mike |
| 2i-d-L3 | LOW | `ebay_new` / `walmart` still flagged `selector_drift` after 2i-d live re-run; `ebay_used` heal_staged OK | Phase 3 |
| 2i-d-L4 | MEDIUM | Watchdog heal at `workers/watchdog.py:251` passes `page_html=error_details` — Opus sees error string, not real DOM. Needs browser fetch in heal path | Phase 3 |
| v4.0-L2 | MEDIUM | Sub-variants without digits (Galaxy Buds Pro 1st gen) still pass token overlap — needs richer Gemini output | Phase 3 |
| 2h-ops | LOW | SQS queues have no DLQ wiring; per-portal fan-out deferred | Phase 3 ops |

---

## What's Next

1. **Phase 2 CLOSED** — `v0.2.0` tagged (2026-04-16). Outstanding: revoke leaked PAT `gho_UUsp9ML7…` in GitHub UI (SP-L1-b, Mike).
2. **Phase 3:** 3a–3d + 3d-noise-filter ✅ (#32–#36), ui-refresh-v1/v2/v2-fix ✅ (#37–#40), 3e (#41), 3f (#42), Benefits Expansion (#45–#47), fb-marketplace-location ✅. Next: 3g portal live scrape, 3h Claude Vision, 3i receipts, 3k savings, 3l coupons, 3m hardening + `v0.3.0`. 3j folded into 3e. See `docs/CHANGELOG.md` + `docs/PHASES.md`.
3. **Phase 4 — Production Optimization:** ~~Best Buy~~ (done via demo-prep bundle, PR #30), Keepa API adapter, App Store submission, Sentry error tracking
4. **Phase 5 — Growth:** Push notifications (APNs), web dashboard, Android (KMP)

---

## Production Infra (EC2)

Single-host: all scraper containers + FastAPI backend (eBay webhook + Browse/Best Buy/Decodo Scraper API adapters) run on one `t3.xlarge` (`us-east-1`). Left running between sessions — don't auto-stop unless Mike says.

- **SSH:** `ssh -i ~/.ssh/barkain-scrapers.pem ubuntu@54.197.27.219`
- **Instance:** `i-09ce25ed6df7a09b2`, SG `sg-0235e0aafe9fa446e` (8081–8091 + 80/443)
- **Public webhook:** `https://ebay-webhook.barkain.app` (Caddy + Let's Encrypt)
- **Ports:** `amazon:8081 bestbuy:8082 walmart:8083 target:8084 homedepot:8085 ebaynew:8087 ebayused:8088 backmarket:8090 fbmarketplace:8091` (8086 lowes + 8089 sams_club retired 2026-04-18). Backend uvicorn on `127.0.0.1:8000` behind Caddy `:443`.
- **Env file:** `/etc/barkain-api.env` (mode 600) — eBay creds; no PG/Redis on this host.

**Health sweep:**
```bash
ssh -i ~/.ssh/barkain-scrapers.pem ubuntu@54.197.27.219 'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"'
ssh -i ~/.ssh/barkain-scrapers.pem ubuntu@54.197.27.219 'systemctl is-active barkain-api caddy && sudo journalctl -u barkain-api -n 20 --no-pager'
curl -s "https://ebay-webhook.barkain.app/api/v1/webhooks/ebay/account-deletion?challenge_code=test" | jq .
```

**Redeploy backend:**
```bash
rsync -az --delete --exclude='.git/' --exclude='__pycache__/' --exclude='tests/' --exclude='.venv/' \
  -e "ssh -i ~/.ssh/barkain-scrapers.pem" backend/ ubuntu@54.197.27.219:/home/ubuntu/barkain-api/
ssh -i ~/.ssh/barkain-scrapers.pem ubuntu@54.197.27.219 'sudo systemctl restart barkain-api'
```

**Redeploy scrapers:** `scripts/ec2_deploy.sh` (or rsync to `/home/ubuntu/barkain/` + `docker compose up -d --build <name>`).

**Retailer health (2026-04-18 bench):** `target/homedepot/backmarket` 3/3 via container; `fbmarketplace` 3/3 via Decodo (~30 s, ~17 KB); `walmart` via `walmart_http` decodo_http (~3.3 s); `amazon` via `amazon_scraper_api` (~3.2 s, when `DECODO_SCRAPER_API_AUTH` set); `bestbuy` via `best_buy_api` (~82 ms, when `BESTBUY_API_KEY` set); `ebaynew/ebayused` via `ebay_browse_api` (~500 ms, when `EBAY_APP_ID/CERT_ID` set).

**Cost-stop:** `aws ec2 stop-instances --instance-ids i-09ce25ed6df7a09b2 --region us-east-1` (static IP `54.197.27.219` survives stop/start).

---

## Key Decisions Log

> Quick-ref index only. Full rationale + code pointers live in `docs/CHANGELOG.md` (Key Decisions Log + per-step entries).

### Phase 1
- Container auth VPC-only; `WALMART_ADAPTER={container,firecrawl,decodo_http}`; fd-3 stdout convention (`exec 3>&1; exec 1>&2` + emit JSON via `>&3`); `EXTRACT_TIMEOUT=180`
- Relevance: model-number hard gate + variant-token + ordinal + brand match + 0.4 token overlap; UPCitemdb cross-val runs alongside Gemini, brand agreement picks winner; Gemini emits `device_name` + `model` (shortest unambiguous)

### Phase 2 (see CHANGELOG 2a–2i-d for full rationale)
- SSE: `asyncio.as_completed`; iOS manual byte splitter; fall back to batch on error (2c/2c-fix)
- Identity discounts: zero-LLM SQL join < 150 ms, post-SSE, non-fatal (2d). Card priority: rotating > user-selected > static > base (2e)
- Billing two sources: iOS RC SDK for UI, backend `users.subscription_tier` for rate limit, ≤60 s drift. Webhook idempotency via SETNX 7d. Tier cache `tier:{user_id}` 60 s, fail-open (2f)
- Migrations 0004/0006 mirrored on `__table_args__` so test `create_all` matches alembic (2f/2i-b)
- Affiliate: backend-built URLs + `SFSafariViewController`; fail-open (2g). Workers: LocalStack SQS dev / `moto[sqs]` tests; boto3 via `asyncio.to_thread`; `_UNSET` sentinel (2h)
- Portal rates: `httpx`+BS4, anchor on `aria-label`/semantic classes; `is_elevated` is `GENERATED ALWAYS STORED`. Discount verify 3-state: `verified`/`flagged_missing_mention`/`hard_failed` 3-strikes
- `_classify_retailer_result` = single classification authority for batch + stream (2i-b). Worker CLI scripts MUST `from app import models` for cross-module FK flush (2i-c)
- Test DB drift auto-detected in `conftest.py:_ensure_schema` via marker probe; update each migration (2i-c/3a)
- Watchdog `CONTAINERS_ROOT = parents[2]` — unit mocks hid the bug. XCUITest affiliate-sheet uses OR-of-3 signals (iOS 26 SFSafari chrome outside host a11y tree). Deploy via `rsync` + inline Phase C/D when GitHub auth broken (2i-d)
- fb_marketplace + sams_club need Decodo residential with scoped routing (kill-flags + `--proxy-bypass-list`). See `docs/SCRAPING_AGENT_ARCHITECTURE.md` §C.11

### Phase 3 (see CHANGELOG 3a–3e for full rationale)
- eBay Browse API auto-prefers on `EBAY_APP_ID`+`EBAY_CERT_ID`; 2 hr TTL; filter DSL uses `|` not `,`. GDPR deletion webhook = GET SHA-256 + POST log-and-204. Backend co-deployed on scraper EC2 via Caddy + systemd (3b)
- Best Buy API (`BESTBUY_API_KEY`, ~150 ms); Decodo Scraper API for Amazon (`DECODO_SCRAPER_API_AUTH`, ~3 s); listings at `content.results.results.organic[]`. Decodo: `proxy_relay.py` reads HOST+PORT separately; `walmart_http` appends `:7000` when bare
- lowes + sams_club scrapers retired 2026-04-18, rows kept `is_active=False` for FK. 9 active scraped retailers; `*_direct` stay `is_active=True` as identity-redirect targets
- Search v2 cascade: normalize → Redis → DB pg_trgm@0.3 → Tier 2 `gather(BBY, UPCitemdb)` → Tier 3 Gemini only when Tier 2 irrelevant OR `force_gemini`. Merge DB>BBY>UPCitemdb>Gemini → `_collapse_variants` (2+ variants → synthetic generic row) (3c). `query` override on `/prices/{id}/stream` swaps both retailer query AND per-container `product_name` hint (3c). eBay affiliate = modern EPN params on item URL; `rover.ebay.com` legacy = 42-byte pixel (3c)
- 3c-hardening: platform-suffix / CHALLENGE / 429-5xx retries + Redis cache layering + iOS `browserURL @Binding` anchoring. 3d-noise-filter: `_is_tier2_noise` with strict-majority + model-code verbatim gate. ui-refresh-v2 fix: `.searchable` setter fires `""` on nav-bar hide; guard dismisses only on non-empty changed queries
- **3e M6 Recommendation — deterministic.** Zero LLM. `POST /api/v1/recommend` `gather`s Prices+Identity+Cards+Portals, pure Python (<150 ms p95). `final = base − identity`; card + portal deferred rebates on post-identity price. Tie-break: `effective_cost`, condition, well-known retailer. Brand-direct callout ≥15 %. Excludes inactive/drift. 15 min cache. iOS hero gated on `streamClosed`+`identityLoaded`+`cardsLoaded`; fail → silent nil
- **3f Purchase Interstitial + hotfix.** Reuses 3e rec + cards. `PurchaseInterstitialSheet` from hero CTA + row taps. Activation ack session-scoped. `POST /affiliate/click` gains `activation_skipped` (0008). Baseline 1%. Alternatives rail `scrollTo` + pulse. Pre-fixes: `BarePreviewAPIClient`, `_db_url.py`, `without_demo_mode`. Hotfix: per-retailer `estimated_savings` w/ highest-scraped fallback; migration 0009 `discount_programs.scope` ∈ `{product, membership_fee, shipping}` skips savings when ≠ product. M6 cache `:v4`
- **Benefits Expansion (+follow-ups).** +10 student-tech + Prime YA (`scope='membership_fee'`); +4 `*_direct`; `is_young_adult` (0010). Follow-ups: Prime Student → `identity`; `_dedup_best_per_retailer_scope` key=(retailer_id, scope), rank -savings/-discount_value/name — different scopes survive; `BRAND_ALIASES` widens brand-gate over `product.brand + name`, fails closed on competing brand (ThinkPad→lenovo, ROG→asus, Galaxy→samsung); iOS `scopeBadge` + scope-aware `savingsText`; `PriceRow` price `lineLimit(1)` + `minimumScaleFactor(0.7)` + `layoutPriority(1)`; identity pills `VStack`/`fixedSize`; `resolveTappedResult` falls `/resolve` → `/resolve-from-search` on 404 (Gemini hallucinated UPC)
