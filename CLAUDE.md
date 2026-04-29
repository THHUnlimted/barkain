# CLAUDE.md — Barkain

> **Purpose:** Root orientation for AI coding agents. This file alone should let a new session understand the project, find anything, and follow conventions.
> **Last updated:** 2026-04-28 (v5.43 — Step 3o-B Tier-2 noise filter narrowing. 14-entry `_TIER2_NOISE_CATEGORY_TOKENS` split into three pools: hard (11, unconditional), soft (`case` + `charger`, query-opt-out via `_SOFT_NOISE_QUERY_OPT_OUT`), and accessor-context (`accessor` + `_ACCESSOR_CONTEXT_TOKENS`). Resolves Discovery v1 §B3 cat-litter false-negative; proactively addresses 3o-A vocab's `iphone case`/`anker charger` predictable false-negatives. `monitor` and `screen protector` held in hard pool per wait-and-see. New `_classify_tier2_noise` powers per-pool drop counts in escalation log line for observability. Backend tests +19 (754→773 passed; 8 skipped → 781 collected). Title denylist + brand-bleed/strict-spec/model-code gates untouched. Per-step detail in `docs/CHANGELOG.md`.)

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
| demo-prep-1 | F&F: 422→`insufficientData` + envelope fix; `UnresolvedProductView`; 409 confidence + `/confirm`; first Makefile | +12 | +11 | #63 |
| savings-math-prominence | Hero invert; shared `StackingReceiptView`; `error.message` audit; `make verify-counts` | +4 | +10 | #64 |
| sim-edge-case-fixes-v1 | Pattern-UPC reject; canonical 422 handler; SearchView clear-text race; `.numberPad` + digit-filter | +3 | — | #65 |
| interstitial-parity-1 | `priceBreakdownBlock` independent of `hasCardGuidance`; M6 filters portals by active memberships | +1 | +3 | #66 |
| category-relevance-1 | 5 fixes from 15-SKU sweep: FB overlap 0.4→0.6; appliance regex; brand-bleed gate; Rule 3/3b | +13 | — | #67 |
| cat-rel-1-followups | L4 post-resolve gate; L1 `_extract_brand_from_url`; L2 Gemini-reasoning logs; L3 digit-led regex + unit-suffix lookahead | +22 | — | TBD |
| apple-variant-disambiguation | Rule 2c chip / 2d display-size disagreement-only gates + telemetry | +14 | — | TBD |
| inflight-cache-1 | `prices:inflight:{pid}[:scope]` Redis hash, 120s TTL; pre-yield write; L1 M6 skips cache, L2 `query_override` `:q<sha1>` segment | +17 | — | #73 |
| bench/vendor-compare-1 | 600-call diagnostic, 6 configs. DEFER (catalog contaminated). Opens `bench-cat-1` | +9 | — | #74 |
| feat/grounded-low-thinking | grounded leg → `ThinkingLevel.LOW`. Same recall, ~37% cheaper | +2 | — | #75 |
| bench/vendor-compare-2 | Clean-catalog re-run; B and E tie 24/28. MIGRATE B→E. Opens `bench-cat-2` | +0 | — | #76 |
| bench/vendor-migrate-1 | UPC resolve grounded-only → Serper-then-grounded. temperature=1.0 hardcode fixed. 100% vs 53% recall, p50 −47%, ~36× cheaper. Opens `vendor-migrate-1-L1` | +17 | — | #77 |
| feat/thumbnail-coverage | End-to-end image plumbing: Serper/UPCitemdb passthrough, scraper backfill, `product_image_url` on done, iOS `ProductCard` `fallbackImageUrl` chain. Opens `thumbnail-coverage-L1`–`L3` | +1 | +1 | #79 |
| 3n (M14 misc-retailer slot) | New `m14_misc_retailer` + `_serper_shopping_fetch`. KNOWN_RETAILER filter, top-3, Redis 6h, 30s inflight. 5 adapters via `MISC_RETAILER_ADAPTER`. iOS `MiscRetailerCard`. Bench harness + 50-SKU pet panel. Opens `misc-retailer-L1` | +46 | +4 | #80 |
| 3n-debug-on | `isMiscRetailerEnabled` Debug-default-ON / Release-default-OFF; standard-suite-gated so tests stay default-OFF. Canary lever now server-side only | — | +13/−2 | #81 |
| 3o-A | Autocomplete vocab expansion: drop `is_electronics()` filter; sweep 6 default Amazon scopes (aps + electronics + grocery + pet-supplies + tools + beauty) + 2 probe-admitted extras (automotive + office-products; HPC rejected); `asyncio.gather` parallelizes sweep_source; `--max-terms` 5K→15K; bundle `version=2`. Vocab 4,448→15,000 / 128 KB→470 KB. iOS code unchanged | +6/−9 collected | 0 | #84 |
| 3o-B | Tier-2 noise filter narrowing: 14-entry category denylist split into hard (11, unconditional) / soft (`case` + `charger`, query-opt-out) / accessor-context (electronics-parent gate); resolves Discovery v1 §B3 cat-litter false-negative + 3o-A predictable false-negatives. `_classify_tier2_noise` adds per-pool breakdown to escalation log. Title denylist + query-aware gates untouched | +19 | 0 | TBD |

**Test totals:** 773 backend passed + 8 skipped (781 collected) + 207 iOS unit + 6 iOS UI (with experiment flags off — see L-Experiment-flags-default-off). 3o-B added +19 backend tests (754→773 passed). 3o-A swung the count by −3 collected (parametrize collapse: dropped 9 `test_electronics_filter` cases, added 6 new). `ruff check` clean. `xcodebuild` clean.

**Migrations:** 0001 (initial, 21 tables) → 0002 (price_history composite PK) → 0003 (is_government) → 0004 (card catalog unique index) → 0005 (portal bonus upsert + failure counter) → 0006 (`chk_subscription_tier` CHECK) → 0007 (pg_trgm + trgm GIN idx) → 0008 (`affiliate_clicks.metadata` JSONB) → 0009 (`discount_programs.scope` — product / membership_fee / shipping) → 0010 (`is_young_adult` on `user_discount_profiles`) → 0011 (`fb_marketplace_locations` — city→FB Page ID cache w/ tombstoning) → 0012 (`portal_configs` — display + signup-promo + alerting state for shopping portals). Drift marker in `tests/conftest.py::_ensure_schema` checks `portal_configs`.

> Per-step file inventories, detailed test breakdowns, and full decision rationale: see `docs/CHANGELOG.md`.

---

## Known Issues

> Full history in `docs/CHANGELOG.md`. Only items affecting active development are listed here.

| ID | Severity | Issue | Owner |
|----|----------|-------|-------|
| SP-L1-b | HIGH | Leaked PAT `gho_UUsp9ML7…` stripped from EC2 (2i-d) but not yet revoked in GitHub UI | Mike |
| 2i-d-L3 | LOW | `ebay_new` / `walmart` still flagged `selector_drift`; `ebay_used` heal_staged OK | Phase 3 |
| 2i-d-L4 | MEDIUM | Watchdog heal at `workers/watchdog.py:251` passes `page_html=error_details`; needs browser fetch in heal path | Phase 3 |
| v4.0-L2 | MEDIUM | Sub-variants without digits (Galaxy Buds Pro 1st gen) still pass token overlap | Phase 3 |
| 2h-ops | LOW | SQS queues have no DLQ wiring; per-portal fan-out deferred | Phase 3 ops |
| noise-filter-L1 | MEDIUM | `_TIER2_NOISE_CATEGORY_TOKENS` lacks "game download" — tiered merge promotes digital-game BBY rows ("Switch OLED" → 422) | Phase 3 |
| cat-rel-1-L2-ux | LOW | iOS could surface Gemini reasoning on `/resolve-from-search` 404s (Gemini correctly refused) instead of generic "couldn't find" — needs error-envelope plumbing + new iOS state | Phase 3 |
| vendor-migrate-1-L1 | LOW | Serper coverage tail: cold-path None falls back to grounded Gemini ($0.040/call, ~3s p50). Watch `Serper synthesis returned null` log frequency; if >15% fallback, options: multi-query / top-N up to 10 / alternate SERP | Phase 3 ops |
| thumbnail-coverage-L1 | LOW | Tier 3 Gemini search rows show box-icon placeholder (no image field). Defer until miss-rate is measured | Phase 3 |
| thumbnail-coverage-L2 | LOW | `RecentlyScannedStore` caches `imageUrl` at first-resolve time; old entries self-heal on re-tap. Bulk reset overkill | iOS |
| thumbnail-coverage-L3 | LOW | Backfill only fires when `Product.image_url IS NULL`; broken hotlink-blocked CDNs (demandware 403) stick. iOS papers over via `fallbackImageUrl`. Long-term: known-bad-host blocklist or HEAD-check before persist | Phase 3 |
| misc-retailer-L1 | LOW | Weekly `make bench-misc-retailer` post-canary; alert on `panel_below_alert` (<75% × 2). Watch Serper cold-path nulls in `barkain.m14.serper_shopping` | Phase 3 ops |

---

## What's Next

1. **Phase 2 CLOSED** — `v0.2.0` tagged (2026-04-16). Outstanding: revoke leaked PAT `gho_UUsp9ML7…` in GitHub UI (SP-L1-b, Mike).
2. **Phase 3:** all steps in the table are ✅ shipped. **Active follow-ups:** physical-iPhone app-tests (cold-cache p50 ~3s → ~1.5s); monitor `vendor-migrate-1-L1`; **3n misc-retailer canary** ($50 Starter Serper → `make bench-misc-retailer` → if ≥80% pass, flip `MISC_RETAILER_ADAPTER=serper_shopping` 5%→50%→100% over 48h; iOS gate is server-side only now); weekly bench cron; resurrect stashed iOS provisional `/recommend` (`git stash list | grep "PR-3 provisional"`); AppIcon PNGs (Figma); prod FB seed; eBay-Tier-2 graduation; snapshot-baseline re-record (sim-26.3 drift); F#1c (Continue via portal when membership matches `winner.portal_source`); `cat-rel-1-L2-ux`; watch `apple_variant_gate_rejected`. **Next planned:** 3o-C (Gemini system-instruction rewrite). **Remaining:** 3h Vision · 3i receipts · 3k savings · 3l coupons · 3m hardening → `v0.3.0`
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
- **M14 misc-retailer slot (#80, #81).** `_serper_shopping_fetch` (thumbnail-stripped, soft-fail) + flat `m14_misc_retailer` module (no `cache.py`/`filters.py`). `KNOWN_RETAILER_DOMAINS` drops the 9 scraped retailers + display variants + `*_direct` mirrors. **Inflight TTL 30s** (not 120s — single-call Serper, not SSE fan-out). Cap 3 rows server + iOS. Tap → Google Shopping in `SFSafariViewController`. `MISC_RETAILER_ADAPTER='disabled'` default; canary lever is server-only. **iOS gate (`isMiscRetailerEnabled`) Debug-default-ON / Release-default-OFF**, gated on `defaults === UserDefaults.standard` so tests stay default-OFF. Z-standby stub raises `NotImplementedError` so accidental flips are loud; bench trigger `panel_below_alert` (<75% × 2 weeks). **`ai/web_search.py` ~316 LOC** hosts 4 Serper paths (`_serper_fetch` + `resolve_via_serper` + `_first_image_url` + `_serper_shopping_fetch`); split trigger ~300 LOC OR 5th path → `serper_resolve.py` + `serper_shopping.py` + shared `serper_client.py`
- **Autocomplete vocab expansion (3o-A).** Drops the `is_electronics()` term-content filter outright; load-bearing work is now scope diversity. `scripts/generate_autocomplete_vocab.py` defaults to 6 Amazon scopes (`aps`, `electronics`, `grocery`, `pet-supplies`, `tools`, `beauty`); 3 probe-gated extras (`automotive`, `health-personal-care`, `office-products`) auto-admit when `_probe_scope` averages ≥5 suggestions across `(ca, pa, tir)`. `sweep_all_sources` parallelizes per-source sweeps via `asyncio.gather(return_exceptions=True)` so one source dying doesn't kill the run. `--max-terms` 5K→15K; bundle `version=2` (schema on terms unchanged: `{t, s}`). 4,448 → 15,000 terms / 128 KB → 470 KB / 12-min wall-clock. iOS code untouched — `AutocompleteService` decode handles arbitrary N. Dropped fields: `stats.after_electronics_filter` (filter retired). Added: `stats.scope_probes` + `stats.scope_probes_admitted`
- **Tier-2 noise filter narrowing (3o-B).** Single 14-entry `_TIER2_NOISE_CATEGORY_TOKENS` denylist → three behavior pools: `_TIER2_HARD_NOISE_CATEGORY_TOKENS` (11; warrant/applecare/subscription/gift card/specialty gift/protection/monitor/physical video game/service/digital signage/screen protector — unconditional drop), `_TIER2_SOFT_NOISE_CATEGORY_TOKENS` (`case`, `charger` — drop unless `_SOFT_NOISE_QUERY_OPT_OUT` matches; opts: `{case, cases}` and `{charger, chargers, charging}`), and accessor-context (`accessor` substring drops only when category also names an electronics parent from `_ACCESSOR_CONTEXT_TOKENS`: gaming/controller/console/phone/smartphone/tablet/laptop/computer/tv/video game/camera/drone/headphone/earbud/keyboard/mouse). **Resolves cat-litter false-negative** (Discovery v1 §B3 + §H3) — `Litter Boxes & Accessories` no longer drops on the bare `accessor` substring. **Proactively addresses 3o-A predictable false-negatives** — `iphone case` / `anker charger` queries now opt out of soft-pool drops. `monitor` and `screen protector` held in hard pool per wait-and-see (revisit if telemetry surfaces real false-negatives). Sibling `_classify_tier2_noise` returns the reason string (`hard_category` / `soft_category` / `accessor_context` / `title` / `query_check`) — used only by the escalation log line for per-pool drop counts. Title denylist + brand-bleed/strict-spec/model-code gates untouched. iOS sim smoke (cat litter unscented / iphone 17 pro max case / anker portable charger / ps5 controller) passed end-to-end.
