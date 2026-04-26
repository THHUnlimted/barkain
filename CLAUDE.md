# CLAUDE.md — Barkain

> **Purpose:** Root orientation for AI coding agents. This file alone should let a new session understand the project, find anything, and follow conventions.
> **Last updated:** 2026-04-25 (v5.34 — inflight-cache-1 + L1 + L2: closes the backend transaction-visibility blocker that made the original PR-3 provisional /recommend silently no-op. SSE `stream_prices` runs as one per-request transaction; in-flight `_upsert_price` writes are invisible to other requests under READ COMMITTED until end-of-stream commit, so M6's parallel `/recommend` would always see zero fresh prices and re-dispatch all 9 scrapers. **Live Redis in-flight cache** — new `prices:inflight:{pid}[:scope]` Redis hash with field-per-retailer JSON payloads + 120s TTL. `stream_prices` `_write_inflight()` after every `_upsert_price` (BEFORE the SSE `yield`); `_clear_inflight()` after `_cache_to_redis` at stream end. `get_prices` Step 2.5 between Redis-canonical and DB checks calls `_check_inflight()`, returns partial dict if non-None — never re-dispatches. **Critical edge case: distinguishes "no key" (None → fall through to DB+dispatch) from "empty key" (empty-prices dict → DO NOT dispatch, stream just opened)** via `EXISTS` after `HGETALL`. Without it the brief window between `EXPIRE` and first `HSET` of a fresh stream would let a parallel `get_prices` race in and dispatch a duplicate batch. **L1 cache-contamination guard (folded in)** — `_check_inflight` annotates the returned dict with an underscore-prefixed `_inflight: True` marker (Pydantic ignores on serialize); M6's `get_recommendation` checks `prices_payload.get("_inflight")` and skips `_write_cache` when True, logging `recommendation_built_from_inflight` for observability. Without this guard, a provisional rec built from a 5/9 snapshot would land in M6's 15-min cache and serve the same user for up to 15 min after the stream completed, masking the canonical 9/9 result. Originally documented as needing a Pydantic schema bump + iOS coordination — that was wrong; internal dict marker is purely backend. **L2 query_override scope plumbing (also folded in)** — `get_prices` now accepts `query_override: str | None = None` and threads it through `_check_redis`, `_check_inflight`, the dispatch query + product_name hint, and `_cache_to_redis` write-back; skips DB cache when set (mirrors `stream_prices`'s same guard, since the prices table has no scope tag). `RecommendationService.get_recommendation` and `RecommendationRequest` schema gain matching `query_override` parameter; M6's cache key conditionally appends `:q<sha1>` when set so the optimistic-tap rec and the bare-flow rec for the same product live in disjoint cache spaces. **No M6 cache version bump** — the segment is only inserted when `query_override` is set, so existing `…:v5` no-override entries stay reachable. With L2, the optimistic-search-tap flow now benefits from inflight too; pre-fix, the SSE wrote a SCOPED bucket but M6 read the bare bucket (empty) and double-dispatched. **Soft-fail Redis throughout** — log warning on exception, stream continues; canonical end-of-stream cache is still authoritative. **Picked over commit-per-retailer** (would muddy partial-failure semantics) and inline-prices-in-/recommend (bloats request body + needs M6 `_gather_inputs` rewrite). Backend 666→683 (+17 tests: 10 inflight cache + 2 M6 cache-contamination + 3 M6 query_override + 2 get_prices query_override threading). **Unblocks** the stashed iOS provisional /recommend code (`git stash list | grep "PR-3 provisional"`) — once paired iOS lands, the user gets full hero + receipt 60-90s before stream finishes on slow days, with no stale cache pollution and full coverage for both barcode/SKU-search AND optimistic-search-tap flows.)
> **Previous (v5.33):** 2026-04-25 (apple-variant-disambiguation: targeted fix for an M4 iPad query surfacing an M3 iPad listing on eBay. **Rule 2c (Apple chip equality, disagreement-only)** — `m2_prices/service.py:_score_listing_relevance` now extracts `M[1-4](\s+(Pro|Max|Ultra))?` tokens from product (`name + gemini_model + upcitemdb.model`) and listing title; rejects when both sides emit a chip and they disagree. Allows when either side omits — used eBay/FB sellers routinely list "MacBook Air 2022 8GB/256GB" with no chip name, so a require-presence gate would zero-out genuine coverage. **Rule 2d (Apple display-size equality, disagreement-only)** — same shape over 11/13/14/15/16-inch tokens. Floored at 11 / capped at 16 to skip 4-inch knives and 27-inch monitors. **Telemetry on every rejection** — silent zero-results from Rule 2c/2d are invisible to users (looks identical to "no retailer had this product"), so logger emits a structured line `apple_variant_gate_rejected rule=2{c|d} product_chips=[...] listing_chips=[...] retailer_id=...` for every fired rejection. Watch logs for clusters where ALL listings for a product are rejected — that's the signal that Gemini stored the wrong chip on the canonical (the inverse of the bug). **Deliberately cut from scope:** generation ordinal gate (sellers don't write "9th gen" — would zero-out used iPad coverage); negative-token matching (M3 base must NOT match M3 Pro — query intent ambiguous, no precedent); chip/size NOT added to `_query_strict_specs` (would over-reject correctly-resolved canonicals when Gemini's name omits the chip). Backend 652→666 (+14 tests). Sweep plan documented at `Barkain Prompts/Apple_Variant_Disambiguation_Sweep_v1.md` for any future expansion.)
> **Previous:** 2026-04-25 (v5.32 — cat-rel-1-followups: clears all 4 carry-forward Known Issues from category-relevance-1 (#67). **L4 post-resolve sanity check** — `m1_product/service.py:resolve_from_search` runs `_resolved_matches_query` after `resolve()`; rejects when query strict-specs (voltage / 4+digit numeric, reused from `search_service._query_strict_specs`) or query brand are absent from the resolved haystack. Catches Vitamix 5200→E310, Greenworks 40V→80V, Toro→Greenworks. Cached pre-fix entries self-invalidate on next access. **L1 Decodo Amazon brand recovery** — `m2_prices/adapters/amazon_scraper_api.py:_extract_brand_from_url` pulls the brand from URL slugs like `/Weber-51040001-Q1200-…/dp/…` when `manufacturer` is empty; prepends to title so Rule 3 brand check passes. Verified live against EC2 Decodo response (5/5 Breville listings re-prefixed). **L2 Gemini UPC log enhancement** — service now logs Gemini's `reasoning` when null on the retry pass. **Rejected** the original "tighten prompt to force UPCs for Tools brands" fix path after a live Gemini probe revealed Ryobi P1817 already returns a UPC, ASUS Chromebook CX1 is a multi-variant line (Gemini correctly refuses), and Husqvarna 130BT isn't stocked at major retailers (Gemini correctly refuses). Forcing UPCs would re-introduce the hallucinations cat-rel-1 just fixed; real fix is iOS UX work to surface the reasoning. **L3 digit-led model regex** — added `\b\d{5}[A-Z]{0,2}\b` with negative lookahead skipping BTU/mAh/Wh/lbs/Hz/MB/GB/etc. Catches Hamilton Beach 49981A/49963A/49988, Bissell 15999, Greenworks 24252; verified on 12 fixtures including the previously-flagged-risky 12000 BTU / 10000 mAh / 1080p / 4090Ti collisions. Backend 630→652 (+22 tests).)

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
| category-relevance-1 | 5 fixes from 15-SKU obscure-SKU sweep across Electronics/Appliances/Home&Tools (`Category_UPC_Efficacy_Report_v1.md`). #1 FB strict overlap floor 0.4→0.6 + `_FB_SOFT_GATE_MIN_OVERLAP` constant. #1b new `_MODEL_PATTERNS` regex `[A-Z]{2,4}\d{3,5}[A-Z]{1,4}\d{0,2}` (BES870XL/DCD777C2/JES1072SHSS class). #1c `_extract_model_identifiers` pre-pass collapses `Q 1200`→`Q1200`. #2 brand-bleed gate: leading meaningful query token must appear in haystack (Toro→Greenworks rejection). #3 `_query_strict_specs` voltage (40v/80v) + 4+digit pure-numeric (5200) verbatim match. #4 Rule 3 brand fallback to product.name first word (Conair Corp→Cuisinart). #4b Rule 3b `for {brand}`/`compatible with {brand}` template hard-reject (Uniflasy "for Weber Q1200" $15.99 leak). Demo headlines: Breville $18.95→$299.99, Weber $15.99→$239.99, Cuisinart 0/9→2/9 | +13 | — | #67 |
| cat-rel-1-followups | Clears all 4 cat-rel-1 carry-forwards. **L4** `m1_product/service.py:_resolved_matches_query` post-resolve sanity gate (brand + voltage/4+digit specs from query must echo in resolved haystack); cached pre-fix entries self-invalidate. Catches Vitamix 5200→E310, Greenworks 40V→80V, Toro→Greenworks. **L1** `amazon_scraper_api.py:_extract_brand_from_url` recovers brand from URL slug (`/Weber-…/dp/…`) when Decodo's `manufacturer` is empty; live-verified on EC2 Decodo response. **L2** logs Gemini reasoning on retry-null; the originally-proposed prompt-tightening fix path was REJECTED after live probe (Ryobi P1817 already returns UPC; ASUS CX1 / Husqvarna 130BT correctly refused — forcing UPCs would re-introduce hallucinations cat-rel-1 just fixed). **L3** added `\d{5}[A-Z]{0,2}` digit-led pattern with unit-suffix lookahead (BTU/mAh/Hz/etc.); 12-fixture corpus catches Hamilton Beach 49981A and friends without 12000 BTU / 1080p / 4090Ti collisions | +22 | — | TBD |
| apple-variant-disambiguation | User-reported demo bug: M4 iPad query surfaced M3 iPad listing on eBay. **Rule 2c** (Apple chip equality, disagreement-only) extracts `M[1-4](\s+(Pro\|Max\|Ultra))?` from product (`name + gemini_model + upcitemdb.model`) + listing title; rejects when both sides emit a chip and they disagree. **Rule 2d** (display-size equality, disagreement-only) same shape over 11/13/14/15/16-inch tokens. Both rules emit `apple_variant_gate_rejected rule=2{c\|d} ...` log lines on every rejection so silent zero-results are observable. Deliberately cut: ordinal gate (sellers don't write "9th gen"), negative-token matching (M3 base vs M3 Pro intent ambiguous), search-time gate via `_query_strict_specs` (would over-reject correct canonicals when Gemini name omits chip) | +14 | — | TBD |
| inflight-cache-1 (+ L1 + L2) | Closes the backend transaction-visibility blocker for PR-3 provisional /recommend. SSE `stream_prices` runs as one per-request transaction; in-flight `_upsert_price` writes invisible under READ COMMITTED until end-of-stream commit. New `prices:inflight:{pid}[:scope]` Redis hash (field-per-retailer JSON, 120s TTL) — `stream_prices` writes after each `_upsert_price` BEFORE the `yield`, clears at end after `_cache_to_redis`. `get_prices` Step 2.5 reads inflight between canonical Redis + DB checks, returns partial dict, never re-dispatches. `EXISTS`-after-`HGETALL` distinguishes missing-key (fall through to dispatch) from empty-key (stream just opened, do NOT dispatch). Soft-fails on Redis errors. Scope mirrors `_cache_key` so SKU/bare-name buckets don't cross. Picked over commit-per-retailer + inline-in-/recommend. **L1 cache-contamination guard folded in:** `_check_inflight` returned dict carries `_inflight: True`; M6 skips `_write_cache` when set so a provisional rec built from partial data doesn't pollute M6's 15-min cache. **L2 query_override threading folded in:** `get_prices` accepts `query_override`, threads to all cache layers + dispatch query, skips DB cache (mirrors `stream_prices`); `RecommendationService.get_recommendation` + `RecommendationRequest` schema accept it; M6 cache key conditionally adds `:q<sha1>` so optimistic-tap recs are isolated from bare-flow recs. No cache version bump (segment only inserted when set). Unblocks stashed iOS provisional code for BOTH barcode/SKU AND optimistic-tap flows (60-90s win on slow days when paired) | +17 | — | #73 |

**Test totals:** 683 backend + 203 iOS unit + 6 iOS UI (with experiment flags off — see L-Experiment-flags-default-off). `ruff check` clean. `xcodebuild` clean.

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
| cat-rel-1-L2-ux | LOW | L2 prompt path was rejected; the actionable carry-forward is iOS UX. When `/products/resolve-from-search` returns 404 because Gemini correctly refused (multi-variant line / not stocked online), iOS could surface Gemini's reasoning rather than a generic "couldn't find" — requires plumbing reasoning into the error envelope (`UPCNotFoundForDescriptionError` doesn't carry it today) and a dedicated iOS state. Defer to iOS sprint | Phase 3 |

---

## What's Next

1. **Phase 2 CLOSED** — `v0.2.0` tagged (2026-04-16). Outstanding: revoke leaked PAT `gho_UUsp9ML7…` in GitHub UI (SP-L1-b, Mike).
2. **Phase 3:** 3a–3d-noise-filter ✅ (#22–#36), ui-refresh-v1/v2/v2-fix ✅ (#37–#40), 3e (#41), 3f (+hotfix) ✅ (#42, #44), Benefits Expansion ✅ (#45–#47), FB Marketplace location + resolver ✅ (#48, #49), experiment/tier2-ebay-search ✅ (#50, opt-in), fb-resolver-followups + postfix-1 ✅ (#51, #52), 3g-A + 3g-B + 3g-B-fix-1 ✅ (#53, #54, #55), search-resolve-perf-1 ✅ (#61), search-relevance-1 ✅ (#62), demo-prep-1 ✅ (#63, AppIcon drop-in deferred on Figma), savings-math-prominence ✅ (#64, Mike's identity-toggle drill rehearsal pending), sim-edge-case-fixes-v1 ✅ (#65), interstitial-parity-1 ✅ (#66), category-relevance-1 ✅ (#67), cat-rel-1-followups ✅ (PR pending), apple-variant-disambiguation ✅ (PR pending, stacked on cat-rel-1-followups), inflight-cache-1 ✅ (#73 — backend-only; unblocks the stashed iOS provisional `/recommend` code). Next: **resurrect the stashed iOS provisional /recommend code** (`git stash list | grep "PR-3 provisional"`, then `git stash pop` and adapt — the backend now serves partial inflight data so the provisional fire at 5/9 retailers will return real prices), AppIcon PNGs when Figma lands, prod FB seed (Mike), eBay-Tier-2 graduation call, snapshot-baseline re-record pass (sim-26.3 drift), F#1c follow-up (route Continue through portal redirect when active membership matches `winner.portal_source`), `cat-rel-1-L2-ux` (surface Gemini reasoning to iOS for unverifiable-SKU 404s), watch `apple_variant_gate_rejected` log clusters for silent-zero-results pattern (signal that user-query plumbing into M2 is needed), 3h Vision, 3i receipts, 3k savings, 3l coupons, 3m hardening + `v0.3.0`. 3j folded into 3e
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
- **category-relevance-1 (#67).** 5 backend fixes from 15-SKU obscure-SKU sweep across the 3 catalog categories (Electronics/Appliances/Home&Tools — see `Barkain Prompts/Category_UPC_Efficacy_Report_v1.md`). Demo-blocking hallucinations fixed: Breville BES870XL Barista Express showed `$18.95` hero on FB drip-tray listings (real retail $499); Weber Q1200 grill showed `$15.99` hero on Amazon Uniflasy "for Weber" replacement burner tube (real retail $200); Cuisinart food processor returned 0/9 because UPCitemdb stores brand as parent company "Conair Corporation"; Toro Recycler search returned only Greenworks/WORX rows (zero Toro). **#1 FB strict overlap floor** (`m2_prices/service.py:_score_listing_relevance`): when `model_missing=True` on FB Marketplace, require raw token overlap ≥0.6 (was implicit 0.4 baseline) before applying the visible 0.5 cap. New constant `_FB_SOFT_GATE_MIN_OVERLAP=0.6`. Pre-fix `min(score, 0.5)` masked the difference between drip-tray (overlap 0.5) and legit (overlap 0.83) listings — both scored 0.5 and passed the 0.4 threshold. **#1b appliance/tool model regex**: added `\b[A-Z]{2,4}\d{3,5}[A-Z]{1,4}\d{0,2}\b` to `_MODEL_PATTERNS` (catches BES870XL/DCD777C2/JES1072SHSS/many cordless-tool + kitchen-appliance shapes that the 7 prior patterns missed — without identifiers `model_missing` never fires, so the soft gate doesn't trigger). **#1c single-letter normalize**: `_extract_model_identifiers` runs `\b([A-Z])\s+(\d{3,4})\b` → `\1\2` pre-pass to collapse "Q 1200" → "Q1200" (Gemini stores Weber's name space-separated; without this Q1200 isn't extracted as a model). Localized to extraction so prose collisions stay independent. **#2 R3 brand-bleed gate** (`m1_product/search_service.py:_is_tier2_noise`): the first meaningful, alpha-only query token (length ≥3) must appear in the row haystack (title+brand+model). Catches Toro→Greenworks brand-bleed without a maintained brand list — leverages the universal observation that the leading non-stopword query token is almost always a brand. Cross-brand subsidiary cases (Anker→Soundcore via "by Anker" in the title) still pass because the check is haystack substring, not brand-field equality. `BRAND_ALIASES` lives in m5_identity (governs identity-discount eligibility) and was never consulted at Tier-2 search time pre-fix. **#3 strict-spec gate**: new `_query_strict_specs` extracts voltage tokens (`40v`/`80v`/`240v` via `^\d{2,3}v$`) and 4+ digit pure-numeric model numbers (`5200`/`6400` via `^\d{4,}$`) from the query — these must match verbatim in the row haystack. Catches Vitamix 5200→Explorian E310 (5200≠64068) and Greenworks 40V→80V drift. iPhone 16 / Galaxy S24 stay safe (numeric tokens are 2 digits, below the 4+ floor). **#4 Rule 3 brand fallback to product.name**: when `product.brand` (e.g. "Conair Corporation") doesn't appear in the listing title, fall back to the leading non-stopword word of `product.name` (e.g. "Cuisinart"). Tracks `matched_brand` for downstream rules. UPCitemdb stores parent companies — Conair for Cuisinart, Whirlpool for KitchenAid, etc. Pre-fix every Cuisinart listing was rejected at Rule 3 → 0/9 success. **#4b Rule 3b "for-template" reject**: listings whose title contains `\b(?:for|fits|compatible\s+with)\s+{matched_brand}\b` are hard-rejected — Uniflasy "Grill Burner Tube for Weber Q1200", OEM "compatible with Cuisinart" patterns. Genuine Weber listings never say "for Weber" (sellers don't write the brand twice for their own product). The simple regex catches both alphabetic-led ("Uniflasy 60040…") AND digit-led ("304 Stainless Steel 60040…") third-party titles, and triggers regardless of leading-token shape. Final harness: Breville $18.95→$299.99, Weber $15.99→$239.99, Cuisinart 0/9→2/9, Toro brand-bleed gone, GE/Bissell/HB hallucinations all gone. Coverage dropped (2.5/9 avg pre-fix → 1.6/9 avg post-fix across the 15 SKUs), but every retailer lost was emitting a wrong-product price — keeping them was a demo liability, not an asset. Carry-forward as Known Issues: `cat-rel-1-L1` (Decodo Amazon adapter strips brand from titles → real Weber listings now `no_match` post-fix; net win for demo, separate adapter fix), `cat-rel-1-L2` (3 SKUs unresolvable on Gemini-only no-UPC path — ASUS CX1, Ryobi P1817, Husqvarna 130BT), `cat-rel-1-L3` (Hamilton Beach 49981A digit-leading model code still not extracted — risky to add digit-led pattern), `cat-rel-1-L4` (UPCitemdb returns wrong canonical product for some UPCs — Vitamix 5200→E310, Greenworks 40V→80V, Toro→Greenworks; upstream data quality). Backend 617→630 (+13 tests across `test_m2_prices.py` and `test_product_search.py`)
- **cat-rel-1-followups (PR pending).** Clears all 4 cat-rel-1 carry-forward Known Issues. **L4 post-resolve sanity check** (`m1_product/service.py:_resolved_matches_query`): after `resolve(upc)` returns a Product, run a deterministic gate against the user's query — query brand (or, when absent, leading meaningful alpha token of the query) must appear in the resolved name+brand haystack, AND every voltage / 4+digit pure-numeric token from the query must echo verbatim. Reuses `search_service._query_strict_specs` so search-time noise filtering and resolve-time mismatch detection use the same definition of "must match." Applied in BOTH the fresh-resolve path and the cache-hit path; on mismatch we delete the bad cache entry and raise `UPCNotFoundForDescriptionError`. The Product row stays in PG (it IS a real product, just wrong for *this* query — a future scan of its actual barcode benefits). Catches the 3 demo cases: Vitamix 5200 query → resolved E310 rejected (5200 missing); Greenworks 40V query → resolved 80V rejected (40v missing); Toro Recycler query → resolved Greenworks rejected (toro missing from haystack). Cached pre-fix Redis entries (24h TTL) self-invalidate on next access. Fixture `test_resolve_from_search_devupc_cache_short_circuits_gemini` had bogus product data (`name="Cached Product" brand="Steam"`) that the new gate correctly rejected — realigned to realistic Valve data; test intent (cache short-circuits Gemini) preserved. **L1 Decodo Amazon brand recovery** (`m2_prices/adapters/amazon_scraper_api.py:_extract_brand_from_url`): Decodo's Amazon parser routinely returns titles with brand stripped ("Q1200 Liquid Propane Grill" instead of "Weber Q1200…") AND ships an empty `manufacturer` field, but the canonical product URL slug preserves it ("/Weber-51040001-Q1200-…/dp/B010ILB4KU"). New helper extracts the leading slug segment when it's alpha-only, 3-25 chars, and not in `_URL_BRAND_DENYLIST = {dp, gp, ref, stores, amazon, exec, the, and}` (filters direct `/dp/B0...` URLs). Adapter prepends the recovered brand to the title only when (1) `manufacturer` is empty AND (2) title doesn't already contain it (no "Weber Weber Q1200" duplication on listings the parser handled correctly). Live-verified: pulled real Decodo response from EC2 for query `breville barista express`, ran `_map_organic_to_listing` against each organic item — 5/5 listings prefixed correctly ("Barista Express Espresso Machine BES870XL…" → "Breville Barista Express…"). Same on Weber Q1200 sample. Restores Rule 3 brand-check passes on legitimate Amazon listings post-cat-rel-1. **L2 Gemini UPC log enhancement + prompt-tightening REJECTED.** Original CLAUDE.md fix path was "tighten ai/prompts/upc_lookup.py to require UPC for low-volume Tools brands." Live Gemini probe on the 3 known-fail SKUs (`/tmp` script using `gemini_generate_json` directly) revealed: Ryobi P1817 returns UPC `033287186235` on pass 1 (issue stale); ASUS Chromebook CX1 correctly returns null with reason "product line with numerous sub-variants" (this is correct — CX1 is a line, not a single SKU); Husqvarna 130BT correctly returns null with reason "Major US retailers do not currently stock the Husqvarna 130BT" (this is honest — sold via dealer network). Forcing a UPC here would re-introduce the demo-killer hallucinations cat-rel-1 just fixed (Gemini guesses → wrong UPC → wrong canonical → wrong prices). Prompt path REJECTED. Minimum useful change shipped: `_lookup_upc_from_description` now logs Gemini's `reasoning` (truncated to 200 chars) on the retry-null log line, so future debugging of obscure-SKU resolution failures has the model's stated rationale visible. Real fix is iOS UX work (surface the reasoning to the user) — tracked as `cat-rel-1-L2-ux`. **L3 digit-led model regex** (`m2_prices/service.py:_MODEL_PATTERNS`): added `\b\d{5}[A-Z]{0,2}\b(?!\s*(?:BTU|mAh|Wh|ml|cc|ft|sq|lbs?|oz|kg|RPM|MHz|GHz|Hz|MB|GB|TB|fps))` (case-insensitive lookahead). Catches Hamilton Beach 49981A/49963A/49988, Bissell 15999, Greenworks 24252, and similar catalog-numbered home-goods SKUs that all 8 prior patterns missed (every one of them required a leading letter prefix). The CLAUDE.md note flagged this pattern as risky pre-fix — the unit-suffix lookahead resolves the year/capacity false-positive concern: 12000 BTU air conditioner / 10000 mAh power bank / 5000 lbs trailer all skipped. Also passes 1080p (4 digits, below 5-digit floor), 4090Ti (4 digits), 256GB (3 digits), Series 10 (2 digits). 12-fixture corpus shipped in `test_extract_model_identifiers_catches_digit_led_appliance_sku` + `test_extract_model_identifiers_skips_capacity_units` + `test_extract_model_identifiers_does_not_collide_with_capacity_specs`. Backend 630→652 (+22 tests: 10 L4 across `test_product_resolve_from_search.py`, 8 L1 across `test_amazon_scraper_api.py`, 1 L2 logging assertion, 3 L3 across `test_m2_prices.py`). Honest tradeoffs: L1 end-to-end (Weber Q1200 Amazon row passes Rule 3 post-deploy) requires EC2 deploy to verify in-stream; adapter-level + live-Decodo-sample is the strongest local proof. L3's negative-lookahead corpus is closed (12 fixtures); blind spots possible for shapes outside the corpus (e.g. 5-digit ZIP codes in obscure listings) but not observed.
- **inflight-cache-1 (#73).** Closes the backend transaction-visibility blocker that made the original PR-3 provisional `/recommend` silently no-op. Root cause: SSE `stream_prices` runs as one per-request transaction (`app/dependencies.py:21-25` — single `await session.commit()` at end of `get_db()`); in-flight `_upsert_price` writes are invisible to other requests under READ COMMITTED until commit at end-of-stream. M6's `/recommend` fired while iOS was still streaming would call `PriceAggregationService.get_prices` → canonical Redis miss → DB miss → re-dispatch all 9 scrapers in parallel with the live stream, doubling backend work and never delivering fresher data than the stream was about to commit. **Live Redis in-flight cache** (`m2_prices/service.py`): new `prices:inflight:{pid}[:scope]` Redis hash with field-per-retailer JSON payload + 120s TTL (covers Best Buy ~91s p95 + buffer; auto-evicts crashed streams). Four helpers: `_inflight_key()` mirrors `_cache_key`'s scoping `(product_id, query_override?, fb_location_id?, fb_radius_miles?)`; `_write_inflight()` `pipeline().hset(key, field, val).expire(key, TTL).execute()`, soft-fails Redis errors with logger.warning; `_check_inflight()` `HGETALL`s + parses + reconstructs partial `PriceComparison`-shaped dict (`prices` sorted ascending, `retailer_results` ordered success/no_match/unavailable, computed counts, `cached=False`, `_inflight=True` marker); `_clear_inflight()` deletes on canonical-cache write. **L1 cache-contamination guard (folded into same PR after initial design proved over-cautious).** Initial CLAUDE.md note claimed L1 needed a Pydantic schema bump + iOS coordination — that was wrong. The marker `_inflight: True` lives inside the prices payload dict (which Pydantic doesn't validate; M2's wire schema declares its known fields and ignores extras). M6's `get_recommendation` reads `prices_payload.get("_inflight")` AFTER building the rec; when True it logs `recommendation_built_from_inflight user=… product=… succeeded=… skipping cache write` and skips the `_write_cache(...)` call. Pydantic Recommendation schema unchanged. iOS unchanged. Without the guard, a provisional rec built from a 5/9 inflight snapshot would land in M6's 15-min cache (`recommend:user:{u}:product:{p}:c{cards}:i{identity}:p{portals}:v5`) and serve the same user even after the stream completed and the canonical 9/9 result was available — the iOS stash already passes `force_refresh=true` on the FINAL call to defeat this, but a re-scan within 15 min before the final fired would still see the stale provisional. Now bulletproof regardless of iOS retry behavior. **Critical edge case — distinguishes "no key" from "empty key"**: `_check_inflight` calls `EXISTS` after empty `HGETALL` so it can return `None` (no stream in flight → caller falls through to DB+dispatch) vs an empty-prices dict (stream just opened, no completions yet → caller MUST NOT dispatch a parallel batch). Without this distinction, the brief window between `EXPIRE` and the first `HSET` of a fresh stream would let a parallel `get_prices` race in and dispatch a duplicate batch. **Wire-up**: `stream_prices` for-await loop calls `_write_inflight()` after `_upsert_price` and BEFORE the `yield`, so by the time iOS sees a `retailer_result` event the inflight bucket already has that retailer's payload — the contract a parallel `get_prices` depends on. After `_cache_to_redis` at stream end, `_clear_inflight()` deletes the bucket. `get_prices` adds a Step 2.5 between canonical Redis check and DB cache check: when `_check_inflight` returns non-None, return it directly (whether `prices` is empty or partial); never write inflight to canonical (partial result must not masquerade as authoritative for 6h). All inflight checks gated on `if not force_refresh:` so debug-flow re-runs with `force_refresh=True` correctly bypass. **Scope decision** — bucket scoped by `(product_id, query_override, fb_location_id, fb_radius_miles)`. M6's `get_prices` doesn't pass `query_override` today, so it reads the bare-scope bucket — which is what the barcode + SKU-search flows write to. Generic-search-tap (`query_override` set, e.g. when iOS's `experiment.optimisticSearchTap` taps a `.generic` row and `OptimisticPriceVM` passes `originalResult.deviceName` as the override) writes a SCOPED bucket M6 won't see. The win is SKU-flow-only by design — most demo flows are barcode + SKU-resolved-search; only the optimistic-tap-on-generic-row path doesn't benefit. Piping `query_override` through M6 + `/recommend` is the deeper fix; deferred because the experiment defaults OFF and SKU-flow is the demo-relevant path. **Picked over commit-per-retailer** (would muddy partial-failure semantics — a crashed stream would leave half the prices persisted, vs today's clean rollback) and **inline-prices-in-/recommend** (zero backend change but bloats request body and would have required rewriting M6's `_gather_inputs` shape). **Soft-fail Redis throughout**: `_write_inflight`/`_clear_inflight` `try/except Exception` around the Redis call + log a warning; SSE stream continues regardless. Canonical end-of-stream `_cache_to_redis` write is still authoritative — inflight is strictly-additive. **Test fixture lesson**: `_FakeContainerClient` only had `_extract_one` (built for `stream_prices`) and didn't expose `extract_all` (called by `get_prices`). Added an `extract_all` shim mirroring single-call semantics + recording each retailer in the same `extract_one_calls` list — kept the force-refresh test driving `get_prices` end-to-end without rewriting via monkeypatch. **Killer integration test**: `test_get_prices_mid_stream_serves_partial_inflight` opens stream, awaits one event (walmart with 5ms delay finishes first), calls `get_prices` in parallel, asserts walmart's row is in the snapshot AND no retailer was dispatched twice. **L2 query_override threading (also folded into same PR after L1 ship)**: `get_prices` now accepts `query_override: str | None = None` and threads it through `_check_redis`, `_check_inflight`, the dispatch query + product_name hint, and `_cache_to_redis` write-back. Skips DB cache when set (mirrors `stream_prices`'s same guard, since the prices table has no scope tag — falling through would serve cross-scope rows). `RecommendationService.get_recommendation` and `_gather_inputs` accept `query_override`; `RecommendationRequest` Pydantic schema gains `query_override: str | None = None` (default-None, backwards-compat for current iOS callers). M6's `_cache_key` conditionally inserts a `:q<sha1>` segment before `:v5` when `query_override` is set — disjoint cache space from the bare-flow rec. **No cache version bump** because the segment is only inserted when set; existing `…:v5` no-override entries continue to be read/written unchanged. Backend 666→683 (+17 tests: 10 inflight cache across `tests/modules/test_m2_prices_stream.py` — 3 pure key-shape, `_writes_inflight_per_retailer_during_run`, `_clears_inflight_after_canonical_write`, `_get_prices_mid_stream_serves_partial_inflight` (the killer), `_inflight_bypassed_on_force_refresh`, `_write_soft_fails_on_redis_error`, `_distinguishes_missing_from_empty`, `_isolated_by_query_override_scope`; plus 2 M6 cache-contamination guards across `tests/modules/test_m6_recommend.py` — `test_recommendation_skips_cache_write_when_prices_came_from_inflight` (asserts M6 cache key is unset + telemetry log fires + second call still recomputes) and `test_recommendation_writes_cache_when_prices_came_from_canonical` regression guard; plus 3 M6 query_override tests — `_with_query_override_reads_scoped_inflight` (proves the scoped bucket is preferred over the bare bucket when both have data), `_cache_isolated_by_query_override_scope` (proves disjoint cache keys + both directions cache-hit), `_no_override_unchanged_by_l2_wiring` (regression guard that the bare flow still reads/writes the v5 key shape unchanged); plus 2 `get_prices` query_override unit tests in `tests/modules/test_m2_prices.py` — `_uses_override_as_dispatch_query` (asserts dispatched query AND product_name hint both = override string), `_skips_db_cache_short_circuit` (proves the DB-skip rule by seeding a $500 DB row, calling with override, confirming the dispatched $100 result is served instead). **Unblocks** the stashed iOS provisional `/recommend` code (`git stash list | grep "PR-3 provisional"`) — once paired iOS lands, iOS will fire `/recommend` at the 5/9 retailer threshold mid-stream (passing `query_override` when in the optimistic-tap flow, omitting it for barcode/SKU-search), M6's `get_prices` will read the SCOPED inflight bucket the stream is writing to instead of dispatching a parallel batch, and the user gets the full hero + receipt 60-90s before the stream finishes on slow days — across BOTH demo flows now. **Remaining honest limitation**: inflight reads return whatever has been classified up to the read moment — if M6's `_filter_prices` strips most as inactive/drift-flagged the recommendation might still raise `InsufficientPriceDataError` (iOS provisional code already silently ignores 422 per the stash). Both L1 and L2 from the original Known Issues were solved in this same PR.
- **apple-variant-disambiguation (PR pending, stacked on cat-rel-1-followups).** Targeted fix for a user-reported demo bug: picked an M4 iPad in the app and saw an M3 iPad listing surface from eBay. Both products had distinct, real model numbers, so the existing identifier hard gate (Rule 1) passed both — the chip name was the only disambiguator and was not gated anywhere. **Rule 2c (Apple chip equality, disagreement-only)** in `m2_prices/service.py:_score_listing_relevance`: extracts `\bM([1-4])(?:\s+(Pro|Max|Ultra))?\b` (case-insensitive, anchored to require exactly 1 digit so M310 mice / M16 carbines / M1234 SKUs / MS220 cables don't false-match) from `clean_name + gemini_model + upcitemdb.model` on the product side and from `listing_title` on the listing side. Normalizes to lowercase tokens (`m1`, `m3 pro`, `m4 max`). Rejects with `score=0.0` only when both sides emit a chip and the sets disagree — explicitly allows when either side omits the chip, because used eBay/FB sellers routinely list "MacBook Air 2022 8GB/256GB" without a chip name and a require-presence gate would zero-out genuine coverage. Mirrors the existing Rule 2 (variants) and Rule 2b (ordinals) shape. **Rule 2d (Apple display-size equality, disagreement-only)** same shape over `\b(11|13|14|15|16)\s*-?\s*inch(?:es)?\b`. Floored at 11 to skip 4"/5"/8" knife and food-scale listings; capped at 16 to skip 24-32" monitors and 40"+ TVs that don't share product UPCs with Apple laptops anyway. Inch-quote shorthand (`13"`) deliberately not matched — most listings spell it out. **Telemetry on every rejection** because silent zero-results from these rules are invisible to users (looks identical to "no retailer had this product"): `logger.info("apple_variant_gate_rejected rule=2{c|d} product_chips=[...] listing_chips=[...] retailer_id=... product_brand=... listing_title=...", ...)`. The pattern to watch for in production logs is *clusters where ALL listings for a single product are rejected* — that's the signal Gemini stored the wrong chip on the canonical (the inverse of the bug this fixes). **Aggregation across product fields**: chip+size extraction runs on `clean_name + gemini_model + upcitemdb.model` joined, maximizing the chance of catching the chip on the product side even when `product.name` itself omits it (which is common — Gemini's iPad Pro M4 canonical is often "Apple iPad Pro 11-inch (2024)" with no chip). **Deliberately cut from scope** (each was evaluated and rejected with a documented reason): (1) generation ordinal gate (`9th gen` / `10th gen`) — sellers don't write ordinals; eBay used iPad listings say "iPad 64GB 2021 WiFi" or model number "A2602" or just "iPad", and even Amazon's product titles say `Apple iPad 10.2-inch (2021)` with no ordinal — adding this gate would zero-out used iPad coverage. Year-as-proxy normalize (`9th gen`→`2021`) was also rejected because year is just as commonly omitted by used-market sellers. Real fix needs a model-number lookup table (A2602 → iPad 9th gen) which is out of scope. (2) Negative-token matching (M3 base must NOT match M3 Pro) — query intent is ambiguous: "macbook pro m3" could mean *the base M3* or *any M3-generation Pro*. No regex disambiguates user intent. Hard gate would punish ambiguous queries with false rejections. Tier bleed is acceptable because hero price differential makes wrong-tier results visible. (3) Chip/size NOT added to `_query_strict_specs` (which is reused by L4 resolve gate and search-time noise filter) — would over-reject correctly-resolved canonicals when Gemini's product name omits the chip name (e.g. "Apple iPad Pro 11-inch (2024)" lacks "M4" but IS the M4 iPad — adding `m4` as a strict spec would force a 404). Kept scoped to M2 listing relevance only. **Honest limitation**: if neither `product.name`, `gemini_model`, nor `upcitemdb.model` carries the chip token, Rule 2c can't fire (no signal on product side). Telemetry will surface this — if logs show frequent silent zero-results on Apple SKUs, the deeper plumbing fix is to thread the user's original query through to M2 (`?query=` override on `/prices/{id}/stream` already exists for this purpose; just isn't always set). Backend 652→666 (+14 tests across `test_m2_prices.py`: 5 helper-level extraction tests including non-Apple collision tests for M310/M16/MS220/M1234, 5 score-level disagreement-only tests including the user's exact bug shape, 1 demo-check-evergreen-MBA-M1 regression guard, 2 telemetry-log assertions on Rule 2c+2d, 1 Pro/Max/Ultra suffix multi-token equality test). Sweep plan documented at `Barkain Prompts/Apple_Variant_Disambiguation_Sweep_v1.md` for any future expansion (15 SKUs across MacBook Air chip rev / MacBook Pro tier+same-year-chip-swap / iPad gen+Air/Pro chip+display).
