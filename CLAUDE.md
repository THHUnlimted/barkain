# CLAUDE.md — Barkain

> **Purpose:** Root orientation for AI coding agents. This file alone should let a new session understand the project, find anything, and follow conventions.
> **Last updated:** 2026-04-24 (v5.26 — fix/search-relevance-pack-1: price-outlier <40 % median on {ebay,fb} (≥4 listings); FB soft model gate; family-prefix SKU `RZ07-0074`; `[A-Z]\d{3,4}` pattern (G613/G915); `upcitemdb.model` plumbed; partial-listing regex widened; Tier-2 +accessor/thumbstick. Backend 589→597. Full entry in docs/CHANGELOG.md.)

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
pytest --tb=short -q          # 589 backend tests (Docker PG port 5433, NOT SQLite)
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

**Pattern:** MVVM (iOS) + Modular Monolith (FastAPI Python 3.12+) + Containerized Scrapers (per-retailer Chromium + agent-browser).

**Walmart** uses an HTTP adapter (`WALMART_ADAPTER={decodo_http,firecrawl,container}`) since PerimeterX defeats headless Chromium — `__NEXT_DATA__` is server-rendered before JS. Firecrawl is currently 100% CHALLENGE'd; kept selectable.

**Zero-LLM matching:** identity discounts, card rewards, rotating categories, portal bonuses all resolve via pure SQL joins. LLMs are only at the M1 boundary (product resolution) and M6 has been deterministic since 3e.

**Data flow (barcode):** iOS → `POST /products/resolve` (M1: Gemini + UPCitemdb cross-val + PG cache) → `GET /prices/{id}/stream` (SSE; M2 fans out to 9 retailers in parallel) → on done `GET /identity/discounts` + `GET /cards/recommendations` → `POST /api/v1/recommend` for the M6 stack → `PriceComparisonView` renders. Tap retailer → `POST /affiliate/click` → `SFSafariViewController` with tagged URL.

**Concurrency:** Python `async`/`await` throughout. Swift structured concurrency on iOS.

---

## Conventions

### Backend (Python)
- FastAPI + Pydantic v2 schemas; Alembic migrations in `infrastructure/migrations/` (backward-compatible only); SQLAlchemy 2.0 async; **constraints mirrored in `__table_args__`** for test `create_all` parity
- Per-module layout `router.py` / `service.py` / `schemas.py`; modules import each other directly (no event bus)
- All AI calls go through `ai/abstraction.py` — never import `google.genai` / `anthropic` / `openai` directly
- Background workers = SQS (LocalStack dev / real AWS prod) + `scripts/run_worker.py <subcmd>`, not Celery; workers translate messages to existing service calls (`price_ingestion` reuses `PriceAggregationService`); ack only on success or permanently-bad data
- Per-retailer adapters in `m2_prices/adapters/` normalize to a common price schema; BS4 for structured HTML, `re` for patterns
- **`session.refresh()` does NOT autoflush** — assert against the in-memory object via the identity map (2h learning)
- **Three-mode optional params** (unset / override / force-None): `_UNSET = object()` sentinel, not `or`-chains
- **Divergence docs in 3 places** (code docstring + arch doc + CHANGELOG) when a worker/service diverges from planning pseudocode (e.g. `portal_rates` uses httpx+BS4 not agent-browser)

