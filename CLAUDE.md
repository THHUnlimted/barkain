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
| 2i-d | EC2 redeploy (11/11 containers, MD5 clean) + PAT scrub + Watchdog live `--check-all` (`CONTAINERS_ROOT` fix) + BarkainUITests E2E smoke | — | +1 UI | #20, #21 |

**Phase 3 — Recommendation Intelligence: IN PROGRESS**

| Step | What | Backend tests | iOS tests | PR |
|------|------|:-:|:-:|:-:|
| 3a | M1 Product Text Search: `POST /products/search` + pg_trgm + Gemini fallback + SearchView (base + sim-testing follow-ups) | +10 | +6 unit/+1 UI | #22, #23 |
| 3b | eBay Marketplace Deletion webhook (GDPR) + Browse API adapter replacing `ebay_new`/`ebay_used` scrapers (sub-second, +API) + FastAPI deploy on scraper EC2 (Caddy+LE) | +13 | — | #24 |

**Test totals:** **335 + 29 backend** (SP-decodo-scoping hotfix adds 26 shell-flag guards in `test_fb_marketplace_extract_flags.py` + 2 Firecrawl payload guards + 1 walmart_http single-request guard; re-sum after your next full run) + **72 iOS unit** + **3 iOS UI**.
`ruff check` clean. `xcodebuild` clean.

**Migrations:** 0001 (initial, 21 tables) → 0002 (price_history composite PK) → 0003 (is_government) → 0004 (card catalog unique index) → 0005 (portal bonus upsert + failure counter) → 0006 (`chk_subscription_tier` CHECK) → 0007 (pg_trgm extension + `idx_products_name_trgm` GIN index).

> Per-step file inventories, detailed test breakdowns, and full decision rationale: see `docs/CHANGELOG.md`.

---

## Known Issues

> Full history in `docs/CHANGELOG.md`. Only items affecting active development are listed here.

| ID | Severity | Issue | Owner |
|----|----------|-------|-------|
| SP-L1-b | HIGH | Leaked PAT `gho_UUsp9ML7…` stripped from EC2 `.git/config` in 2i-d, but **not yet revoked** in GitHub Settings → Developer settings. Anyone with the token can still read `molatunji3/barkain` | Mike (GitHub UI only) |
| 2i-d-L2 | MEDIUM | `lowes` container extract times out (>120 s); classified as `selector_drift` but root cause is hang, not missing selectors. Probably Xvfb / Chromium init issue on the specific container | Phase 3 |
| 2i-d-L3 | LOW | `ebay_new` / `walmart` still flagged `selector_drift` after live re-run with real Anthropic key. `ebay_used` heal_staged successfully (2399 Opus tokens → `containers/ebay_used/staging/extract.js`). `fb_marketplace` fixed via Decodo proxy (see below) | Phase 3 |
| 2i-d-L4 | MEDIUM | Watchdog heal prompt passes `page_html=error_details` at `backend/workers/watchdog.py:251` — Opus never sees the real DOM, only the error string from the failed extract, so it cannot usefully repair selectors. Fix requires wiring a browser fetch into the heal path. Not blocking for `v0.2.0` — the `_handle_selector_drift` pipeline itself is now end-to-end verified | Phase 3 |
| 2b-val-L2 | UX | Best Buy leg ~91 s dominates total runtime; SSE masks it but `domcontentloaded` wait strategy remains a win | Phase 3 |
| v4.0-L2 | MEDIUM | Sub-variants without digits (Galaxy Buds Pro 1st gen) still pass token overlap — needs richer Gemini output | Phase 3 |
| 2h-ops | LOW | SQS queues have no DLQ wiring; per-portal fan-out deferred (workers are one-shot orchestrators today) | Phase 3 ops |
| SP-decodo-scoping | RESOLVED | `fb_marketplace` Chromium routed ALL egress through Decodo — observed ~85 MB/billing-window leak, only 1.53 MB actually walmart.com (see CHANGELOG). Fix: Chromium telemetry kill flags + `--proxy-bypass-list` for google/telemetry domains + default image-blocking in `containers/fb_marketplace/extract.sh`; regression guards in `test_fb_marketplace_extract_flags.py`, `test_firecrawl_payload_has_no_decodo_overlay`, and `test_fetch_walmart_makes_exactly_one_request_per_call`. See docs/SCRAPING_AGENT_ARCHITECTURE.md §C.11 | Mike (post-deploy Decodo-dashboard verify + rotate leaked Decodo/Firecrawl creds) |
| SP-samsclub-decodo | RESOLVED | `sams_club` was deterministic-failing at ~100 s with 0 listings — Akamai `/are-you-human/` gate fired from AWS datacenter IP (homepage OK, `/s/` search redirects). Fix: same Decodo-scoped pattern as fb_marketplace (proxy relay + 13 telemetry kill flags + proxy bypass list + `SAMS_CLUB_DISABLE_IMAGES=1` default + homepage warmup kept for session cookies). After bandwidth-tuning sweep (bypass image CDNs, fonts, ad-verify, session replay, first-party telemetry subdomains; switch `ab wait` from `networkidle` → `load`): **3/3 listings, ~1,047 KB/run through Decodo — 86% reduction from 7,284 KB baseline**. 93% of remaining bytes are the site itself; 7% is PerimeterX (required for IP-rep). `scripts/ec2_deploy.sh` now sources `/etc/barkain-scrapers.env` and injects `DECODO_PROXY_*` env for both retailers via `case` on retailer name. Regression-guarded in `test_sams_club_extract_flags.py` (42 asserts). See docs/SCRAPING_AGENT_ARCHITECTURE.md §C.12 | — (follow-up: CDP request interception to block analytics XHRs within www.samsclub.com — not worth the complexity at 1 MB/scrape) |

