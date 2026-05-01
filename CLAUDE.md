# CLAUDE.md — Barkain

> **Purpose:** Root orientation for AI coding agents. This file alone should let a new session understand the project, find anything, and follow conventions.
> **Last updated:** 2026-05-01 (v5.51 — `fix/3o-C-L1-token-overlap-gate` (open). Closes `3o-C-L1-fabricated-upc-tap` after live re-diagnosis. `_resolved_matches_query` gains a 3rd check (token-overlap floor) on top of brand + strict-spec — when query has ≥2 meaningful tokens (≥3 chars, non-stopword), require ≥2 substring-hits in the resolved haystack. Defends against in-brand cross-category drift the brand-keyword check alone misses. Live-confirmed against `Apple Watch Ultra 2 49mm Natural Titanium GPS Cellular`: pre-fix returned MacBook Air rows ($769–$830) via real-but-wrong-product UPC `195949036323`; post-fix (a) invalidates the bad cached UPC + 404s on cache-hit, (b) falls cleanly to provisional on fresh-upstream → 4 real Apple Watch prices ($341.96–$650) in M2 + 3 in M14. +2 BE tests (815→817). v5.50 — `feat/provisional-resolve` (open). Adds a dark-launched fallback path on `POST /resolve-from-search`: when both Gemini device→UPC AND UPCitemdb keyword search return null, instead of raising `UPC_NOT_FOUND_FOR_PRODUCT` we persist a best-effort `Product` with `upc=NULL`, `source="provisional"`, `source_raw["provisional"]=True` + `["search_query"]` (and Gemini's stated reason when present). Gated by new `PROVISIONAL_RESOLVE_ENABLED: bool = False` flag — schema + property changes ship safely with behavior unchanged until the flag flips. New `Product.match_quality` JSONB-derived `@property` (`"exact" | "provisional"`) surfaces on `ProductResponse` so iOS can branch. M2 `get_prices` + `stream_prices` auto-inject `query_override = product.name` for provisional rows so the bare-name cache scope, container query, and per-container product_name hint all key off the user's intent rather than a generic SKU title (relevance gates do the rest). M6 `recommendation_skip_cache_write` log line generalized: now fires for both inflight + provisional payloads (provisional snapshot would mask a future canonical-UPC backfill). 7-day dedup window on `(name, brand, source='provisional')` keeps re-tapped dead-end queries pinned to one row. Wire-through: new `query: String?` on `ResolveFromSearchRequest`; `Endpoint.resolveFromSearch` + `APIClientProtocol.resolveProductFromSearch` + `MockAPIClient` + `BarePreviewAPIClient` all gain it (Swift protocol default-args don't propagate through protocol-typed call sites — every conformer + holder passes explicitly). iOS `Product` gains `matchQuality: String?` + `isProvisional` convenience; `RecommendationHero` renders a soft "Best results for \"<query>\"" banner above the card and downgrades the gold BEST BARKAIN eyebrow to muted "APPROXIMATE MATCH" when provisional; `SearchView`'s `recentlyScanned.record` skips provisional rows so the rail stays canonical. Tests +9 backend (806→815) + new hero snapshot baseline. Live-verified: Festool TS 60 KEBQ-Plus 577419 (yesterday's 404 sweep) now persists provisional, M2 stream returns FB Marketplace $700 used listing while other retailers correctly `no_match` at the relevance-gate level. **`feat/search-thumbnail-fallback` (#94)** still open from 2026-04-30. Known Issues unchanged at 1 open (`2i-d-L4` MED).)

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
- **Snapshot tests for branched render paths:** views w/ multiple branches each rendering own top-level container + duplicated sections (precedent: `ProfileView`'s 4 `content` branches) get a test per branch under `BarkainTests/Features/<feature>/…SnapshotTests.swift` w/ baselines in `__Snapshots__/`. Record w/ `RECORD_SNAPSHOTS=1`. ProfileView is the only such view in `Features/*` (L-smoke-7). PNG diff is the only regression signal — identifiers stay as XCUITest anchors
- **`.task(id:)` on a `Group { if … }` host does NOT fire** — SwiftUI elides the modifier when the host resolves to EmptyView. Caught live in 3n MiscRetailerCard. **Pattern:** anchor `.task(id:)` on a guaranteed-concrete view inside a wrapping VStack — `Color.clear.frame(width: 0, height: 0).accessibilityHidden(true).task(id:) { … }`, then conditional content as a sibling. Symptom is silent — only live integration testing catches it
- **Experiment flags default ON in DEBUG, OFF in Release.** `FeatureGateService` pattern: `#if DEBUG` branch returns `true` only when `defaults === UserDefaults.standard && defaults.object(forKey:) == nil`. Standard-suite gate keeps non-standard test suites on explicit `bool(forKey:)` default-OFF; explicit `defaults.set(false, ...)` still wins. **Why:** `simctl spawn defaults write` is broken on physical devices and unreliable on sim (cfprefsd nukes app-sandbox plist edits). Codified in `isMiscRetailerEnabled` (PR #81); apply to future flags

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
| 3a | M1 text search (pg_trgm + Gemini fallback) + SearchView | +10 | +7 | #22, #23 |
| 3b | eBay Browse API + GDPR webhook + FastAPI on scraper EC2 (Caddy+LE) | +13 | — | #24 |
| demo prep | Walmart decodo_http default; Best Buy Products API; Decodo Scraper API for Amazon; lowes/sams_club retired | +127 | — | #25–#31 |
| 3c | Search v2 3-tier cascade + variant collapse + `?query=` price-stream + eBay EPN | +40 | +5 | #32 |
| 3d | Autocomplete (on-device prefix + `.searchable`); `_is_tier2_noise` → Gemini escalation | +27 | +35 | #34, #36 |
| ui-refresh-v1/v2 | Warm-gold design pass + Home tab + Kennel + nav-hide-during-stream | +4 | — | #37–#40 |
| 3e | M6 Recommendation Engine — deterministic, no LLM, p95 <150 ms | +14 | +9 | #41 |
| 3f | Purchase Interstitial + Activation Reminder; 0008 `affiliate_clicks.metadata`; 0009 `discount_programs.scope` | +7 | +9 | #42, #44 |
| Benefits Expansion | +10 student-tech + Prime YA; 0010 `is_young_adult`; `/resolve-from-search` fallback | +10 | +7 | #45, #46 |
| fb-loc-resolver | Numeric FB Page ID end-to-end; 0011 `fb_marketplace_locations`; 3-tier Redis→PG→live + GCRA | +28 | +9 | #49 |
| tier2-ebay-search | 4 opt-in flags (default off); UPCitemdb→Browse swap; partial-listing denylist | — | — | #50 |
| fb-resolver-followups | `fb_location_resolve` bucket; DTO `live` collapse; picker `retry()`; VALIDATED/FALLBACK/REJECTED | +9 | +9 | #51, #52 |
| 3g-A | Portal Live backend: 0012 `portal_configs` + `m13_portal` + 5-step CTA tree + Resend alerting | +16 | — | #53 |
| 3g-B | Portal Live iOS: `PortalCTA` row + `PortalMembershipPreferences`; M6 cache `:p<sha1>` | +2 | +14 | #54 |
| 3g-B-fix-1 | Wire `portalMembershipsSection` into ProfileView completed branch | — | — | #55 |
| search-resolve-perf-1 | Tiered `_merge()` by confidence; parallel Gemini+UPCitemdb (P50 17→5s); `cascade_path` | +6 | — | #61 |
| search-relevance-1 | Price-outlier <40% median {ebay,fb}; FB soft gate; G-series + `upcitemdb.model` | +8 | — | #62 |
| demo-prep-1 + savings-math + sim-edge + interstitial-parity + cat-relevance | F&F demo pack: 422→`insufficientData`; `UnresolvedProductView`; 409 + `/confirm`; hero invert + `StackingReceiptView`; pattern-UPC reject; M6 portal filtering; FB overlap 0.4→0.6; brand-bleed gate; Rule 3/3b | +33 | +24 | #63–#67 |
| cat-rel-1-followups + apple-variant + inflight-cache | L4 post-resolve gate; brand-from-URL; Gemini reasoning logs; Apple chip/display-size disagreement-only gates; `prices:inflight:{pid}[:scope]` Redis hash 120s TTL | +53 | — | #73, TBD |
| bench-vendor 1+2+migrate | Bench cascade resolved Serper-then-grounded (E_then_B) as the new resolve hot path: 100% vs 53% recall, p50 −47%, ~36× cheaper. temperature=1.0 hardcode fixed | +28 | — | #74–#77 |
| feat/thumbnail-coverage | End-to-end image plumbing: Serper/UPCitemdb passthrough, scraper backfill, iOS `ProductCard` fallback chain. Opens L1–L3 | +1 | +1 | #79 |
| 3n + 3n-debug-on | M14 misc-retailer slot via `_serper_shopping_fetch`; iOS `MiscRetailerCard`. iOS gate Debug-default-ON / Release-default-OFF | +46 | +17 | #80, #81 |
| 3o-A | Autocomplete vocab expansion: drop `is_electronics()` filter; sweep 6 Amazon scopes + 2 probe-admitted extras; parallelize via `asyncio.gather`; `--max-terms` 5K→15K; bundle `version=2`. Vocab 4,448→15,000 | +6/−9 | 0 | #84 |
| 3o-B | Tier-2 noise filter narrowing: 14-entry denylist → hard (11) / soft (`case`+`charger`, query-opt-out) / accessor-context (electronics-parent gate). Resolves cat-litter false-negative + 3o-A predictable misses | +19 | 0 | #85 |
| 3o-C | Gemini UPC `system_instruction` rewritten category-agnostic (3,489→4,310 chars). 9-step skeleton + JSON contract preserved; 6 mixed-vertical examples replace 4 electronics-only. New `tests/ai/test_upc_lookup_prompt.py` anti-condensation suite (8 tests). Closes 3o-A+B+C trilogy | +8 | 0 | TBD |
| known-issues-triage-1..4 | 15 → 1 open Known Issue across four rounds (2026-04-29). Closed: `noise-filter-L1` (`"game download"` token), `2h-ops` (SQS DLQ wiring), `cat-rel-1-L2-ux` (Gemini reasoning in 404 envelope), `thumbnail-coverage-L1` (brand-initials placeholder), `thumbnail-coverage-L3` (`_KNOWN_BAD_IMAGE_HOSTS` blocklist), `vendor-migrate-1-L1` (Serper outcome counter), `2i-d-L3`/`L2`/`misc-retailer-L1` (stale/won't-fix), `SP-L1-b` (PAT revoked) | +17 BE/+8 iOS | +69 iOS | TBD |
| fix/dark-mode-contrast | Dark-mode contrast fix on warm-gold capsules + hero card. `barkainOnPrimaryContainer` dark hex `#2A1C00` on `barkainPrimaryFixed` `#3A2D15` was ≈1.2:1 (below WCAG AA). Split: `OnPrimaryContainer` stays always-dark for `BestBarkainBadge` always-gold pill; new `barkainOnPrimaryFixed` (light `#694700`, dark `#F9B12D`) flips for warm-cream/warm-dark capsules. New `barkainHeroSurface` (light `#F7D18C`, dark `#2A1F0E`) replaces hero's `PrimaryContainer.opacity(0.55)`. 7 sites migrated; ScentTrail untouched | 0 BE | +28/−10 iOS | #93 |
| feat/search-thumbnail-fallback | Last-resort thumbnail cascade after `_collapse_variants`: eBay Browse `lookup_thumbnail` (free) → Serper `/images` `lookup_thumbnail_via_serper` (paid ~$0.001/call, switched mid-build from `/search`). Per-row parallel, soft-fail. `SEARCH_THUMBNAIL_FALLBACK` flag (default ON). Wire-through: `fallback_image_url` on resolve schemas; `_persist_product` adopts ONLY when no upstream image, via `_KNOWN_BAD_IMAGE_HOSTS`. iOS forwards `result.imageUrl`. Persisted onto `Product.image_url` so loading + Recently Sniffed inherit. Live-verified in sim — niche queries now show real thumbnails | +6 BE | +5 iOS | #94 |
| feat/provisional-resolve | Dark-launched fallback in `/resolve-from-search`: when Gemini + UPCitemdb both null, persist a Product w/ `upc=NULL`, `source='provisional'`, `source_raw['provisional']=True` + `['search_query']`. New `Product.match_quality` `@property` (`exact`/`provisional`) on `ProductResponse`. M2 `get_prices`/`stream_prices` auto-inject `query_override = product.name` for provisional rows so the bare-name cache scope wins; M6 `_write_cache` skipped (renamed log to `recommendation_skip_cache_write`, covers both inflight + provisional). 7-day dedup on `(name, brand, source='provisional')`. iOS `RecommendationHero` adds banner + downgraded eyebrow when `product.isProvisional`; `SearchView` skips provisional from Recently Sniffed; `query: String?` threaded through `Endpoint`/`APIClientProtocol`/`MockAPIClient`/`BarePreviewAPIClient`. `PROVISIONAL_RESOLVE_ENABLED: bool = False` flag. Live-verified Festool 577419 → provisional row → FB Marketplace $700 used listing | +9 BE | +6 iOS | TBD |
| fix/3o-C-L1-token-overlap-gate | Closes `3o-C-L1-fabricated-upc-tap`. `_resolved_matches_query` (post-resolve relevance gate) gains a 3rd check on top of brand + strict-spec: when query has ≥2 meaningful tokens (≥3 chars, not in `_RELEVANCE_STOPWORDS`), require ≥2 to substring-match the resolved haystack. Defends against in-brand cross-category drift the brand-keyword check alone misses (`Apple Watch Ultra 2 49mm Natural Titanium GPS Cellular` → Gemini-picked MacBook Air UPC; "apple" matches both haystacks but watch/49mm/titanium/gps/cellular don't). Falls back to gates 1+2 only when query has <2 meaningful tokens (`iPhone 16 Pro` → `["iphone"]`) to avoid penalizing single-iconic-name resolves. Reuses `_meaningful_query_tokens` from `search_service.py`. Live-verified: same Apple Watch Ultra 2 query that returned MacBook Air rows pre-fix now (a) cache-hit branch invalidates bad UPC + raises 404, (b) fresh-upstream branch falls to provisional → 4 real Apple Watch rows in M2 + 3 in M14 misc | +2 BE | 0 | TBD |

**Test totals:** 817 backend passed + 8 skipped (825 collected) + 216 iOS unit + 6 iOS UI (experiment flags off). Recent deltas: fix/3o-C-L1-token-overlap-gate +2 BE (815→817); feat/provisional-resolve +9 BE (806→815) + 1 iOS hero snapshot (215→216); feat/search-thumbnail-fallback +7 BE (799→806); fix/dark-mode-contrast 0 (cosmetic); triage-4 +8 iOS (207→215); triage-3 +10 BE (789→799); triage-2 +6 BE (784→790); triage-1 +1 BE; 3o-C +8 BE; 3o-B +19 BE. `ruff check` + `xcodebuild` clean. (Pre-existing iOS snapshot flakes on `StackingReceiptViewSnapshotTests`, `UnresolvedProductViewSnapshotTests`, `ConfirmationPromptViewSnapshotTests`, `ProfileViewSnapshotTests` and 2 `AutocompleteServiceTests` cases reproduce on `main` — unrelated to this PR. See `SnapshotTestHelper.swift` for the iOS 26.4 environmental hang note.)

**Migrations:** 0001 (initial, 21 tables) → 0002 (price_history composite PK) → 0003 (is_government) → 0004 (card catalog unique index) → 0005 (portal bonus upsert + failure counter) → 0006 (`chk_subscription_tier` CHECK) → 0007 (pg_trgm + trgm GIN idx) → 0008 (`affiliate_clicks.metadata` JSONB) → 0009 (`discount_programs.scope` — product / membership_fee / shipping) → 0010 (`is_young_adult` on `user_discount_profiles`) → 0011 (`fb_marketplace_locations` — city→FB Page ID cache w/ tombstoning) → 0012 (`portal_configs` — display + signup-promo + alerting state for shopping portals). Drift marker in `tests/conftest.py::_ensure_schema` checks `portal_configs`.

> Per-step file inventories, detailed test breakdowns, and full decision rationale: see `docs/CHANGELOG.md`.

---

## Known Issues

> Full history in `docs/CHANGELOG.md`. Only items affecting active development are listed here.

| ID | Severity | Issue | Owner |
|----|----------|-------|-------|
| 2i-d-L4 | MEDIUM | Watchdog heal at `workers/watchdog.py:251` passes `page_html=error_details`; needs browser fetch in heal path | Phase 3 |

> **Recently closed** (kept here as a marker for one cycle, then drop):
> **2026-05-01 (this session):**
> `3o-C-L1-fabricated-upc-tap` (open PR TBD) — `_resolved_matches_query` gains a token-overlap gate. Same Apple Watch Ultra 2 query that pre-fix returned MacBook Air prices now (a) invalidates the bad cached UPC and raises 404 on cache-hit branch, (b) falls cleanly to provisional on fresh-upstream branch (Gemini returned no UPC, UPCitemdb rate-limited) → real Apple Watch prices via M2 + M14.
> `provisional-resolve` (open) — dark-launched fallback in `/resolve-from-search` for the "no UPC at all" branch. New `Product.match_quality` JSONB-derived property; `PROVISIONAL_RESOLVE_ENABLED` flag default OFF. M2 stream auto-injects `query_override` for provisional rows, M6 skips cache write for them, 7-day dedup keeps re-taps pinned to one row. iOS hero gets approximate-match banner + downgraded eyebrow when provisional.
> **2026-04-30:**
> `dark-mode-contrast` (PR #93, merged) — token split: `OnPrimaryContainer` always-dark + new `OnPrimaryFixed` flipping; new `barkainHeroSurface` for hero card. 7 sites migrated; ScentTrail untouched.
> `search-thumbnail-fallback` (PR #94, open) — eBay Browse → Serper `/images` cascade after `_collapse_variants`. `SEARCH_THUMBNAIL_FALLBACK` default ON. `fallback_image_url` wires search-row image to `Product.image_url`. Switched mid-build from Serper `/search` → `/images` after niche-query miss in headed sim.

---

## What's Next

1. **Phase 2 CLOSED** — `v0.2.0` tagged (2026-04-16).
2. **Phase 3:** category-expansion trilogy + dark-mode + thumbnail-fallback shipped. **Active follow-ups:** physical-iPhone p50 (~3s → ~1.5s); 3n misc-retailer canary ($50 Starter Serper → bench → flip `MISC_RETAILER_ADAPTER=serper_shopping` 5→50→100%); weekly bench cron; AppIcon PNGs; prod FB seed; eBay-Tier-2 graduation; snapshot baseline re-record; F#1c portal-Continue. **Remaining:** 3h Vision · 3i receipts · 3k savings · 3l coupons · 3m hardening → `v0.3.0`
3. **Phase 4 — Production Optimization:** Keepa API, App Store submission, Sentry
4. **Phase 5 — Growth:** APNs, web dashboard, Android (KMP)

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

**Retailer health (2026-04-18):** target/homedepot/backmarket 3/3 via container; fbmarketplace via Decodo (~30 s); walmart via `walmart_http` (~3.3 s); amazon via `amazon_scraper_api` (~3.2 s); bestbuy via `best_buy_api` (~82 ms); ebaynew/ebayused via `ebay_browse_api` (~500 ms). API-keyed adapters need their respective env vars set.

**Cost-stop:** `aws ec2 stop-instances --instance-ids i-09ce25ed6df7a09b2 --region us-east-1` (static IP survives).

---

## Key Decisions Log

> Quick-ref index only. Full rationale + code pointers in `docs/CHANGELOG.md` Key Decisions Log + per-step entries.

### Phase 1 + 2 (quick-ref)
- Container auth VPC-only; `WALMART_ADAPTER={container,firecrawl,decodo_http}`; fd-3 stdout; `EXTRACT_TIMEOUT=180`
- Relevance: model-number hard gate + variant-token + ordinal + brand + 0.4 overlap; UPCitemdb cross-val w/ Gemini (brand agreement wins)
- SSE via `asyncio.as_completed` + iOS byte splitter; batch fallback. Identity zero-LLM SQL <150 ms post-SSE. Card priority: rotating > user > static > base
- Billing: iOS RC SDK UI, backend `users.subscription_tier` rate-limit; webhook SETNX 7d idempotency; tier cache 60 s fail-open
- Workers: LocalStack/real SQS; boto3 via `asyncio.to_thread`; `_UNSET` sentinel for tri-state params
- `_classify_retailer_result` is the single classifier (batch + stream). Worker scripts MUST `from app import models`. Drift auto-detected in `conftest._ensure_schema`
- fb_marketplace needs Decodo residential w/ scoped routing — see `docs/SCRAPING_AGENT_ARCHITECTURE.md` §C.11

### Phase 3 (quick-ref)
- **External APIs.** eBay Browse (`EBAY_APP_ID`+`CERT_ID`, 2h TTL); Best Buy Products (`BESTBUY_API_KEY`); Decodo Scraper for Amazon (`DECODO_SCRAPER_API_AUTH`); Serper SERP (`SERPER_API_KEY`, top-5, ~$0.001/call); GDPR webhook = GET SHA-256 + POST 204
- **9 active scraped retailers** post-2026-04-18 (lowes + sams_club retired). `*_direct` rows stay `is_active=True` for identity redirects
- **AI resolve (vendor-migrate-1).** `_get_gemini_data` tries `web_search.resolve_via_serper` first (Serper top-5 → Gemini synthesis, `grounded=False, thinking_budget=0, max=1024, temperature=0.1`); soft-falls to grounded Gemini (`thinking_level=ThinkingLevel.LOW` since PR #75) on null/error. `gather(_get_gemini_data, _get_upcitemdb_data)` unchanged. **temperature=1.0 hardcode bug fixed.** Autouse pytest fixture `_serper_synthesis_disabled` patches `resolve_via_serper`→None for every test by default. Blended cost ~$0.0070/call avg (~5.7× cheaper than grounded-only)
- **Search v2 cascade.** normalize → Redis → DB pg_trgm@0.3 → Tier 2 `gather(BBY, UPCitemdb)` → Tier 3 Gemini. Tiered merge strong/weak (`_STRONG_CONFIDENCE=0.55`), tiebreaks `DB>BBY>UPCitemdb>Gemini`. `cascade_path` on response. `?query=` override on `/prices/{id}/stream`
- **Relevance pack (#62, #67, cat-rel-1-followups, apple-variant).** Price-outlier <40% median on `{ebay,fb}`; FB soft model gate (overlap≥0.6); model regexes incl. `\d{5}[A-Z]{0,2}` w/ unit-suffix lookahead; `_query_strict_specs` voltage/4+digit; brand-bleed gate; Rule 3 / 3b brand fallbacks; Rule 2c chip / 2d display-size disagreement-only + telemetry; post-resolve L4 `_resolved_matches_query`
- **M6 Recommendation (3e + interstitial-parity-1).** Deterministic. `gather`s Prices+Identity+Cards+Portals, <150 ms p95. `final = base − identity`; rebates on post-identity. Brand-direct ≥15 % at `*_direct`. 15-min Redis cache key `:c<sha1>:i<sha1>:p<sha1>:v5` + optional `:q<sha1>`. `portal_by_retailer` filtered by active memberships. iOS hero failures → `RecommendationState.insufficientData`
- **Inflight cache (#73).** `prices:inflight:{pid}[:scope]` Redis hash, 120s TTL. Pre-`yield` write; `EXISTS`+`HGETALL` distinguishes missing vs empty. `_inflight` marker skips M6 cache write. `query_override` adds `:q<sha1>`. Soft-fails Redis
- **Purchase Interstitial (3f + interstitial-parity-1).** `PurchaseInterstitialSheet` from hero CTA + row taps; per-retailer `estimated_savings`; `discount_programs.scope ∈ {product,membership_fee,shipping}` (0009). `priceBreakdownBlock` renders `StackingReceiptView` whenever `receipt.hasAnyDiscount`, independent of card guidance
- **Benefits Expansion.** +10 student-tech + Prime YA (`scope='membership_fee'`); `is_young_adult` (0010); `_dedup_best_per_retailer_scope`; `/resolve`→`/resolve-from-search` fallback
- **FB Marketplace location resolver (0011).** Numeric FB Page ID end-to-end; 3-tier Redis(24h)→PG→live; GCRA + singleflight. iOS `Stored.fbLocationId` bigint-safe String. Followups: dedicated `fb_location_resolve` bucket (5/min); DTO collapses engines to `live`; 3-way decision (VALIDATED>FALLBACK>REJECTED)
- **tier2-ebay-search (#50).** 4 env flags default OFF. Browse omits `gtin` even w/ EXTENDED — `SKIP_UPC` is de facto
- **Portal monetization (3g-A/B).** 0012 `portal_configs`. 5-step CTA tree: feature-flag → 24h staleness → MEMBER_DEEPLINK → SIGNUP_REFERRAL w/ FTC → GUIDED_ONLY. Resend alerting: 3 consecutive empty → email, 24h throttle. **Codable pitfall:** `.convertFromSnakeCase` → `portalCtas` (lowercase `as`). **ProfileView dual-branch pitfall:** grep BOTH `ScrollView` branches when adding a section
- **demo-prep-1 (#63).** Explicit states over silent-nil. Envelope decode fix in `APIClient.decodeErrorDetail`. `UnresolvedProductView` + `TabSelectionAction`. `LOW_CONFIDENCE_THRESHOLD=0.70` 409 gate + `/confirm` marks `user_confirmed`. First repo-root Makefile
- **savings-math-prominence (#64).** Shared `StackingReceiptView` across hero + interstitial. `Money.format` no `.00`. `error.message` re-toned. `make demo-check --no-cache --remote-containers=ec2`. `make verify-counts`
- **sim-edge-case-fixes-v1 (#65).** Pattern-UPC reject `^(\d)\1{11,12}$` pre-Gemini. `RequestValidationError` rewraps Pydantic 422 → canonical envelope. SearchView `.searchable` sync setter; manual-UPC `.numberPad` + digit-filter
- **Bench framework (#74–#77).** `scripts/bench_vendor_compare.py` + `_bench_serper.py` + `bench_data/test_upcs*.json` + `--catalog` flag; `bench_prevalidate_v2.py` dual-filter (UPCitemdb + Gemini agreement). **Find:** small thinking budgets (256/512/1024) HURT recall on clean SERP — budget=0 forces direct snippet extraction
- **M14 misc-retailer slot (#80, #81).** `_serper_shopping_fetch` + flat `m14_misc_retailer` module. `KNOWN_RETAILER_DOMAINS` drops the 9 scraped retailers + `*_direct` mirrors. **Inflight TTL 30s** (single-call Serper, not SSE). Cap 3 rows. Tap → Google Shopping in `SFSafariViewController`. `MISC_RETAILER_ADAPTER='disabled'` default. **iOS gate `isMiscRetailerEnabled` Debug-default-ON / Release-default-OFF**, gated on `defaults === UserDefaults.standard`. **`ai/web_search.py` split trigger** ~300 LOC OR 5th Serper path → `serper_resolve.py` + `serper_shopping.py` + shared `serper_client.py`
- **Autocomplete + noise-filter + prompt trilogy (3o-A/B/C).** Vocab 4,448→15,000 terms via 8-scope Amazon sweep (drops `is_electronics()` filter). Tier-2 noise denylist split into hard (11 tokens) / soft (`case`+`charger`, query-opt-out) / accessor-context (electronics-parent gate). `UPC_LOOKUP_SYSTEM_INSTRUCTION` rewritten category-agnostic (3,489→4,310 chars; 6 mixed-vertical examples). `tests/ai/test_upc_lookup_prompt.py` anti-condensation suite (8 tests). Trilogy makes resolve+search+autocomplete category-agnostic end-to-end
- **Dark-mode contrast tokens (#93).** `barkainOnPrimaryContainer` is text-on-`PrimaryContainer` (always-gold `BestBarkainBadge` pill) — stays dark in both modes (`#694700` light / `#2A1C00` dark). `barkainOnPrimaryFixed` (NEW) is text-on-`PrimaryFixed` (cream→warm-dark capsule) — flips for contrast (`#694700` light / `#F9B12D` dark). `barkainHeroSurface` (NEW) is the recommendation-hero fill — pre-blended cream-gold light (`#F7D18C`) and deep warm-brown dark (`#2A1F0E`) so gold accents pop instead of fighting a translucent-gold background. **Pattern:** when a token is used on two visually different backgrounds (always-saturated vs theme-flipping), split it — one shared "on" name fights itself in dark mode.
- **Provisional-resolve (open).** When `/resolve-from-search` Gemini + UPCitemdb both return null AND `settings.PROVISIONAL_RESOLVE_ENABLED=True`, persist a `Product` with `upc=NULL`, `source="provisional"`, `source_raw["provisional"]=True` + `["search_query"]` + `["gemini_no_upc_reason"]`. Only the upstream-empty branch converts — the cache-mismatch and post-resolve relevance-mismatch branches still raise `UPC_NOT_FOUND_FOR_PRODUCT` so the relevance gates keep authority over canonical rows. The 409 confidence gate fires BEFORE provisional persistence so a low-confidence tap still surfaces the iOS confirmation sheet (no row written until the user confirms). New `Product.match_quality` JSONB-derived `@property` reads `source_raw["provisional"]`; ships `"exact" | "provisional"` on `ProductResponse` so iOS can branch without a column migration. **M2 server-side query injection:** `get_prices` + `stream_prices` auto-inject `query_override = product.name` for provisional rows so the bare-name cache scope, container query, and per-container product_name hint all key off the user's intent. Caller-supplied override still wins. **M6 cache skip:** `_gather_inputs` tags `prices_payload["_provisional"] = True` when `product.source == "provisional"`; the existing inflight-skip branch was renamed `recommendation_skip_cache_write` and now covers both inflight + provisional payloads — operator log line carries `inflight=<bool> provisional=<bool>` for attribution. **7-day dedup window:** `_persist_provisional` SELECTs an existing matching `(name, brand, source='provisional')` row created in the last 7 days and reuses its UUID instead of inserting; re-tapping the same dead-end query in a session keeps the iOS hero stable, narrow enough that a stale row gets replaced after a week of upstream upgrades. **iOS hero banner:** `RecommendationHero` gains `isProvisional`/`searchQuery` props; banner reads "Best results for \"<query>\" — exact match unavailable.", eyebrow downgrades to muted "APPROXIMATE MATCH" with a magnifying-glass icon (no gold pawprint). `SearchView`'s `recentlyScanned.record` skips provisional rows so the rail stays canonical. **`query: String?` plumbing:** new field on `ResolveFromSearchRequest`, `Endpoint.resolveFromSearch`, `APIClientProtocol.resolveProductFromSearch`, `MockAPIClient`, `BarePreviewAPIClient`. Swift protocol default-args don't propagate through protocol-typed call sites — every conformer + holder passes explicitly (the same gotcha thumbnail-fallback hit). **Live verification (2026-05-01):** Festool TS 60 KEBQ-Plus 577419 (yesterday's 404 sweep) — 200 with `match_quality: "provisional"`, M2 stream returned a real $700 used FB Marketplace listing while other retailers correctly `no_match` at the relevance-gate level. **Pattern:** dark-launch behavior changes that touch a hot 4xx path. The schema additions (`match_quality`, `query`) ship safely with the flag still off; the flag flips only after canonical-path tests confirm zero behavior change with `False`.
- **Last-resort search thumbnail fallback (#94).** Two-pass cascade after `_collapse_variants` in `ProductSearchService.search`: eBay Browse `lookup_thumbnail` (free, `m2_prices/adapters/ebay_browse_api.py`) → Serper `/images` `lookup_thumbnail_via_serper` (paid ~$0.001/call, `ai/web_search.py`). Per-row parallel via `asyncio.gather(return_exceptions=True)`, soft-fail. `SEARCH_THUMBNAIL_FALLBACK` default ON. **Why `/images` not `/search`:** Serper `/search` only carries `imageUrl` when Google detected an og:image preview — for niche queries it's often missing. `/images` is purpose-built (Google Images search) and reliably returns hosted image URLs. Caught in headed-sim testing during this PR. **Resolve wire-through:** `fallback_image_url` field on `ProductResolveRequest` + `ResolveFromSearchRequest` + `ResolveFromSearchConfirmRequest`; iOS `SearchViewModel`/`OptimisticPriceVM` forward `result.imageUrl`; backend `_persist_product` uses it ONLY when no upstream resolver supplied an image, through the same `_KNOWN_BAD_IMAGE_HOSTS` filter. Persisted onto `Product.image_url` so the loading state + Recently Sniffed inherit the user-tapped thumbnail. **Pattern:** Swift protocol default-args don't apply through protocol calls — when adding optional params to an `APIClientProtocol` method, every call site holding the protocol type must pass the param explicitly (only the concrete-type calls get the default).
- **Gemini UPC system-instruction rewrite (3o-C).** `UPC_LOOKUP_SYSTEM_INSTRUCTION` rewritten category-agnostic (3,489→4,310 chars). 9-step skeleton + JSON contract (`device_name`/`model`/`reasoning`) preserved verbatim; 6 mixed-vertical examples (iPad / KitchenAid mixer / Royal Canin / DeWalt drill / Greenworks mower / iPhone). `build_upc_retry_prompt` → "all retail categories"; `build_upc_lookup_prompt` byte-unchanged. **Anti-condensation regression suite** (`tests/ai/test_upc_lookup_prompt.py`, 8 tests) pins markers / length ≥3,000 / 9 steps in order / all 6 examples / JSON contract / electronics-only-removal / retry rewrite / builder-byte-stable — Phase 1 L13 (agent-condensing) is the load-bearing failure this catches. **Pre-Fix #1 outcome:** UPC `088381675681` (Makita prefix) misresolving as "Apple MacBook Pro 14-inch M3 Pro" under old prompt — fixed under new, re-resolves to "Makita 18V LXT XFD10Z Driver-Drill". **Mini-bench** (`scripts/bench_grounded_3o_c.py`, 5 UPCs × old+new = 10 calls): pass criterion `no_electronics_regression=True` met. Grounded-only is noisy at n=5 by design (production hot path is Serper-then-grounded post-vendor-migrate-1). **Gemini implicit cache:** byte-edit invalidates prefix → one-shot ~700–900 token tax on first deploy call, steady-state implicit-cache restores; `caches.create()` not adopted (out of scope). **Headed sim smoke surfaced `3o-C-L1-fabricated-upc-tap`** — pre-existing since 3c, amplified by 3o-C breadth (Tier 3 Gemini search ships fake `primary_upc`, iOS taps it, grounded resolve hallucinates an unrelated product, e.g. rustoleum-tap → Tide Pods). Closes the 3o-A + 3o-B + 3o-C trilogy — resolve + search + autocomplete now category-agnostic end-to-end.
- **Token-overlap relevance gate (closes `3o-C-L1`).** Re-diagnosed during the 2026-05-01 non-headed sweep: query `Apple Watch Ultra 2 49mm Natural Titanium GPS Cellular` → grounded Gemini `_lookup_upc_from_description` returned a real (not fabricated) MacBook Air UPC `195949036323`; the post-resolve `_resolved_matches_query` gate let it through because (a) brand-token = `"apple"` was present in both haystacks, (b) strict-spec gate had no anchor (no voltage, no 4+digit pure-numeric — `49mm` doesn't match `^\d{4,}$`). **Fix:** add a 3rd gate — when query has ≥2 meaningful tokens (`_meaningful_query_tokens`: ≥3 chars, not in `_RELEVANCE_STOPWORDS`), require ≥2 to substring-match the haystack. For Apple-Watch-vs-MacBook-Air the meaningful set is `[apple, watch, 49mm, natural, titanium, gps, cellular]` (7 tokens); only `apple` appears in MacBook haystack → 1<2 → reject. **Edge case guard:** when the meaningful set has <2 tokens (e.g. `iPhone 16 Pro` → `[iphone]` after stopword + length filtering), the new gate is inert and brand+strict-spec remain authoritative — single-iconic-name resolves aren't penalized. **Reused** `_meaningful_query_tokens` from `search_service.py` so search-time and resolve-time tokenize identically. **Live verification (post-fix):** same Apple Watch Ultra 2 query — (a) cache-hit branch invalidates the bad cached UPC and 404s with `gemini_reasoning` propagated; (b) fresh-upstream branch: Gemini returned no UPC + UPCitemdb rate-limited → upstream-empty branch fires `_persist_provisional` → 4 real Apple Watch Ultra 2 prices in M2 (Walmart pre-owned $341.96, eBay used $367.99, eBay open-box $419.95, FB used $650) + 3 misc rows (Unclaimed Baggage / PayMore Chelsea / Instacart). **Pattern:** the relevance-gate name "_resolved_matches_query" is the contract — defense-in-depth lives here, not in the LLM prompt. When the test cases for a 2-gate function start growing examples that pass both gates wrong, add a 3rd gate before tightening prompts. **Note:** the original CLAUDE.md description called this "fabricated UPC" — the real mechanism is "wrong-product UPC" (the UPC is real, the product mapping is wrong). Renamed in spirit; kept the issue ID stable for grep-history.
