# CLAUDE.md — Barkain

> **Purpose:** Root orientation for AI coding agents. This file alone should let a new session understand the project, find anything, and follow conventions.
> **Last updated:** 2026-04-25 (v5.31 — category-relevance-1: 5 fixes from `Barkain Prompts/Category_UPC_Efficacy_Report_v1.md` (15-SKU sweep across Electronics/Appliances/Home&Tools). **#1 FB strict overlap floor** — `m2_prices/service.py:_score_listing_relevance` now requires raw token overlap >=0.6 (was implicit 0.4) when soft gate is active; new constant `_FB_SOFT_GATE_MIN_OVERLAP`. Pre-fix Breville BES870XL ($499 retail) showed $18.95 hero on FB drip-tray listings. **#1b appliance/tool model regex** — added `\b[A-Z]{2,4}\d{3,5}[A-Z]{1,4}\d{0,2}\b` to `_MODEL_PATTERNS` (catches BES870XL/DCD777C2/JES1072SHSS that 7 prior patterns missed). **#1c single-letter normalize** — `_extract_model_identifiers` pre-passes `Q 1200 → Q1200` so Gemini space-separated names trip the gate. **#2 R3 brand-bleed gate** — `m1_product/search_service.py:_is_tier2_noise` now hard-rejects rows where the leading meaningful query token (Toro/Husqvarna/etc.) doesn't appear in the haystack. **#3 strict-spec gate** — `_query_strict_specs` requires voltage tokens (40v/80v) and >=4-digit pure-numeric model numbers (5200) to match verbatim. **#4 brand fallback to product.name** — Rule 3 falls back to product.name first word when product.brand (e.g. "Conair Corporation") fails the title check. **#4b Rule 3b "for {brand}" template reject** — listings titled "X for Weber Q1200" / "X compatible with Cuisinart" now hard-rejected at score time; catches the Uniflasy $15.99 burner-tube case Amazon was serving for Weber. Demo headlines: Breville $18.95→$299.99, Weber $15.99→$239.99, Cuisinart 0/9→2/9, Toro brand-bleed gone. Backend 617→630 (+13 tests). Carry-forward: Decodo Amazon adapter strips brand from titles (real Weber listings now no_match — net win for demo, separate adapter fix); 3 SKUs unresolvable on Gemini-only no-UPC path (ASUS Chromebook CX1, Ryobi P1817, Husqvarna 130BT); Hamilton Beach 49981A digit-leading model code still not extracted; UPC-to-wrong-product on Vitamix 5200→E310, Greenworks 40V→80V, Toro→Greenworks (UPCitemdb data quality, upstream of relevance).)
> **Previous:** 2026-04-25 (v5.30 — interstitial-parity-1: 3 fixes from `Sim_Pre_Demo_Comprehensive_Report_v1.md`. **F#1** `PurchaseInterstitialSheet.swift` body restructured (StackingReceipt renders whenever any savings line exists, not gated behind `hasCardGuidance`). **F#1b** M6 `service.py:get_recommendation` filters `portal_by_retailer` by `active_memberships`. **F#2** `scripts/demo_check.py` evergreen UPC → `194252056639` (MacBook Air M1); threshold `7/9`→`5/9`. Backend 616→617 (+1 M6 membership-gate test); iOS 200→203 (+3 Swift Testing tests).)

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
| 3c (+hardening) | Search v2 3-tier cascade + variant collapse + `?query=` price-stream + eBay EPN; retailer retries + Redis cache layering | +40 | +5 | #32 |
| 3d (+noise-filter) | Autocomplete (on-device prefix + `.searchable` + offline vocab); `_is_tier2_noise` → Gemini escalation | +27 | +35 | #34, #36 |
| ui-refresh-v1/v2/v2-fix | Warm-gold design pass + new Home tab + Kennel section + nav-hide-during-stream + searchable mid-stream dismissal guard | +4 | — | #37–#40 |
| 3e | M6 Recommendation Engine — deterministic, no LLM (`/recommend` stacks identity+card+portal via `asyncio.gather`, p95 <150 ms, brand-direct ≥15 %) | +14 | +9 | #41 |
| 3f (+hotfix) | Purchase Interstitial + Activation Reminder; migration 0008 `affiliate_clicks.metadata`; per-retailer estimated_savings; migration 0009 `discount_programs.scope` | +7 | +9 | #42, #44 |
| Benefits Expansion (+follow-ups) | +10 student-tech + Prime YA (`scope='membership_fee'`); 0010 `is_young_adult`; `_dedup_best_per_retailer_scope`; `/resolve-from-search` fallback | +10 | +7 | #45, #46 |
| fb-marketplace-location-resolver | Numeric FB Page ID end-to-end; 0011 `fb_marketplace_locations`; 3-tier Redis→PG→live resolver w/ singleflight + GCRA bucket | +28 | +9 | #49 |
| experiment/tier2-ebay-search | 4 opt-in flags (default off); `SEARCH_TIER2_USE_EBAY` swaps UPCitemdb→Browse; `M2_EBAY_DROP_PARTIAL_LISTINGS` drops box-only/parts/etc. on `ebay_browse_api` | — | — | #50 |
| fb-resolver-followups + postfix-1 | Dedicated `fb_location_resolve` bucket (5/min); DTO `resolution_path` collapses engines to `live`; picker `retry()`; US-metro seed. Postfix-1: 3-way (VALIDATED>FALLBACK>REJECTED) rejects sub-region IDs | +9 | +9 | #51, #52 |
| 3g-A | Portal Live backend: 0012 `portal_configs` + `m13_portal` + 5-step CTA tree + `/portal/cta` + Resend alerting + Lambda infra | +16 | — | #53 |
| 3g-B | Portal Live iOS: `PortalCTA` + interstitial row (≤3, FTC on SIGNUP_REFERRAL, amber promo); `PortalMembershipPreferences` + Profile toggles; M6 cache key `:p<sha1(active_portals)>:v5`; `affiliate_clicks.metadata` += `portal_event_type`/`portal_source` | +2 | +14 | #54 |
| 3g-B-fix-1 | Wire `portalMembershipsSection` into `ProfileView`'s completed-profile `ScrollView` branch (3g-B only patched the empty-profile path) | — | — | #55 |
| search-resolve-perf-1 | Tiered `_merge()` by confidence (fixes Switch OLED→Switch 2); parallel Gemini+UPCitemdb (P50 17→5s, 404 34→13s); `cascade_path` on response | +6 | — | #61 |
| search-relevance-1 | Relevance pack: price-outlier <40% median {ebay,fb}; FB soft model gate; family-prefix SKU; `[A-Z]\d{3,4}` G-series; `upcitemdb.model`; Tier-2 +accessor noise | +8 | — | #62 |
| demo-prep-1 | F&F reliability: `RecommendationState.insufficientData` on /recommend 422 + envelope decode fix; `UnresolvedProductView` + `TabSelectionAction` for /resolve 404; 409 confidence gate + `/confirm` + `ConfirmationPromptView`; `make demo-check`/`demo-warm` + first Makefile | +12 | +11 | #63 |
| savings-math-prominence | Hero invert (`Save $X` 48pt → `effectiveCost at retailer` → `why`); shared `StackingReceiptView` (hero + interstitial); `Money.format` no `.00`; backend `error.message` audit; `APIError` softened. Pre-Fix: `APIClientErrorEnvelopeTests` + `make demo-check --no-cache --remote-containers=ec2` + `make verify-counts` | +4 | +10 | #64 |
| sim-edge-case-fixes-v1 | Pattern-UPC reject pre-Gemini in `service.py:resolve`; `RequestValidationError` handler wraps Pydantic 422s into canonical envelope; SearchView `.searchable` sync setter (Clear-text race); recents success-only + 200-char clamp; Manual UPC `.numberPad` + digit-filter + 12/13-guard + inline error w/ sheet-stays-open | +3 | — | #65 |
| interstitial-parity-1 | F#1 hero/interstitial parity: `PurchaseInterstitialSheet` body restructured to render `StackingReceiptView` independent of `hasCardGuidance` (`summaryBlock`+`directPurchaseBlock` → single `priceBreakdownBlock`). F#1b: M6 `get_recommendation` filters `portal_by_retailer` by active memberships — no aspirational portal savings the Continue button can't transit. F#2: `demo_check.py` evergreen UPC → MacBook Air M1; threshold 7→5; Makefile help synced | +1 | +3 | TBD |
| category-relevance-1 | 5 fixes from 15-SKU obscure-SKU sweep across Electronics/Appliances/Home&Tools (`Category_UPC_Efficacy_Report_v1.md`). #1 FB strict overlap floor 0.4→0.6 + `_FB_SOFT_GATE_MIN_OVERLAP` constant. #1b new `_MODEL_PATTERNS` regex `[A-Z]{2,4}\d{3,5}[A-Z]{1,4}\d{0,2}` (BES870XL/DCD777C2/JES1072SHSS class). #1c `_extract_model_identifiers` pre-pass collapses `Q 1200`→`Q1200`. #2 brand-bleed gate: leading meaningful query token must appear in haystack (Toro→Greenworks rejection). #3 `_query_strict_specs` voltage (40v/80v) + 4+digit pure-numeric (5200) verbatim match. #4 Rule 3 brand fallback to product.name first word (Conair Corp→Cuisinart). #4b Rule 3b `for {brand}`/`compatible with {brand}` template hard-reject (Uniflasy "for Weber Q1200" $15.99 leak). Demo headlines: Breville $18.95→$299.99, Weber $15.99→$239.99, Cuisinart 0/9→2/9 | +13 | — | TBD |

**Test totals:** 630 backend + 203 iOS unit + 6 iOS UI (with experiment flags off — see L-Experiment-flags-default-off). `ruff check` clean. `xcodebuild` clean.

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
| cat-rel-1-L1 | MEDIUM | Decodo Amazon adapter strips brand from titles ("Q1200 Liquid Propane…" without "Weber" prefix) — real Weber listings now fail Rule 3 brand check post category-relevance-1, so Amazon shows `not_match` instead of $15.99 burner-tube hallucination. Net win for demo, but legit brand-prefixed listings are missed. Fix: preserve brand in Amazon adapter or add brand-as-prefix injection | Phase 3 |
| cat-rel-1-L2 | MEDIUM | 3 obscure-SKU classes (ASUS Chromebook CX1, Ryobi P1817, Husqvarna 130BT) resolve via Gemini name-only with `primary_upc=null`, so Manual UPC blocked AND `/products/resolve-from-search` 422s. iOS surfaces `RecommendationState.insufficientData(reason:)`. Fix: tighten `ai/prompts/upc_lookup.py` to require UPC for low-volume Tools brands | Phase 3 |
| cat-rel-1-L3 | LOW | Hamilton Beach 49981A digit-leading model code not extracted by any of `_MODEL_PATTERNS` (all patterns require letter prefix) — soft gate doesn't trip on FB. Listings still show $18 hero possibly. Adding a digit-led pattern is risky (year/capacity false positives); needs more test fixtures | Phase 3 |
| cat-rel-1-L4 | HIGH | UPCitemdb returns wrong canonical product for some UPCs: `703113640681`→Vitamix Explorian E310 (asked for 5200), `841821092511`→Greenworks 80V backpack blower (asked for 40V), `841821087104`→Greenworks mower (asked for Toro Recycler). Upstream UPCitemdb data quality, not search relevance. Fix path: post-resolve sanity check (does resolved name share a token with the user's search query?) | Phase 3 |

---

## What's Next

1. **Phase 2 CLOSED** — `v0.2.0` tagged (2026-04-16). Outstanding: revoke leaked PAT `gho_UUsp9ML7…` in GitHub UI (SP-L1-b, Mike).
2. **Phase 3:** 3a–3d-noise-filter ✅ (#22–#36), ui-refresh-v1/v2/v2-fix ✅ (#37–#40), 3e (#41), 3f (+hotfix) ✅ (#42, #44), Benefits Expansion ✅ (#45–#47), FB Marketplace location + resolver ✅ (#48, #49), experiment/tier2-ebay-search ✅ (#50, opt-in), fb-resolver-followups + postfix-1 ✅ (#51, #52), 3g-A + 3g-B + 3g-B-fix-1 ✅ (#53, #54, #55), search-resolve-perf-1 ✅ (#61), search-relevance-1 ✅ (#62), demo-prep-1 ✅ (#63, AppIcon drop-in deferred on Figma), savings-math-prominence ✅ (#64, Mike's identity-toggle drill rehearsal pending), sim-edge-case-fixes-v1 ✅ (#65), interstitial-parity-1 ✅ (PR pending), category-relevance-1 ✅ (PR pending). Next: AppIcon PNGs when Figma lands, prod FB seed (Mike), eBay-Tier-2 graduation call, snapshot-baseline re-record pass (sim-26.3 drift), F#1c follow-up (route Continue through portal redirect when active membership matches `winner.portal_source`), `cat-rel-1-L1`/`L2`/`L3`/`L4` follow-ups (Decodo Amazon brand-strip, Gemini UPC stricture, Hamilton-Beach digit-led pattern, post-resolve sanity check), 3h Vision, 3i receipts, 3k savings, 3l coupons, 3m hardening + `v0.3.0`. 3j folded into 3e
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

> Quick-ref index only. Full rationale + code pointers in `docs/CHANGELOG.md` Key Decisions Log + per-step entries.

### Phase 1 + 2 (quick-ref)
- Container auth VPC-only; `WALMART_ADAPTER={container,firecrawl,decodo_http}`; fd-3 stdout convention; `EXTRACT_TIMEOUT=180`
- Relevance: model-number hard gate + variant-token + ordinal + brand + 0.4 token overlap; UPCitemdb cross-val alongside Gemini (brand agreement picks winner)
- SSE via `asyncio.as_completed` + iOS byte splitter; batch fallback on error. Identity zero-LLM SQL join <150 ms, post-SSE. Card priority: rotating > user > static > base
- Billing: iOS RC SDK for UI, backend `users.subscription_tier` for rate limit; webhook idempotency SETNX 7d; tier cache 60 s fail-open
- Workers: LocalStack SQS (dev) / real AWS SQS (prod); boto3 via `asyncio.to_thread`; `_UNSET` sentinel for tri-state params
- `_classify_retailer_result` is the single classifier for batch + stream. Worker scripts MUST `from app import models`. Drift auto-detected in `conftest._ensure_schema`
- fb_marketplace requires Decodo residential w/ scoped routing; see `docs/SCRAPING_AGENT_ARCHITECTURE.md` §C.11

### Phase 3 (quick-ref)
- **External APIs.** eBay Browse (`EBAY_APP_ID`+`CERT_ID`, 2h TTL, filter DSL `|`); Best Buy Products API (`BESTBUY_API_KEY`); Decodo Scraper API for Amazon (`DECODO_SCRAPER_API_AUTH`); GDPR webhook = GET SHA-256 + POST 204
- **9 active scraped retailers** post-2026-04-18 (lowes + sams_club retired). `*_direct` rows stay `is_active=True` as identity-redirect targets
- **Search v2 cascade.** normalize → Redis → DB pg_trgm@0.3 → Tier 2 `gather(BBY, UPCitemdb)` → Tier 3 Gemini. Tiered merge strong/weak (`_STRONG_CONFIDENCE=0.55`), tiebreaks `DB>BBY>UPCitemdb>Gemini`. Parallel gather halved P50 (17→5s) and 404 tail (34→13s). `cascade_path` on response. `?query=` override on `/prices/{id}/stream`
- **Relevance pack (#62).** `_pick_best_listing` price-outlier <40% median on `{ebay,fb}` (min 4); FB soft model gate caps 0.5 when SKU absent; `[A-Z]\d{3,4}` pattern catches G-series; `_TIER2_NOISE_*` +accessor/thumbstick
- **M6 Recommendation (3e).** Deterministic. `gather`s Prices+Identity+Cards+Portals, <150 ms p95. `final = base − identity`; rebates on post-identity price. Brand-direct callout ≥15 % at `*_direct`. 15-min Redis cache w/ key `:c<sha1(cards)>:i<sha1(identity)>:p<sha1(portals)>:v5`. iOS hero gated on streamClosed+identityLoaded+cardsLoaded; failures → silent nil
- **Purchase Interstitial (3f).** `PurchaseInterstitialSheet` from hero CTA + row taps; activation ack session-scoped; per-retailer `estimated_savings`; `discount_programs.scope ∈ {product, membership_fee, shipping}` (0009)
- **Benefits Expansion.** +10 student-tech + Prime YA (`scope='membership_fee'`); `is_young_adult` (0010); `_dedup_best_per_retailer_scope` keys `(retailer_id, scope)`; `BRAND_ALIASES` fails closed on competing brand; `/resolve`→`/resolve-from-search` fallback on Gemini UPC hallucination
- **FB Marketplace location resolver (0011).** Numeric FB Page ID end-to-end; 3-tier Redis(24h)→PG→live. GCRA bucket w/ singleflight + subscribe-before-recheck. iOS `Stored.fbLocationId` is bigint-safe String; picker FSM idle→geocoding→resolving→resolved
- **fb-resolver-followups (#51, #52).** Dedicated `fb_location_resolve` bucket (5/min, no pro multiplier). DTO `resolution_path` collapses engines to `live`. Postfix-1: 3-way decision (VALIDATED > FALLBACK > REJECTED) rejects sub-region IDs when a city-norm canonical is available
- **experiment/tier2-ebay-search (#50).** 4 env flags default OFF. `SEARCH_TIER2_USE_EBAY` swaps UPCitemdb→Browse; `M2_EBAY_DROP_PARTIAL_LISTINGS` drops box-only/parts/charger-only on `ebay_browse_api`. Browse omits `gtin` even w/ EXTENDED — `SKIP_UPC` is de facto
- **Portal monetization (3g-A #53, 3g-B #54/#55).** 0012 `portal_configs` (display+signup-promo+alerting). 5-step decision tree: feature-flag → 24h staleness → MEMBER_DEEPLINK → SIGNUP_REFERRAL w/ FTC → GUIDED_ONLY. Sort `(rate desc, portal asc)`. Resend alerting: 3 consecutive empty → email, 24h throttle. iOS: winner-only `portal_ctas` on `StackedPath`; `PortalMembershipPreferences` `[String: Bool]`; interstitial ≤3 CTAs w/ FTC per-CTA on SIGNUP_REFERRAL. **Codable pitfall:** `.convertFromSnakeCase` → `portalCtas` (lowercase `as`). **ProfileView dual-branch pitfall:** grep BOTH `ScrollView` branches when adding a section
- **demo-prep-1 (#63).** Explicit states over silent-nil. `/recommend` 422 → `RecommendationState.insufficientData(reason:)`. FastAPI envelope decode fix in `APIClient.decodeErrorDetail` (lost ~6 months — unblocks #64 audit). `UnresolvedProductView` for `/resolve` 404 + `TabSelectionAction` env. `LOW_CONFIDENCE_THRESHOLD=0.70` 409 gate on `/resolve-from-search` (pre-Gemini, zero AI cost) + `/confirm` marks `user_confirmed`. `make demo-check`/`demo-warm` + first repo-root Makefile
- **savings-math-prominence (#64).** Hero invert: `Save $X` (`.barkainHero` 48pt) → `effectiveCost at retailer` → `why`. Shared `StackingReceiptView` + `StackingReceipt` value across hero + interstitial. `Money.format` no `.00`. Backend `error.message` re-toned in m1/m2/m6; `APIError.errorDescription` softened. `APIClientErrorEnvelopeTests` (4-case envelope). `make demo-check --no-cache --remote-containers=ec2` (`?force_refresh=true` + EC2 `/health` pre-flight). `make verify-counts` pins totals
- **sim-edge-case-fixes-v1 (#65).** Pattern-UPC reject `^(\d)\1{11,12}$` pre-Gemini in `service.py:resolve` (no hallucination, no PG persistence). `RequestValidationError` handler in `app/main.py` rewraps Pydantic 422s into canonical `{detail:{error:{code:"VALIDATION_ERROR",message,details}}}` — iOS surfaces backend messages, not "Validation failed". iOS: `.searchable` sync setter w/ spurious-empty guard mirrored (Clear-text race; retains nav-bar-teardown protection); recents success-only + 200-char clamp. Manual UPC: `.numberPad` + onChange digit-filter; 12/13-digit client guard surfaces inline red error w/ sheet-stays-open. Test fixtures bumped 6 pattern UPCs by trailing digit (semantics-preserving). F#7 dedupe deferred (`_merge()` already correct). 20 iOS snapshot baselines drift on iOS 26.3 sim independent of edits; record-mode UX cleanup is a Pack candidate
- **interstitial-parity-1 (PR pending).** Hero/interstitial money-math parity restored. **F#1**: `PurchaseInterstitialSheet.swift` body restructured — `summaryBlock`+`directPurchaseBlock` collapsed into single `priceBreakdownBlock` that renders `StackingReceiptView` whenever `receipt.hasAnyDiscount` (card OR identity OR portal), independent of `hasCardGuidance`. Pre-fix the receipt was silently dropped for users without a card portfolio even when the hero promised portal/identity savings. **F#1b**: M6 `service.py:get_recommendation` now filters `portal_by_retailer` by `active_memberships = {k for k,v in memberships.items() if v}` — the hero only stacks portal cashback the user has activated, because `continueToRetailer` doesn't pass `portal_event_type`/`portal_source` (the rebate would never post). The signup-referral upsell still surfaces independently via `portal_ctas` (resolve_cta_list emits SIGNUP_REFERRAL/GUIDED_ONLY rows for inactive memberships). **F#2**: `scripts/demo_check.py` evergreen UPC `190198451736` (Apple iPhone 8, docstring claimed "AirPods") → `194252056639` (MacBook Air M1, broadest catalog coverage in 2026-04-25 sweep). Threshold `7/9`→`5/9` calibrated against catalog reality (Home Depot doesn't stock laptops, Back Market only carries refurb). +Makefile help text. Test fixture `partial = ACTIVE_RETAILERS[:5]` → `[:4]` to remain "below 5-threshold". **F#1c carry-forward**: Continue button still uses direct-retailer affiliate URL even when winner has portal_source — analytics gap (portal-driven conversions miss attribution), not user-facing breakage because portal browser extensions catch eBay/Amazon visits. Fix path: when `winner.portal_source` matches an active membership, route Continue through the matching `portal_cta.ctaUrl`. Demo verdict from `Sim_Pre_Demo_Comprehensive_Report_v1.md` flipped HOLD→GO
- **category-relevance-1 (PR pending).** 5 backend fixes from 15-SKU obscure-SKU sweep across the 3 catalog categories (Electronics/Appliances/Home&Tools — see `Barkain Prompts/Category_UPC_Efficacy_Report_v1.md`). Demo-blocking hallucinations fixed: Breville BES870XL Barista Express showed `$18.95` hero on FB drip-tray listings (real retail $499); Weber Q1200 grill showed `$15.99` hero on Amazon Uniflasy "for Weber" replacement burner tube (real retail $200); Cuisinart food processor returned 0/9 because UPCitemdb stores brand as parent company "Conair Corporation"; Toro Recycler search returned only Greenworks/WORX rows (zero Toro). **#1 FB strict overlap floor** (`m2_prices/service.py:_score_listing_relevance`): when `model_missing=True` on FB Marketplace, require raw token overlap ≥0.6 (was implicit 0.4 baseline) before applying the visible 0.5 cap. New constant `_FB_SOFT_GATE_MIN_OVERLAP=0.6`. Pre-fix `min(score, 0.5)` masked the difference between drip-tray (overlap 0.5) and legit (overlap 0.83) listings — both scored 0.5 and passed the 0.4 threshold. **#1b appliance/tool model regex**: added `\b[A-Z]{2,4}\d{3,5}[A-Z]{1,4}\d{0,2}\b` to `_MODEL_PATTERNS` (catches BES870XL/DCD777C2/JES1072SHSS/many cordless-tool + kitchen-appliance shapes that the 7 prior patterns missed — without identifiers `model_missing` never fires, so the soft gate doesn't trigger). **#1c single-letter normalize**: `_extract_model_identifiers` runs `\b([A-Z])\s+(\d{3,4})\b` → `\1\2` pre-pass to collapse "Q 1200" → "Q1200" (Gemini stores Weber's name space-separated; without this Q1200 isn't extracted as a model). Localized to extraction so prose collisions stay independent. **#2 R3 brand-bleed gate** (`m1_product/search_service.py:_is_tier2_noise`): the first meaningful, alpha-only query token (length ≥3) must appear in the row haystack (title+brand+model). Catches Toro→Greenworks brand-bleed without a maintained brand list — leverages the universal observation that the leading non-stopword query token is almost always a brand. Cross-brand subsidiary cases (Anker→Soundcore via "by Anker" in the title) still pass because the check is haystack substring, not brand-field equality. `BRAND_ALIASES` lives in m5_identity (governs identity-discount eligibility) and was never consulted at Tier-2 search time pre-fix. **#3 strict-spec gate**: new `_query_strict_specs` extracts voltage tokens (`40v`/`80v`/`240v` via `^\d{2,3}v$`) and 4+ digit pure-numeric model numbers (`5200`/`6400` via `^\d{4,}$`) from the query — these must match verbatim in the row haystack. Catches Vitamix 5200→Explorian E310 (5200≠64068) and Greenworks 40V→80V drift. iPhone 16 / Galaxy S24 stay safe (numeric tokens are 2 digits, below the 4+ floor). **#4 Rule 3 brand fallback to product.name**: when `product.brand` (e.g. "Conair Corporation") doesn't appear in the listing title, fall back to the leading non-stopword word of `product.name` (e.g. "Cuisinart"). Tracks `matched_brand` for downstream rules. UPCitemdb stores parent companies — Conair for Cuisinart, Whirlpool for KitchenAid, etc. Pre-fix every Cuisinart listing was rejected at Rule 3 → 0/9 success. **#4b Rule 3b "for-template" reject**: listings whose title contains `\b(?:for|fits|compatible\s+with)\s+{matched_brand}\b` are hard-rejected — Uniflasy "Grill Burner Tube for Weber Q1200", OEM "compatible with Cuisinart" patterns. Genuine Weber listings never say "for Weber" (sellers don't write the brand twice for their own product). The simple regex catches both alphabetic-led ("Uniflasy 60040…") AND digit-led ("304 Stainless Steel 60040…") third-party titles, and triggers regardless of leading-token shape. Final harness: Breville $18.95→$299.99, Weber $15.99→$239.99, Cuisinart 0/9→2/9, Toro brand-bleed gone, GE/Bissell/HB hallucinations all gone. Coverage dropped (2.5/9 avg pre-fix → 1.6/9 avg post-fix across the 15 SKUs), but every retailer lost was emitting a wrong-product price — keeping them was a demo liability, not an asset. Carry-forward as Known Issues: `cat-rel-1-L1` (Decodo Amazon adapter strips brand from titles → real Weber listings now `no_match` post-fix; net win for demo, separate adapter fix), `cat-rel-1-L2` (3 SKUs unresolvable on Gemini-only no-UPC path — ASUS CX1, Ryobi P1817, Husqvarna 130BT), `cat-rel-1-L3` (Hamilton Beach 49981A digit-leading model code still not extracted — risky to add digit-led pattern), `cat-rel-1-L4` (UPCitemdb returns wrong canonical product for some UPCs — Vitamix 5200→E310, Greenworks 40V→80V, Toro→Greenworks; upstream data quality). Backend 617→630 (+13 tests across `test_m2_prices.py` and `test_product_search.py`)