---

## What's Next

1. **Phase 2 CLOSED** — `v0.2.0` tagged (2026-04-16). Outstanding: revoke leaked PAT `gho_UUsp9ML7…` in GitHub UI (SP-L1-b, Mike).
2. **Phase 3 — Recommendation Intelligence (IN PROGRESS):** 3a ✅ text search (#22, #23). 3b ✅ eBay Browse API + deletion webhook (#24). Next: 3c M6 Recommendation Engine (Claude Sonnet synthesis), 3d card rewards, 3e portal stacking, 3f image scan, 3g receipts, 3h identity stacking, 3i savings dashboard, 3j coupons, 3k hardening + `v0.3.0`.
3. **Phase 4 — Production Optimization:** Best Buy / Keepa API adapters, App Store submission, Sentry error tracking
4. **Phase 5 — Growth:** Push notifications (APNs), web dashboard, Android (KMP)

---

## Production Infra (EC2) — How Future Sessions Reach + Monitor It

> **Single-host deployment** for Phase 2 / early Phase 3 live-testing. All 11 scraper containers + the FastAPI backend (eBay webhook) run on one `t3.xlarge` in `us-east-1`. Instance is intentionally left running between sessions — don't auto-stop unless Mike says.

**Access:**
- **SSH:** `ssh -i ~/.ssh/barkain-scrapers.pem ubuntu@54.197.27.219`
- **EC2 instance id:** `i-09ce25ed6df7a09b2` (region `us-east-1`)
- **Security group:** `sg-0235e0aafe9fa446e` (scrapers 8081-8091 + web 80/443)
- **Public webhook:** `https://ebay-webhook.barkain.app` (A record → EC2 IP; Let's Encrypt auto-renew via Caddy)

**Quick health sweep** (copy-paste friendly):
```bash
# All 11 scraper containers (ports 8081–8091)
ssh -i ~/.ssh/barkain-scrapers.pem ubuntu@54.197.27.219 \
  'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"'

# Backend API (eBay webhook + Browse API adapter)
ssh -i ~/.ssh/barkain-scrapers.pem ubuntu@54.197.27.219 \
  'systemctl is-active barkain-api caddy && \
   sudo journalctl -u barkain-api -n 20 --no-pager'

# Fire an extract against a specific retailer (replace port)
ssh -i ~/.ssh/barkain-scrapers.pem ubuntu@54.197.27.219 \
  'curl -s --max-time 120 -X POST http://localhost:8081/extract \
    -H "Content-Type: application/json" \
    -d "{\"query\":\"Apple AirPods Pro 2\",\"max_listings\":3}" | jq .'

# Webhook live-verify (handshake + POST)
curl -s "https://ebay-webhook.barkain.app/api/v1/webhooks/ebay/account-deletion?challenge_code=test" | jq .
```

**Ports:** `amazon:8081 bestbuy:8082 walmart:8083 target:8084 homedepot:8085 lowes:8086 ebaynew:8087 ebayused:8088 samsclub:8089 backmarket:8090 fbmarketplace:8091`. Backend `uvicorn` on `127.0.0.1:8000` behind Caddy on `:443`.

**Redeploy** (backend code change — webhook or Browse API adapter):
```bash
rsync -az --delete --exclude='.git/' --exclude='__pycache__/' --exclude='tests/' --exclude='.venv/' \
  -e "ssh -i ~/.ssh/barkain-scrapers.pem" \
  backend/ ubuntu@54.197.27.219:/home/ubuntu/barkain-api/
ssh -i ~/.ssh/barkain-scrapers.pem ubuntu@54.197.27.219 'sudo systemctl restart barkain-api'
```

**Redeploy** (scraper containers — selector fixes): use `ec2_deploy.sh` at `/home/ubuntu/` or rsync to `/home/ubuntu/barkain/` and rebuild the affected container (`docker compose up -d --build <name>`).

**Env file:** `/etc/barkain-api.env` (mode 600). Holds `EBAY_APP_ID`, `EBAY_CERT_ID`, `EBAY_VERIFICATION_TOKEN`, `EBAY_ACCOUNT_DELETION_ENDPOINT`, `DATABASE_URL` (placeholder), `REDIS_URL` (placeholder). DB/Redis are not actually running on this host — backend only serves webhook + Browse API adapter, neither hits PG/Redis.

**Known retailer health** (as of 3b live run): `amazon / bestbuy / walmart / target / homedepot / samsclub / backmarket / fbmarketplace` return listings. `lowes` degrades to 0 under parallel load (resource contention on t3.xlarge). `ebaynew` + `ebayused` no longer served by containers — route through the Browse API adapter in `backend/modules/m2_prices/adapters/ebay_browse_api.py` at 0.5-1.5 s/call.

**Cost-stop if idle:**
```bash
aws ec2 stop-instances --instance-ids i-09ce25ed6df7a09b2 --region us-east-1
# Restart: aws ec2 start-instances ... — Caddy + systemd auto-start; the public IP
# is static (54.197.27.219) so DNS doesn't need to change.
```

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

> - **SSE streaming:** `text/event-stream` + `asyncio.as_completed`; iOS uses manual byte splitter (not `AsyncBytes.lines`); falls back to batch on error (2c, 2c-fix)
> - **Identity discounts:** zero-LLM SQL match < 150 ms; dedupe `(retailer_id, program_name)`; fetched post-SSE-loop (never inside `.done`); failure non-fatal (2d)
> - **Card matching priority:** rotating > user-selected > static > base; Cash+ / Customized Cash / Shopper Cash resolve per-user via `user_category_selections` (2e)
> - **Billing tier — two sources of truth by design:** iOS RC SDK for UI gating; backend `users.subscription_tier` for rate limiting; webhook converges with ≤60 s drift. `DEMO_MODE` renamed from `BARKAIN_DEMO_MODE` in 2i-b and read via `settings.DEMO_MODE` at call-time, not import (2f, 2i-b)
> - **Webhook idempotency:** SETNX dedup (`revenuecat:processed:{event.id}`, 7d TTL) + SET-not-delta math (replays idempotent) (2f)
> - **Tier-aware rate limit:** `_resolve_user_tier` caches `tier:{user_id}` 60 s; pro = base × `RATE_LIMIT_PRO_MULTIPLIER`; falls open to free on infra blip (2f)
> - **Migrations 0004/0006:** index + CHECK constraint mirrored on `__table_args__` so test DB via `create_all` matches alembic. Idempotent `DO $$...END $$` keyed on catalog (2f, 2i-b)
> - **Affiliate URLs:** backend-only construction via `AffiliateService.build_affiliate_url`; `SFSafariViewController` (not WKWebView) so cookies persist; fail-open resolver never throws (2g)
> - **Background workers:** LocalStack SQS for dev, `moto[sqs]` for tests; boto3 via `asyncio.to_thread`; workers reuse services (`get_prices(force_refresh=True)`). `SQSClient` uses `_UNSET` sentinel so tests can force `endpoint_url=None` (2h)
> - **Portal rates via `httpx` + BeautifulSoup** — deliberate deviation from Job 1 agent-browser spec. Parsers anchor on stable attributes (`aria-label`, semantic classes), NOT hash-based CSS. Rakuten `"was X%"` refreshes `portal_bonuses.normal_value`; others seed on first observation (2h)
> - **`is_elevated` column is `GENERATED ALWAYS STORED`** — worker never writes it; reading post-upsert confirms spike math (2h)
> - **Discount verification three-state:** `verified` / `flagged_missing_mention` (soft, no counter bump) / `hard_failed` (4xx/5xx/net → `consecutive_failures += 1`); 3 strikes flips `is_active=False`; `last_verified` always updates (2h)
> - **`_classify_retailer_result` is the single classification authority** for batch + stream paths (extracted 2i-b; deleted ~80 drifted duplicate lines) (2i-b)
> - **`device_name` → `product_name` rename deferred** — 26 call sites incl. load-bearing Gemini system instruction; too risky during hardening; iOS already uses `name` (2i-b)
> - **Worker CLI scripts MUST `from app import models`** so cross-module FKs resolve at flush time. The 2h moto tests passed because fixtures imported explicitly; only real LocalStack runs exposed it. Same fix applied preemptively to `run_watchdog.py` (2i-c)
> - **Test DB drift auto-detected** in `conftest.py:_ensure_schema` via `idx_products_name_trgm` marker probe (Step 3a updated from `chk_subscription_tier`). Missing → drop+recreate. Update marker with each new migration (2i-c, 3a)
> - **Watchdog `CONTAINERS_ROOT` = `parents[2]`** (was `parents[1]` → nonexistent `backend/containers/`). 2h unit tests stubbed the FS and missed it; 2i-d live `--check-all` exposed it. Same pattern as 2i-c worker-model bug — mocks hid the latent path assumption (2i-d)
> - **XCUITest affiliate-sheet assertion uses OR-of-3 signals** (SFSafari visible / Done button / original row non-hittable) because iOS 26 SFSafariVC chrome lives outside the host-app accessibility tree. Authoritative proof is the `affiliate_clicks` DB row (2i-d)
> - **Deploy via rsync when GitHub auth is broken:** `rsync -az --delete --exclude='.git/'` then run Phase C/D of `scripts/ec2_deploy.sh` inline (skip `git pull`). MD5 still validates against rsync'd host copy (2i-d)
> - **Facebook Marketplace needs Decodo residential proxy:** datacenter IPs (AS14618) redirect to `/login/`; `containers/fb_marketplace/proxy_relay.py` relays `:18080` → `gate.decodo.com:7000`. Needs `DECODO_PROXY_USER`/`_PASS` (2i-d)
> - **Decodo proxy must be scoped to Facebook — NOT global Chromium egress** (2026-04-17 hotfix). Chromium with `--proxy-server=...` alone sends ALL requests (component-updater, safe-browsing, optimization-guide, GCM, autofill) through the proxy, burning paid residential bytes. `containers/fb_marketplace/extract.sh` now: (a) disables background-networking / sync / component-update / metrics / etc., (b) sets `--proxy-bypass-list` for google/gvt1/gstatic/doubleclick so telemetry goes out the datacenter IP direct, (c) blocks images via `--blink-settings=imagesEnabled=false` (opt-out: `FB_MARKETPLACE_DISABLE_IMAGES=0`) — extract.js only reads `<img src>` as a string. Regression-guarded by `test_fb_marketplace_extract_flags.py` + `test_firecrawl_payload_has_no_decodo_overlay` + `test_fetch_walmart_makes_exactly_one_request_per_call`. Full rationale: docs/SCRAPING_AGENT_ARCHITECTURE.md §C.11
> - **sams_club uses the same Decodo-scoped pattern** (2026-04-18, SP-samsclub-decodo). Sam's Club `/s/` gate → `/are-you-human?url=...`; homepage loads fine. Same 13 telemetry flags, plus aggressive bypass list that routes image CDNs (`*.samsclubimages.com`, `*.walmartimages.com`), fonts, ad-verify, session replay, and first-party telemetry subdomains (`beacon.samsclub.com`, `dap.samsclub.com`, `titan.samsclub.com`, `scene7.samsclub.com`, `dapglass.samsclub.com`) via direct datacenter IP instead of paid Decodo bytes. `ab wait --load` switched from `networkidle` → `load` to skip post-render telemetry phase (saved ~500 KB/run). Bare-domain forms (`crcldu.com`, `wal.co`) included because Chromium's `*.foo` glob doesn't match bare `foo`. Final: **~1,047 KB/run, 86% reduction from 7,284 KB**. 93% of remaining bytes are the site itself; 7% is PerimeterX (MUST stay on-proxy or the session gets flagged). Homepage warmup is load-bearing (session cookies). `scripts/ec2_deploy.sh` sources `/etc/barkain-scrapers.env` and injects `DECODO_PROXY_{USER,PASS}` for both `fb_marketplace` and `sams_club` via a `case` on retailer name. **Gotcha: use `cut -d= -f2-`, not `-f2`, when reading Decodo creds from `docker inspect` — the base64 password can end in `=` and `-f2` strips it silently (symptom: `CONNECT tunnel failed, response 407` on first deploy).** Regression-guarded by `test_sams_club_extract_flags.py` (42 asserts including `test_perimeterx_is_not_bypassed` and `test_samsclub_main_site_not_bypassed`). Full rationale: docs/SCRAPING_AGENT_ARCHITECTURE.md §C.12

### Phase 3

> - **eBay Browse API adapter replaces `ebay_new`/`ebay_used` container legs** when `EBAY_APP_ID` + `EBAY_CERT_ID` are set (else falls through to container, same pattern as `WALMART_ADAPTER`). Sub-second vs 70-second container calls. Tokens via `client_credentials` grant, 2 hr TTL, cached in-process with asyncio lock around refresh. On 401 we invalidate the cache so the next call re-mints (3b)
> - **eBay filter DSL uses `|` not `,`:** `conditionIds:{1000|1500}` filters, `conditionIds:{1000,1500}` silently doesn't. Discovered in live smoke when ebay_new/ebay_used returned identical mixed-condition results. The text form (`conditions:{NEW}`) also silently no-ops — always use numeric `conditionIds` (3b)
> - **eBay Marketplace Account Deletion webhook is a GDPR prerequisite** for Browse API production access. GET handshake returns `SHA-256(challenge_code + token + endpoint_url)` as hex; POST is log-and-ack-204 since Barkain doesn't store per-user eBay data. Both env vars MUST match the portal exactly or the hash drifts (3b)
> - **Backend deploys onto the scraper EC2 via Caddy + systemd uvicorn** (not a separate host) — Caddy auto-manages Let's Encrypt via TLS-ALPN-01 challenge, reverse-proxies `:443` to `127.0.0.1:8000`. Single-host was the cheap path for the eBay webhook; full ECS Fargate + ALB when the broader backend ships (3b)
