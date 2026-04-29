# CLAUDE.md — Barkain

> **Purpose:** Root orientation for AI coding agents. This file alone should let a new session understand the project, find anything, and follow conventions.
> **Last updated:** 2026-04-29 (v5.41 — Step 3n follow-up (PR #81): `FeatureGateService.isMiscRetailerEnabled` now defaults ON in DEBUG when the flag has never been explicitly set, so personal-device + simulator dev builds always render the misc-retailer card without `defaults write` rituals or hardcoded workarounds. Production canary is unchanged — Release builds still read the explicit-OFF default and roll in 5/50/100 % stages. Tests use a non-standard `UserDefaults` suite, so the DEBUG branch is gated on `defaults === UserDefaults.standard` to keep custom suites on the explicit `bool(forKey:)` semantics; explicit `defaults.set(false, ...)` still wins everywhere. **Net effect on canary plan:** the iOS gate is no longer a knob — server-side `MISC_RETAILER_ADAPTER=serper_shopping` toggle is the only canary lever. Live-validated on Mike's iPhone 15 (`192.168.1.242` → `192.168.1.194:8000`, 200 OK on `/api/v1/misc/...`). Test totals unchanged. **Previous (v5.40):** Step 3n M14 misc-retailer slot — Serper Shopping wrapper. New `backend/modules/m14_misc_retailer/` (~430 LOC) consumes `google.serper.dev/shopping` via a new `_serper_shopping_fetch` helper in `ai/web_search.py`, `KNOWN_RETAILER_DOMAINS` filter, top-3 cap, Redis 6h cache, PR #73 inflight pattern at 30s TTL. iOS `MiscRetailerCard`. Bench harness + 50-SKU pet panel. 711 → 757 backend, 203 → 207 iOS. Drive-by `StreamSummary` memberwise-init restore. Full history in `docs/CHANGELOG.md`.)

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
├── CLAUDE.md                  ← You are here
├── docker-compose.yml         ← PG+TimescaleDB, test DB, Redis, LocalStack
├── .env.example
├── Barkain.xcodeproj
├── Barkain/                   # iOS — BarkainApp.swift, ContentView.swift, Assets.xcassets
│   ├── Features/              # Scanner, Search, Recommendation (PriceComparisonView),
│   │                          # Profile, Savings, Billing, Shared
│   └── Services/              # Networking (APIClient, SSE parser), Scanner (AVFoundation),
│                              # Subscription (RC SDK + FeatureGate)
├── BarkainTests/  BarkainUITests/
├── backend/
│   ├── app/                   # main.py, config.py, database.py, dependencies.py,
│   │                          # errors.py, middleware.py, models.py
│   ├── modules/               # m1_product, m2_prices (+adapters/, health_*, sse.py),
│   │                          # m3_secondary, m4_coupons, m5_identity, m9_notify,
│   │                          # m10_savings, m11_billing, m12_affiliate, m13_portal
│   ├── ai/                    # abstraction.py (Gemini+Anthropic), web_search.py
│   │                          # (Serper-then-synthesis), prompts/
│   ├── workers/               # queue_client, price_ingestion, portal_rates,
│   │                          # discount_verification, watchdog
│   ├── tests/                 # conftest.py, modules/, workers/, scripts/,
│   │                          # integration/ (BARKAIN_RUN_INTEGRATION_TESTS=1),
│   │                          # fixtures/portal_rates/
│   ├── requirements.txt  requirements-test.txt
├── containers/                # Per-retailer scrapers: base/, amazon/, best_buy/, walmart/,
│                              # target/, home_depot/, ebay_new/, ebay_used/, backmarket/,
│                              # fb_marketplace/, template/
├── infrastructure/migrations/ # Alembic
├── scripts/                   # run_worker.py, run_watchdog.py, seed_*, ec2_*, bench_*, demo_*
├── prototype/
└── docs/                      # ARCHITECTURE, CHANGELOG (full per-step history),
                               # PHASES, FEATURES, COMPONENT_MAP, DATA_MODEL,
                               # DEPLOYMENT, TESTING, AUTH_SECURITY,
                               # CARD_REWARDS, IDENTITY_DISCOUNTS,
                               # SEARCH_STRATEGY, SCRAPING_AGENT_ARCHITECTURE,
                               # BENCH_VENDOR_COMPARE, BENCH_VENDOR_COMPARE_V2
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
pytest --tb=short -q          # 711 backend tests (Docker PG port 5433, NOT SQLite)
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

**Data flow (barcode):** iOS → `POST /products/resolve` (M1: Serper-then-grounded-Gemini + UPCitemdb cross-val + PG cache) → `GET /prices/{id}/stream` (SSE; M2 fans out to 9 retailers in parallel, writes inflight Redis) → on done `GET /identity/discounts` + `GET /cards/recommendations` → `POST /api/v1/recommend` for the M6 stack → `PriceComparisonView` renders. Tap retailer → `POST /affiliate/click` → `SFSafariViewController` with tagged URL.

**Concurrency:** Python `async`/`await` throughout. Swift structured concurrency on iOS.

---

## Conventions

### Backend (Python)
- FastAPI + Pydantic v2 schemas; Alembic migrations in `infrastructure/migrations/` (backward-compatible only); SQLAlchemy 2.0 async; **constraints mirrored in `__table_args__`** for test `create_all` parity
- Per-module layout `router.py` / `service.py` / `schemas.py`; modules import each other directly (no event bus)
- All AI calls go through `ai/abstraction.py` or `ai/web_search.py` — never import `google.genai` / `anthropic` / `openai` / `httpx`-to-Serper directly
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
- **Snapshot tests for branched render paths:** views where multiple branches each render their OWN top-level container w/ 2+ duplicated sections (precedent: `ProfileView`'s 4 `content` branches) get a test per branch in `BarkainTests/Features/<feature>/…SnapshotTests.swift`; baselines beside the test under `__Snapshots__/`. Record w/ `RECORD_SNAPSHOTS=1` in scheme env; CI runs without. **L-smoke-7:** `ProfileView` is the only view in `Features/*` with this shape — don't re-audit unless a new matching view is introduced. **A11y-grep ruled out:** PNG diff is the only regression signal; identifiers stay in view code as XCUITest anchors only
- **`.task(id:)` on a `Group` whose only child is a hidden `if` does NOT fire** — SwiftUI elides the modifier when the host resolves to EmptyView in the view tree. Caught live in sim during 3n MiscRetailerCard verification: body printed `flag=true rows=0` but the fetch task never ran. **Pattern:** anchor `.task(id:)` on a guaranteed-concrete view inside a wrapping VStack — `Color.clear.frame(width: 0, height: 0).accessibilityHidden(true).task(id:) { … }`, then conditional content as a sibling. The 0×0 Color.clear is a real Shape, so the task lifecycle reliably fires. **Don't trust** `Group { if … }` as a `.task` host even though it compiles cleanly — symptoms are silent (no fetch, no log) and only show up with live integration testing
- **Experiment flags default ON in DEBUG, OFF in Release.** Pattern in `FeatureGateService`: `#if DEBUG` branch returns `true` only when the key is unset (`defaults.object(forKey:) == nil`) AND `defaults === UserDefaults.standard`. Standard-suite gate keeps non-standard test suites on the explicit `bool(forKey:)` default-OFF semantics, so existing tests don't shift, and explicit `defaults.set(false, ...)` still wins in DEBUG. Personal-device + simulator dev builds always render the gated feature; Release/canary stays explicit-OFF. **Why:** flipping experiments via `simctl spawn defaults write` is broken on physical devices (no shortcut) and unreliable on sim (cfprefsd nukes app-sandbox plist edits). Codified in `isMiscRetailerEnabled` (3n-debug-on, PR #81); apply the same pattern to future experiment flags

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
| 3b | eBay Browse API + GDPR deletion webhook + FastAPI on scraper EC2 (Caddy+LE) | +13 | — | #24 |
| demo/post-demo prep | Walmart decodo_http default; Best Buy Products API; Decodo Scraper API for Amazon; lowes/sams_club retired | +127 | — | #25–#31 |
| 3c (+hardening) | Search v2 3-tier cascade + variant collapse + `?query=` price-stream + eBay EPN; retailer retries + Redis cache layering | +40 | +5 | #32 |
| 3d (+noise-filter) | Autocomplete (on-device prefix + `.searchable` + offline vocab); `_is_tier2_noise` → Gemini escalation | +27 | +35 | #34, #36 |
| ui-refresh-v1/v2/v2-fix | Warm-gold design pass + new Home tab + Kennel section + nav-hide-during-stream | +4 | — | #37–#40 |
| 3e | M6 Recommendation Engine — deterministic, no LLM (`/recommend` stacks identity+card+portal, p95 <150 ms) | +14 | +9 | #41 |
| 3f (+hotfix) | Purchase Interstitial + Activation Reminder; 0008 `affiliate_clicks.metadata`; 0009 `discount_programs.scope` | +7 | +9 | #42, #44 |
| Benefits Expansion (+follow-ups) | +10 student-tech + Prime YA; 0010 `is_young_adult`; `_dedup_best_per_retailer_scope`; `/resolve-from-search` fallback | +10 | +7 | #45, #46 |
| fb-marketplace-location-resolver | Numeric FB Page ID end-to-end; 0011 `fb_marketplace_locations`; 3-tier Redis→PG→live + singleflight + GCRA | +28 | +9 | #49 |
| experiment/tier2-ebay-search | 4 opt-in flags (default off); UPCitemdb→Browse swap; partial-listing denylist on ebay | — | — | #50 |
| fb-resolver-followups + postfix-1 | Dedicated `fb_location_resolve` bucket; DTO collapses engines to `live`; picker `retry()`; 3-way decision (VALIDATED/FALLBACK/REJECTED) | +9 | +9 | #51, #52 |
| 3g-A | Portal Live backend: 0012 `portal_configs` + `m13_portal` + 5-step CTA tree + Resend alerting | +16 | — | #53 |
| 3g-B | Portal Live iOS: `PortalCTA` interstitial row + `PortalMembershipPreferences`; M6 cache `:p<sha1(active_portals)>:v5` | +2 | +14 | #54 |
| 3g-B-fix-1 | Wire `portalMembershipsSection` into ProfileView completed-profile branch | — | — | #55 |
| search-resolve-perf-1 | Tiered `_merge()` by confidence; parallel Gemini+UPCitemdb (P50 17→5s, 404 34→13s); `cascade_path` on response | +6 | — | #61 |
| search-relevance-1 | Relevance pack: price-outlier <40% median {ebay,fb}; FB soft model gate; G-series + `upcitemdb.model`; +accessor noise | +8 | — | #62 |
| demo-prep-1 | F&F reliability: 422→`insufficientData` + envelope fix; `UnresolvedProductView` + `TabSelectionAction`; 409 confidence + `/confirm`; first Makefile | +12 | +11 | #63 |
| savings-math-prominence | Hero invert (`Save $X` 48pt → cost → why); shared `StackingReceiptView`; `error.message` audit; `make verify-counts` | +4 | +10 | #64 |
| sim-edge-case-fixes-v1 | Pattern-UPC reject pre-Gemini; canonical 422 envelope handler; SearchView clear-text race; manual-UPC `.numberPad` + digit-filter | +3 | — | #65 |
| interstitial-parity-1 | `priceBreakdownBlock` renders receipt independent of `hasCardGuidance`; M6 filters `portal_by_retailer` by active memberships | +1 | +3 | #66 |
| category-relevance-1 | 5 fixes from 15-SKU sweep: FB overlap 0.4→0.6; appliance regex `[A-Z]{2,4}\d{3,5}…`; brand-bleed gate; `_query_strict_specs`; Rule 3 brand fallback; Rule 3b "for {brand}" reject | +13 | — | #67 |
| cat-rel-1-followups | **L4** `_resolved_matches_query` post-resolve gate. **L1** `_extract_brand_from_url` (Decodo Amazon). **L2** logs Gemini reasoning. **L3** digit-led `\d{5}[A-Z]{0,2}` regex w/ unit-suffix lookahead | +22 | — | TBD |
| apple-variant-disambiguation | **Rule 2c** chip equality disagreement-only; **Rule 2d** display-size 11–16-inch. Telemetry per rejection | +14 | — | TBD |
| inflight-cache-1 (+ L1 + L2) | `prices:inflight:{pid}[:scope]` Redis hash, 120s TTL; `stream_prices` writes pre-yield; `get_prices` Step 2.5; `EXISTS`-after-`HGETALL` missing-vs-empty. **L1** `_inflight` marker → M6 skips cache write. **L2** `query_override` threaded through; `:q<sha1>` cache segment | +17 | — | #73 |
| bench/vendor-compare-1 | 600-call diagnostic: 6 Gemini+Serper configs. **DEFER** — E p50 −59%, $/call −98% but recall contaminated (catalog labels wrong). Opens `bench-cat-1` | +9 | — | #74 |
| feat/grounded-low-thinking | `gemini_generate` `thinking_budget=-1` → `ThinkingLevel.LOW`. Verified by `bench_mini_a_vs_b.py` (UPCitemdb pre-validation): identical recall 8/10, ~37% cheaper | +2 | — | #75 |
| bench/vendor-compare-2 | Clean-catalog re-run, dual-filter prevalidated. B and E tie 24/28 on different UPCs. **MIGRATE B→E with prompt hardening first.** Closes `bench-cat-1`; opens `bench-cat-2` | +0 | — | #76 |
| bench/vendor-migrate-1 | Production AI-resolve: grounded-only (B) → Serper-then-grounded (E-then-B). New `ai/web_search.py:resolve_via_serper`. **temperature=1.0 hardcode bug fixed.** Bench (Mike-verified 9 UPCs): 100% vs 53% recall; p50 -47%; ~36× cheaper. Closes `bench-cat-2` in spirit; opens `vendor-migrate-1-L1` | +17 | — | #77 |
| feat/thumbnail-coverage | End-to-end image plumbing: Serper `imageUrl` pass-through, UPCitemdb `images[]` preserved on `source_raw`, `Product.image_url` backfilled from first scraper in `stream_prices`/`get_prices`, `image_url` on each price row + `product_image_url` on `done`/batch response, iOS `ProductCard` `fallbackImageUrl` chain that promotes on AsyncImage failure (rescues hotlink-blocked CDNs), `PriceRow.retailerIcon` AsyncImage. Live-validated Makita XFD10Z + InfantLY | +1 | +1 | #79 |
| 3n (M14 misc-retailer slot) | New `m14_misc_retailer` module + `_serper_shopping_fetch` helper. Serper Shopping → `KNOWN_RETAILER_DOMAINS` filter → top-3 cap → Redis 6h cache. PR #73 inflight pattern at 30s TTL. 5 adapters (`serper_shopping`/`disabled`/Z-standby/3×X-fallback). `MISC_RETAILER_ADAPTER='disabled'` default. iOS `MiscRetailerCard` behind `experiment.miscRetailerEnabled` UserDefaults flag. Bench harness + 50-SKU pet panel + `make bench-misc-retailer`. Drive-by `StreamSummary` memberwise-init restore | +46 | +4 | #80 |
| 3n-debug-on (follow-up) | `isMiscRetailerEnabled` defaults ON in DEBUG when unset (gated on `defaults === UserDefaults.standard` so test suites still default OFF). Removes the `defaults write` ritual on personal devices; production canary unchanged | — | +13/−2 | #81 |

**Test totals:** 757 backend + 207 iOS unit + 6 iOS UI (with experiment flags off — see L-Experiment-flags-default-off). `ruff check` clean. `xcodebuild` clean.

**Migrations:** 0001 (initial, 21 tables) → 0002 (price_history composite PK) → 0003 (is_government) → 0004 (card catalog unique index) → 0005 (portal bonus upsert + failure counter) → 0006 (`chk_subscription_tier` CHECK) → 0007 (pg_trgm + trgm GIN idx) → 0008 (`affiliate_clicks.metadata` JSONB) → 0009 (`discount_programs.scope` — product / membership_fee / shipping) → 0010 (`is_young_adult` on `user_discount_profiles`) → 0011 (`fb_marketplace_locations` — city→FB Page ID cache w/ tombstoning) → 0012 (`portal_configs` — display + signup-promo + alerting state for shopping portals). Drift marker in `tests/conftest.py::_ensure_schema` checks `portal_configs`.

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
| cat-rel-1-L2-ux | LOW | When `/products/resolve-from-search` returns 404 because Gemini correctly refused (multi-variant line / not stocked online), iOS could surface Gemini's reasoning rather than a generic "couldn't find" — requires plumbing reasoning into the error envelope and a dedicated iOS state. Defer to iOS sprint | Phase 3 |
| bench-cat-2 | RESOLVED | Closed in spirit by vendor-migrate-1 — Mike-verified 9-UPC catalog gave the broader-category recall answer (E_current_budget0 45/45 vs B_grounded_low 24/45). vendor-compare-3 still nice-to-have but not blocking | — |
| vendor-migrate-1-L1 | LOW | Serper coverage tail in production: when `resolve_via_serper` returns None on a cold-path UPC, fallback to grounded Gemini at original $0.040/call + ~3s p50. Watch `Serper synthesis returned null device_name for UPC %s` log frequency in `barkain.ai.web_search`. If >15% of cold-path resolves hit fallback, options: (a) multi-query Serper, (b) increase top-N from 5 to 10, (c) alternate SERP source. Fallback is graceful, just slower + costlier on the tail | Phase 3 ops |
| thumbnail-coverage-L1 | LOW | Search-result rows produced by Tier 3 Gemini search show the box-icon placeholder — Gemini search has no image field and the cascade has no fallback. Rows from Tier 1/2 (DB/BBY/UPCitemdb) render fine. Fix needs either an image-fetch pass on Tier 3 candidates (extra latency) or surfacing only top-N with images first (relevance trade-off). Defer until thumbnail miss-rate is measured in production | Phase 3 |
| thumbnail-coverage-L2 | LOW | `RecentlyScannedStore` (iOS) caches `imageUrl` at first-resolve time — older entries that resolved before this fix keep showing the paw icon on Home until the user taps them again, which re-runs resolve and overwrites the local cache. Self-heals on next interaction; bulk reset is overkill. Verified for the original Makita 18V LXT and InfantLY entries | iOS |
| thumbnail-coverage-L3 | LOW | Backfill in `stream_prices`/`get_prices` only fires when `Product.image_url IS NULL`. Products that resolved with a hotlink-blocked CDN URL (e.g. `production-web-cpo.demandware.net` returns HTTP 403) keep that broken URL forever. iOS papers over with `fallbackImageUrl` chain on AsyncImage failure, but cleaner long-term: backend-side known-bad-host blocklist that also overwrites those URLs on backfill, OR HEAD-check the URL before persisting it | Phase 3 |
| misc-retailer-L1 | LOW | Bench-cron + Serper coverage tail for the Step 3n misc-retailer slot. Schedule `make bench-misc-retailer` weekly post-canary (current panel is a placeholder pet-vertical mix; Mike to curate once usage data exists). Watch for: (a) the bench's `panel_below_alert` flag (<75% pass × 2 consecutive runs → Z-build kickoff per §Locked Decisions item 4); (b) Serper Shopping cold-path null returns logged in `barkain.m14.serper_shopping`. Vendor-concentration hedge is the Z-standby adapter stub already plumbed; build trigger is the bench, not a separate decision | Phase 3 ops |

---

## What's Next

1. **Phase 2 CLOSED** — `v0.2.0` tagged (2026-04-16). Outstanding: revoke leaked PAT `gho_UUsp9ML7…` in GitHub UI (SP-L1-b, Mike).
2. **Phase 3:** all steps in the table above are ✅ shipped or PR-pending. **Active follow-ups:** Mike physical-iPhone app-tests (watch p50 SSE-first-event drop ~3s → ~1.5s on cold-cache UPCs); monitor `vendor-migrate-1-L1` (Serper-coverage tail in `barkain.ai.web_search` logs); **3n misc-retailer canary** (Mike buys $50 Starter Serper pack → `make bench-misc-retailer` against placeholder panel → if ≥80% pass, flip `MISC_RETAILER_ADAPTER=serper_shopping` for 5% → 50% → 100% over 48h. iOS gate is no longer a knob: PR #81 made `isMiscRetailerEnabled` Debug-default-ON / Release-default-OFF, so the canary is server-side only — staged production rollout = `MISC_RETAILER_ADAPTER` toggle plus whatever traffic-percentage mechanism we wire in); weekly bench cron post-canary (alerting on `misc-retailer-L1`); **resurrect stashed iOS provisional `/recommend` code** (`git stash list | grep "PR-3 provisional"`, `git stash pop` — backend now serves partial inflight data); AppIcon PNGs when Figma lands; prod FB seed (Mike); eBay-Tier-2 graduation call; snapshot-baseline re-record pass (sim-26.3 drift); F#1c (route Continue through portal redirect when active membership matches `winner.portal_source`); `cat-rel-1-L2-ux` (surface Gemini reasoning to iOS for unverifiable-SKU 404s); watch `apple_variant_gate_rejected` log clusters. **Remaining steps:** 3h Vision, 3i receipts, 3k savings, 3l coupons, 3m hardening → `v0.3.0`. 3j folded into 3e
3. **Phase 4 — Production Optimization:** ~~Best Buy~~ (done via demo-prep bundle, PR #30), Keepa API adapter, App Store submission, Sentry error tracking
4. **Phase 5 — Growth:** Push notifications (APNs), web dashboard, Android (KMP)

---

## Production Infra (EC2)

Single-host: all scraper containers + FastAPI backend (eBay webhook + Browse/Best Buy/Decodo Scraper API adapters) run on one `t3.xlarge` (`us-east-1`). Left running between sessions — don't auto-stop unless Mike says.

- **SSH:** `ssh -i ~/.ssh/barkain-scrapers.pem ubuntu@54.197.27.219`
- **Instance:** `i-09ce25ed6df7a09b2`, SG `sg-0235e0aafe9fa446e` (8081–8091 + 80/443)
- **Public webhook:** `https://ebay-webhook.barkain.app` (Caddy + Let's Encrypt)
- **Ports:** `amazon:8081 bestbuy:8082 walmart:8083 target:8084 homedepot:8085 ebaynew:8087 ebayused:8088 backmarket:8090 fbmarketplace:8091` (8086 lowes + 8089 sams_club retired 2026-04-18). Backend uvicorn on `127.0.0.1:8000` behind Caddy `:443`.
- **Env file:** `/etc/barkain-api.env` (mode 600) — eBay creds + `SERPER_API_KEY`; no PG/Redis on this host.

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
- **External APIs.** eBay Browse (`EBAY_APP_ID`+`CERT_ID`, 2h TTL); Best Buy Products API (`BESTBUY_API_KEY`); Decodo Scraper API for Amazon (`DECODO_SCRAPER_API_AUTH`); Serper SERP (`SERPER_API_KEY`, top-5 organic, ~$0.001/call); GDPR webhook = GET SHA-256 + POST 204
- **9 active scraped retailers** post-2026-04-18 (lowes + sams_club retired). `*_direct` rows stay `is_active=True` as identity-redirect targets
- **AI resolve (vendor-migrate-1).** `_get_gemini_data` tries `web_search.resolve_via_serper` first (Serper top-5 → Gemini synthesis, `grounded=False, thinking_budget=0, max=1024, temperature=0.1`); soft-falls to grounded Gemini (`thinking_level=ThinkingLevel.LOW` since PR #75) on null/error. `gather(_get_gemini_data, _get_upcitemdb_data)` unchanged. **temperature=1.0 hardcode bug fixed.** Autouse pytest fixture `_serper_synthesis_disabled` patches `resolve_via_serper`→None for every test by default. Blended cost ~$0.0070/call avg (~5.7× cheaper than grounded-only)
- **Search v2 cascade.** normalize → Redis → DB pg_trgm@0.3 → Tier 2 `gather(BBY, UPCitemdb)` → Tier 3 Gemini. Tiered merge strong/weak (`_STRONG_CONFIDENCE=0.55`), tiebreaks `DB>BBY>UPCitemdb>Gemini`. `cascade_path` on response. `?query=` override on `/prices/{id}/stream`
- **Relevance pack (#62, #67, cat-rel-1-followups, apple-variant).** Price-outlier <40% median on `{ebay,fb}`; FB soft model gate (`_FB_SOFT_GATE_MIN_OVERLAP=0.6`); model regexes `[A-Z]\d{3,4}` + `[A-Z]{2,4}\d{3,5}[A-Z]{1,4}\d{0,2}` + `\d{5}[A-Z]{0,2}` (w/ unit-suffix lookahead); `_query_strict_specs` voltage/4+digit; brand-bleed gate; Rule 3 brand fallback to product.name; Rule 3b `for {brand}` reject; Rule 2c chip / 2d display-size disagreement-only w/ telemetry; post-resolve L4 `_resolved_matches_query`
- **M6 Recommendation (3e + interstitial-parity-1).** Deterministic. `gather`s Prices+Identity+Cards+Portals, <150 ms p95. `final = base − identity`; rebates on post-identity price. Brand-direct ≥15 % at `*_direct`. 15-min Redis cache key `:c<sha1(cards)>:i<sha1(identity)>:p<sha1(active_portals)>:v5` w/ optional `:q<sha1>` segment. `portal_by_retailer` filtered by active memberships only. iOS hero failures → `RecommendationState.insufficientData`
- **Inflight cache (#73).** `prices:inflight:{pid}[:scope]` Redis hash, 120s TTL. `stream_prices` writes pre-`yield`; `get_prices` Step 2.5 reads, never re-dispatches; `EXISTS` after `HGETALL` distinguishes missing vs empty. `_inflight: True` marker → M6 skips `_write_cache`. `query_override` threaded through; M6 `_cache_key` adds `:q<sha1>`. Soft-fails Redis throughout
- **Purchase Interstitial (3f, interstitial-parity-1).** `PurchaseInterstitialSheet` from hero CTA + row taps; per-retailer `estimated_savings`; `discount_programs.scope ∈ {product, membership_fee, shipping}` (0009). `priceBreakdownBlock` renders `StackingReceiptView` whenever `receipt.hasAnyDiscount`, independent of `hasCardGuidance`
- **Benefits Expansion.** +10 student-tech + Prime YA (`scope='membership_fee'`); `is_young_adult` (0010); `_dedup_best_per_retailer_scope`; `/resolve`→`/resolve-from-search` fallback
- **FB Marketplace location resolver (0011).** Numeric FB Page ID end-to-end; 3-tier Redis(24h)→PG→live. GCRA bucket + singleflight. iOS `Stored.fbLocationId` is bigint-safe String. fb-resolver-followups: dedicated `fb_location_resolve` bucket (5/min); DTO `resolution_path` collapses engines to `live`; 3-way decision (VALIDATED>FALLBACK>REJECTED)
- **experiment/tier2-ebay-search (#50).** 4 env flags default OFF. Browse omits `gtin` even w/ EXTENDED — `SKIP_UPC` is de facto
- **Portal monetization (3g-A/B).** 0012 `portal_configs`. 5-step CTA tree: feature-flag → 24h staleness → MEMBER_DEEPLINK → SIGNUP_REFERRAL w/ FTC → GUIDED_ONLY. Resend alerting: 3 consecutive empty → email, 24h throttle. **Codable pitfall:** `.convertFromSnakeCase` → `portalCtas` (lowercase `as`). **ProfileView dual-branch pitfall:** grep BOTH `ScrollView` branches when adding a section
- **demo-prep-1 (#63).** Explicit states over silent-nil. FastAPI envelope decode fix in `APIClient.decodeErrorDetail`. `UnresolvedProductView` + `TabSelectionAction` env. `LOW_CONFIDENCE_THRESHOLD=0.70` 409 gate on `/resolve-from-search` + `/confirm` marks `user_confirmed`. `make demo-check`/`demo-warm` + first repo-root Makefile
- **savings-math-prominence (#64).** Shared `StackingReceiptView` + `StackingReceipt` value across hero + interstitial. `Money.format` no `.00`. Backend `error.message` re-toned. `make demo-check --no-cache --remote-containers=ec2` (`?force_refresh=true`). `make verify-counts` pins totals
- **sim-edge-case-fixes-v1 (#65).** Pattern-UPC reject `^(\d)\1{11,12}$` pre-Gemini. `RequestValidationError` handler rewraps Pydantic 422s into canonical envelope. SearchView `.searchable` sync setter; manual-UPC `.numberPad` + digit-filter
- **Bench framework (#74–#76, vendor-migrate-1).** `scripts/bench_vendor_compare.py` + `_bench_serper.py` + `bench_data/test_upcs*.json` + `--catalog` CLI flag. `bench_prevalidate_v2.py` dual-filter (UPCitemdb + Gemini agreement). **Counterintuitive find:** small thinking budgets (256/512/1024) HURT recall on clean SERP — budget=0 forces direct snippet extraction
- **M14 misc-retailer slot (Step 3n + 3n-debug-on, #80, #81).** `_serper_shopping_fetch` (thumbnail-stripped, soft-fail to None) + `m14_misc_retailer` module (flat: schemas + service + router + 6 adapters in one dir, no `cache.py`/`filters.py`). `KNOWN_RETAILER_DOMAINS` filter drops Amazon/Best Buy/Walmart/Target/Home Depot/eBay/BackMarket/FB Marketplace + display variants ("best buy", "back market") + their `*_direct` mirrors. **Inflight TTL 30s, NOT 120s** — sized for Serper's 1.4–2.5s p50 single-call API, vs `m2_prices`'s 9-scraper SSE fan-out. Cap 3 rows server-side + iOS-side. iOS `MiscRetailerCard` opens Google Shopping product page in `SFSafariViewController` (NOT a direct merchant URL — Google handles redirect). `MISC_RETAILER_ADAPTER='disabled'` default; flip to `serper_shopping` post-bench. **iOS gate (`isMiscRetailerEnabled`) is Debug-default-ON / Release-default-OFF** — Debug branch is `defaults === UserDefaults.standard && defaults.object(forKey:) == nil` so test suites stay on explicit `bool(forKey:)` semantics. Canary is server-only via `MISC_RETAILER_ADAPTER`. Vendor concentration hedge: Z-standby adapter stub raises `NotImplementedError` so accidental flag-flip is loud; build trigger is bench `panel_below_alert` (<75% × 2 weekly runs). **`backend/ai/web_search.py` now hosts 4 Serper code paths** (~316 LOC): `_serper_fetch` + `resolve_via_serper` + `_first_image_url` + `_serper_shopping_fetch`. Split trigger ~300 LOC OR a 5th path → `serper_resolve.py` + `serper_shopping.py` + shared `serper_client.py`