### iOS (Swift)
- SwiftUI + `@Observable` VMs (iOS 17+); no force unwraps except Previews; `// MARK: -` sections; extract subviews past ~40 lines
- Services injected via `.environment(...)`; `APIClient` uses a custom `EnvironmentKey` because the protocol is Sendable
- SPM only; no CocoaPods
- **SSE consumer:** manual byte-level splitter over `URLSession.AsyncBytes`, NOT `bytes.lines` (buffers aggressively, 2c-val-L6)
- **Simulator `API_BASE_URL`:** `http://127.0.0.1:8000`, NOT `localhost:8000` (skips IPv6 happy-eyeballs)
- **SSE debug:** subsystem `com.barkain.app` / category `SSE` os_log captures everything; watch with `xcrun simctl spawn booted log stream --level debug --predicate 'subsystem == "com.barkain.app" AND category == "SSE"'`
- **Hiding `.searchable` nav bar:** `.searchable(isPresented:)` only toggles focus; apply `.toolbar(.hidden, for: .navigationBar)` on the root view to actually hide it (SearchView pattern, ui-refresh-v1)
- **Snapshot tests for branched render paths:** views where multiple branches each render their OWN top-level container w/ 2+ duplicated sections (precedent: `ProfileView`'s 4 `content` branches — loading/error/empty-scroll/profileSummary-scroll) get a test per branch in `BarkainTests/Features/<feature>/…SnapshotTests.swift`; baselines beside the test under `__Snapshots__/`. Record w/ `RECORD_SNAPSHOTS=1` in scheme env; CI runs without. Intra-branch state permutations that materially change layout get their own test (see `ProfileViewSnapshotTests` — 9 tests covering branches + pro-tier / non-zero affiliate stats / saved marketplace location / kitchen-sink chips). **L-smoke-7:** `ProfileView` is the only view in `Features/*` with this shape (audited `ContentView`/`Search`/`Scanner`/`PriceComparison`/`Home`/`Savings`/`Billing`/`Recommendation`); don't re-audit unless a new matching view is introduced. **A11y-grep ruled out:** 4 walker variants all failed on iOS 26.4's SwiftUI bridge — PNG diff is the only regression signal; identifiers stay in view code as XCUITest anchors only

### Git
- Branch per step `phase-N/step-Na`; conventional commits (`feat:`/`fix:`/`docs:`/`test:`/`refactor:`); tags at phase boundaries `v0.N.0`
- **Developer handles all git ops — agent never commits without explicit request**
- Stacked-PR conflicts after lower squash-merge: `git rebase origin/main && git push --force-with-lease` (git auto-detects patch equivalence)

### Classification Rule
Before implementing any feature, check `docs/FEATURES.md` for its AI/Traditional/Hybrid classification. If classified as Traditional, do NOT use LLM calls. If Hybrid, AI generates and code validates/executes.

---

## Development Methodology

Two-tier AI workflow: **Planner** (Claude Opus via claude.ai) authors prompt packages, reviews error reports, evolves prompts. **Executor** (Claude Code) implements + tests. Loop: Planner → Agent plans + builds + tests → Developer writes error report → Planner reviews. Prompt packages live in `prompts/` (not in repo). Every step includes a FINAL section mandating guiding-doc updates. Pre-fix blocks carry known issues forward.

---

## Tooling

**MCP:** Postgres MCP Pro · Redis MCP · Context7 · Clerk · XcodeBuildMCP.
**CLIs:** `gh` `docker` `ruff` `alembic` `pytest` `swiftlint` `jq` `xcodes`; deploy adds `aws` `railway`; Phase 4+ adds `fastlane` `vercel`.

---

## Current State

**Phase 1 — Foundation:** ✅ tagged `v0.1.0` (2026-04-08). Barcode → Gemini UPC → 9-retailer price comparison (was 11; lowes + sams_club retired 2026-04-18) → iOS display. Validated on physical iPhone.

**Phase 2 — Intelligence Layer:** ✅ tagged `v0.2.0` (2026-04-16). 2a–2i shipped across PRs #3–#21: Watchdog, Walmart HTTP adapter, UPCitemdb cross-val, SSE + iOS byte splitter, M5 Identity (52 programs), Card portfolio (30 cards), M11 Billing (RC + webhook), M12 Affiliate, SQS workers, code-quality sweep, EC2 redeploy + UITests. Per-step in `docs/CHANGELOG.md`.

**Phase 3 — Recommendation Intelligence: IN PROGRESS**

> Step rows below are 1-line indices. Full motivation + decisions + file inventory live per-step in `docs/CHANGELOG.md`.

| Step | What | BE | iOS | PR |
|------|------|:-:|:-:|:-:|
| 3a | M1 product text search (pg_trgm + Gemini fallback) + SearchView | +10 | +7 | #22, #23 |
| 3b | eBay Browse API adapter + GDPR deletion webhook + FastAPI on scraper EC2 (Caddy+LE) | +13 | — | #24 |
| demo/post-demo prep | Walmart decodo_http default; Best Buy Products API; Decodo Scraper API for Amazon; lowes/sams_club retired | +127 | — | #25–#31 |
| 3c (+hardening) | Search v2 3-tier cascade + variant collapse + price-stream `?query=` + eBay EPN affiliate fix; retailer retries + Redis cache layering + iOS sheet-anchor | +40 | +5 | #32 |
| 3d (+noise-filter) | Autocomplete (on-device prefix + `.searchable` + offline vocab); `_is_tier2_noise` denylist → Gemini escalation | +27 | +35 | #34, #36 |
| ui-refresh-v1/v2/v2-fix | Warm-gold design pass + new Home tab + Kennel section + nav-hide-during-stream + searchable mid-stream dismissal guard | +4 | — | #37–#40 |
| 3e | M6 Recommendation Engine — deterministic, no LLM (`/recommend` stacks identity+card+portal via `asyncio.gather`, p95 <150 ms, brand-direct ≥15 %) | +14 | +9 | #41 |
| 3f (+hotfix) | Purchase Interstitial + Activation Reminder; migration 0008 `affiliate_clicks.metadata`; per-retailer estimated_savings; migration 0009 `discount_programs.scope` | +7 | +9 | #42, #44 |
| Benefits Expansion (+follow-ups) | +10 student-tech + Prime YA (`scope='membership_fee'`); 0010 `is_young_adult`; `_dedup_best_per_retailer_scope` + `BRAND_ALIASES`; `/resolve-from-search` fallback | +10 | +7 | #45, #46 |
| fb-marketplace-location-resolver | Numeric FB Page ID end-to-end (slug retired); 0011 `fb_marketplace_locations`; 3-tier Redis→PG→live resolver w/ singleflight + GCRA bucket | +28 | +9 | #49 |
| experiment/tier2-ebay-search | 4 opt-in flags (default off); `SEARCH_TIER2_USE_EBAY` swaps UPCitemdb→Browse; `M2_EBAY_DROP_PARTIAL_LISTINGS` drops box-only/parts/etc. on `ebay_browse_api` | — | — | #50 |
| fb-resolver-followups | Dedicated `fb_location_resolve` rate bucket (5/min hard cap); DTO `source`→`resolution_path` + engine collapse to `live`; `location_default_used` pill; picker `retry()` + 3-cap; top-50 US-metro local seed | +4 | +9 | #51 |
| fb-resolver-postfix-1 | Extractor canonical-name validation: verb-agnostic primary pattern + 3-way decision (VALIDATED>FALLBACK>REJECTED) rejects sub-region IDs (West Raleigh, etc.) | +5 | — | #52 |
| 3g-A | Portal Live Integration backend: 0012 `portal_configs` + `m13_portal` module + 5-step CTA decision tree + `/portal/cta` + Resend alerting + Lambda infra (Mike runs `deploy.sh`) | +16 | — | #53 |
| 3g-B | Portal Live Integration iOS: `PortalCTA` model + interstitial row (≤3 sorted, FTC disclosure on SIGNUP_REFERRAL, amber promo); `PortalMembershipPreferences` + Profile toggles; M6 cache key adds `:p<sha1(active_portals)>:v5` so toggles bust stale recs; `affiliate_clicks.metadata` gains `portal_event_type`/`portal_source` for funnel split; demo seed deleted | +2 | +14 | #54 |
| 3g-B-fix-1 | Wire `portalMembershipsSection` into `ProfileView`'s second `ScrollView` branch (completed-profile path) — original 3g-B only patched the empty-profile branch. Sim screenshot during validation showed zero toggles for users with a saved identity. 1-line structural fix | — | — | #55 |
| search-resolve-perf-1 | Tiered `_merge()` by confidence (fixes Switch OLED→Switch 2); parallel Gemini+UPCitemdb in resolve paths (P50 17→5s, 404 34→13s); `upcitemdb.py` HTTPStatusError split; `ProductSearchResponse.cascade_path` | +6 | — | #61 |
| search-relevance-1 | Relevance pack: price-outlier <40 % median {ebay,fb}; FB soft model gate; family-prefix SKU `RZ07-0074`; `[A-Z]\d{3,4}` pattern (G613/G915); `upcitemdb.model` plumbed; partial-listing regex widened; Tier-2 +accessor/thumbstick | +8 | — | #62 |

**Test totals:** 597 backend + 179 iOS unit + 6 iOS UI (with experiment flags off — see L-Experiment-flags-default-off). `ruff check` clean. `xcodebuild` clean.

**Migrations:** 0001 (initial, 21 tables) → 0002 (price_history composite PK) → 0003 (is_government) → 0004 (card catalog unique index) → 0005 (portal bonus upsert + failure counter) → 0006 (`chk_subscription_tier` CHECK) → 0007 (pg_trgm + trgm GIN idx) → 0008 (`affiliate_clicks.metadata` JSONB) → 0009 (`discount_programs.scope` — product / membership_fee / shipping) → 0010 (`is_young_adult` on `user_discount_profiles`) → 0011 (`fb_marketplace_locations` — city→FB Page ID cache w/ tombstoning) → 0012 (`portal_configs` — display + signup-promo + alerting state for shopping portals). Drift marker in `tests/conftest.py::_ensure_schema` now checks `portal_configs`.

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
| noise-filter-L1 | MEDIUM | `_TIER2_NOISE_CATEGORY_TOKENS` lacks "game download" — tiered merge promotes digital-game BBY rows when DB/BBY lack a console match ("Switch OLED" → `/recommend` 422). Widen tokens | Phase 3 |

---

## What's Next

1. **Phase 2 CLOSED** — `v0.2.0` tagged (2026-04-16). Outstanding: revoke leaked PAT `gho_UUsp9ML7…` in GitHub UI (SP-L1-b, Mike).
2. **Phase 3:** 3a–3d-noise-filter ✅ (#22–#36), ui-refresh-v1/v2/v2-fix ✅ (#37–#40), 3e (#41), 3f (+hotfix) ✅ (#42, #44), Benefits Expansion ✅ (#45–#47), FB Marketplace location + resolver ✅ (#48, #49), experiment/tier2-ebay-search ✅ (#50, opt-in), fb-resolver-followups + postfix-1 ✅ (#51, #52), 3g-A + 3g-B + 3g-B-fix-1 ✅ (#53, #54, #55), search-resolve-perf-1 ✅ (#61), search-relevance-1 ✅ (#62). Next: prod FB seed (Mike), pill→Profile cross-tab nav, eBay-Tier-2 graduation call, 3h Vision, 3i receipts, 3k savings, 3l coupons, 3m hardening + `v0.3.0`. 3j folded into 3e
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
> **Note:** EC2 has no PG/Redis on this host — skip `alembic upgrade head` against EC2 and run migrations only against the full-app DB (local Docker PG in dev; production DB wherever `DATABASE_URL` points). The EC2 backend is a webhook/scraper-API shim.

**Redeploy scrapers:** `scripts/ec2_deploy.sh` (or rsync to `/home/ubuntu/barkain/` + `docker compose up -d --build <name>`).

**Retailer health (2026-04-18 bench):** `target/homedepot/backmarket` 3/3 via container; `fbmarketplace` 3/3 via Decodo (~30 s, ~17 KB); `walmart` via `walmart_http` decodo_http (~3.3 s); `amazon` via `amazon_scraper_api` (~3.2 s, when `DECODO_SCRAPER_API_AUTH` set); `bestbuy` via `best_buy_api` (~82 ms, when `BESTBUY_API_KEY` set); `ebaynew/ebayused` via `ebay_browse_api` (~500 ms, when `EBAY_APP_ID/CERT_ID` set).

**Cost-stop:** `aws ec2 stop-instances --instance-ids i-09ce25ed6df7a09b2 --region us-east-1` (static IP `54.197.27.219` survives stop/start).

---

## Key Decisions Log

> Quick-ref index only. Full rationale + code pointers live in `docs/CHANGELOG.md` (Key Decisions Log + per-step entries).

### Phase 1 + 2 (terse — see CHANGELOG for rationale)
- Container auth VPC-only; `WALMART_ADAPTER={container,firecrawl,decodo_http}`; fd-3 stdout (`exec 3>&1; exec 1>&2`); `EXTRACT_TIMEOUT=180`
- Relevance: model-number hard gate + variant-token + ordinal + brand + 0.4 token overlap; UPCitemdb cross-val alongside Gemini, brand agreement picks winner
- SSE via `asyncio.as_completed` + iOS byte splitter; batch fallback on error. Identity zero-LLM SQL join <150 ms, post-SSE, non-fatal. Card priority: rotating > user > static > base
- Billing: iOS RC SDK for UI, backend `users.subscription_tier` for rate limit; webhook idempotency SETNX 7d; tier cache 60 s fail-open; migrations mirror constraints on `__table_args__` for test parity
- Workers: LocalStack SQS / `moto[sqs]`; boto3 via `asyncio.to_thread`; `_UNSET` sentinel for tri-state params; `is_elevated` GENERATED STORED on portal_bonuses
- `_classify_retailer_result` is the single classifier for batch + stream. Worker scripts MUST `from app import models` for FK flush. Drift auto-detected in `conftest._ensure_schema`; update marker each migration
- fb_marketplace needs Decodo residential w/ scoped routing (kill-flags + `--proxy-bypass-list`); see `docs/SCRAPING_AGENT_ARCHITECTURE.md` §C.11

### Phase 3 (terse — see CHANGELOG for the why behind each)
- **Adapters/external APIs.** eBay Browse on `EBAY_APP_ID`+`CERT_ID` (2h TTL, filter DSL `|` not `,`); GDPR webhook = GET SHA-256 + POST 204; Best Buy API on `BESTBUY_API_KEY` (~150 ms); Decodo Scraper API for Amazon on `DECODO_SCRAPER_API_AUTH` (~3 s, listings at `content.results.results.organic[]`); Decodo: `proxy_relay.py` reads HOST+PORT separately
- **Active scraped retailers = 9.** lowes + sams_club retired 2026-04-18 (rows `is_active=False` for FK); `*_direct` stay `is_active=True` as identity-redirect targets
- **Search v2 cascade + perf + relevance.** normalize → Redis → DB pg_trgm@0.3 → Tier 2 `gather(BBY, UPCitemdb)` → Tier 3 Gemini on Tier 2 irrelevant/`force_gemini`. Tiered merge: strong (conf ≥ `_STRONG_CONFIDENCE=0.55`) / weak, `DB>BBY>UPCitemdb>Gemini` tiebreaks. `resolve_from_search` + `_resolve_with_cross_validation` via `gather(return_exceptions=True)` — P50 17→5s, 404 34→13s. Retry externalized to `_get_gemini_data_retry`. `upcitemdb.py` `HTTPStatusError` split. `cascade_path` populated. `?query=` override on `/prices/{id}/stream`. Relevance pack (#62): `_pick_best_listing` price-outlier <40 % median on `{ebay,fb}` (min 4); FB soft model gate caps 0.5 when SKU absent; `_LONG_MODEL_PREFIX_RE` emits family stem; `[A-Z]\d{3,4}` pattern catches G613/G915; `lookup_upc` returns `model`; `_TIER2_NOISE_*` +accessor/thumbstick
- **3e M6 Recommendation — deterministic, no LLM.** `gather`s Prices+Identity+Cards+Portals, <150 ms p95. `final = base − identity`; rebates on post-identity price. Tiebreak `effective_cost` → condition → well-known retailer. Brand-direct callout ≥15 % at `*_direct`. 15-min Redis cache; iOS hero gated on `streamClosed`+`identityLoaded`+`cardsLoaded`; failures → silent nil
- **3f Interstitial + hotfix.** `PurchaseInterstitialSheet` from hero CTA + row taps; activation ack session-scoped; `affiliate_clicks.activation_skipped` (0008); per-retailer `estimated_savings` with highest-scraped fallback; `discount_programs.scope ∈ {product, membership_fee, shipping}` (0009). M6 cache key extended `:c<sha1(card_ids)>:i<sha1(identity_flags)>:v4` so portfolio/profile changes bust stale recs. Pre-fixes: `BarePreviewAPIClient`, `_db_url.py`, `without_demo_mode`
- **Benefits Expansion.** +10 student-tech + Prime YA (`scope='membership_fee'`); +4 `*_direct`; `is_young_adult` axis (0010); `program_type='membership'` retired. `_dedup_best_per_retailer_scope` keys (retailer_id, scope) so different scopes survive; `BRAND_ALIASES` fails closed on competing brand (ThinkPad→lenovo, etc.). iOS scopeBadge + price `lineLimit(1)+minimumScaleFactor(0.7)` + pills `VStack`. `/resolve`→`/resolve-from-search` fallback on Gemini UPC hallucination
- **FB Marketplace location resolver (0011).** Numeric FB Page ID end-to-end; 3-tier Redis(24h)→PG→live (Startpage/DDG/Brave via Decodo). Tombstone `(NULL,'unresolved')` 1h; all-engines-throttled → 5-min Redis bar only (no PG write). GCRA bucket GET+SET (fakeredis no EVAL); singleflight + **subscribe-before-recheck** closes race window. Miles→km at `ContainerClient.extract`. iOS `Stored.fbLocationId` is bigint-safe String; v1→v2 silent clear; picker FSM idle→geocoding→resolving→resolved
- **fb-resolver-followups (#51) + postfix-1 (#52).** Dedicated `fb_location_resolve` bucket (5/min, no pro multiplier — `_NO_PRO_MULTIPLIER_CATEGORIES` allowlist). Public DTO renames `source`→`resolution_path` + collapses engine names to `live` (DB column unchanged). `location_default_used` per-row flag drives "Using SF default" pill. Picker `retry()` (no CLGeocoder roundtrip), 3-attempt cap, `.rateLimited` kind. Postfix-1: 3-way decision (VALIDATED > FALLBACK > REJECTED) rejects sub-region IDs when a city-norm canonical is available, falls through to first-match when none is
- **experiment/tier2-ebay-search (#50).** 4 env flags, all default off. `SEARCH_TIER2_USE_EBAY` swaps UPCitemdb for Browse `item_summary/search` (rows tagged `"upcitemdb"` to avoid widening iOS enum). `_sanitize_ebay_title` strips seller noise. **GTIN finding:** Browse omits `gtin` even w/ EXTENDED → `USE_GTIN` no-op; `SKIP_UPC` is de facto. `M2_EBAY_DROP_PARTIAL_LISTINGS` drops box-only/parts/charger-only/as-is on `ebay_browse_api`
- **3g-A portal monetization backend (#53).** 0012 `portal_configs` (display + signup-promo + `consecutive_failures`/`last_alerted_at` — alerting on the same table is the cheapest place since the worker already touches the row each invocation). `PortalMonetizationService` 5-step decision tree per portal (feature-flag → 24h staleness → MEMBER_DEEPLINK w/ graceful fallthrough → SIGNUP_REFERRAL w/ FTC disclosure → GUIDED_ONLY); deterministic sort `(rate desc, portal asc)`; rejected candidates logged at DEBUG (PR #52 lesson — opaque first-match-wins is a latent bug). `POST /api/v1/portal/cta` on `general` bucket. Resend alerting (3 consecutive empty → email; 24h throttle; empty key → log+skip, mirrors AFFILIATE_WEBHOOK_SECRET). Lambda infra files only — EC2 has no DB so cron CANNOT run there
- **3g-B portal monetization iOS.** M6 cache key → `:c<...>:i<...>:p<sha1(active_portals)>:v5` — toggling membership busts stale recs; hashes the *active* set only (toggle-off-then-on doesn't double-bust). Winner-only `portal_ctas` on `StackedPath`. `PortalMembershipPreferences` mirrors `LocationPreferences` UserDefaults wrapper, open-ended `[String: Bool]` → future portals need no migration. Interstitial portal row: ≤3 sorted CTAs; FTC disclosure inline + per-CTA on SIGNUP_REFERRAL only. `affiliate_clicks.metadata` extends via existing 0008 JSONB — new `portal_event_type` validated at boundary → iOS typos hit 422. **Codable pitfall:** `.convertFromSnakeCase` → `portalCtas` (lowercase `as`); see CHANGELOG. **`ProfileView` dual-branch pitfall (3g-B-fix-1):** two `ScrollView` branches (empty-profile vs `profileSummary`) — when adding a Profile section, grep a nearby section (e.g. `cardsSection`) in BOTH. Demo seed `seed_portal_bonuses_demo.py` deleted
