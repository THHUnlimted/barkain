# Barkain — Phase Roadmap

> Source: Project Planning Questionnaire + Architecture Sessions, March–April 2026
> Scope: All planned phases, current position, infrastructure dependencies
> Last updated: 2026-05-01 (v3.11 — `feat/provisional-resolve` (open) lands as a dark-launched fallback path on `/resolve-from-search`: when Gemini device→UPC + UPCitemdb keyword search both return null, persist a best-effort `Product` with `upc=NULL`, `source="provisional"`, `source_raw["provisional"]=True` + `["search_query"]` instead of raising `UPC_NOT_FOUND_FOR_PRODUCT`. Gated by new `PROVISIONAL_RESOLVE_ENABLED` flag (default OFF) so schema/property additions ship safely with behavior unchanged until the flag flips. New `Product.match_quality` JSONB-derived property (`exact`/`provisional`) on `ProductResponse`. M2 `get_prices`/`stream_prices` auto-inject `query_override = product.name` for provisional rows so the bare-name cache scope wins. M6 `recommendation_skip_cache_write` log line generalized to cover both inflight + provisional payloads. 7-day dedup window on `(name, brand, source='provisional')` keeps re-tapped dead-end queries pinned to one row. iOS `RecommendationHero` adds soft "Best results for \"<query>\"" banner + downgraded muted-grey "APPROXIMATE MATCH" eyebrow when `product.isProvisional`; `SearchView` skips provisional from Recently Sniffed; new `query: String?` threaded through `Endpoint`/`APIClientProtocol`/`MockAPIClient`/`BarePreviewAPIClient`. Backend 806→815 (+9 tests). Live-verified Festool 577419 (yesterday's 404 sweep) → provisional row → FB Marketplace $700 used listing while other retailers correctly `no_match` at the relevance gate. **`feat/search-thumbnail-fallback` (#94)** still open; **`fix/dark-mode-contrast` (#93)** merged 2026-04-30.)
>
> For per-step file inventories and decision rationale, see `docs/CHANGELOG.md`.

---

## Current Position

**Phase 0 (Planning) — COMPLETE**
**Step 0 (Infrastructure Provisioning) — COMPLETE** (2026-04-06)
**Step 1a (Database Schema + FastAPI Skeleton + Auth) — COMPLETE** (2026-04-07)
**Step 1b (M1 Product Resolution + AI Abstraction) — COMPLETE** (2026-04-07)
**Step 1c (Container Infrastructure + Backend Client) — COMPLETE** (2026-04-07)
**Step 1d (Retailer Containers Batch 1) — COMPLETE** (2026-04-07)
**Step 1e (Retailer Containers Batch 2) — COMPLETE** (2026-04-07)
**Step 1f (M2 Price Aggregation + Caching) — COMPLETE** (2026-04-08)
**Step 1g (iOS App Shell + Scanner + API Client + Design System) — COMPLETE** (2026-04-08)
**Step 1h (Price Comparison UI) — COMPLETE** (2026-04-08)
**Step 1i (Hardening + Doc Sweep + Tag v0.1.0) — COMPLETE** (2026-04-08)
**Phase 1 (Foundation) — COMPLETE**
**Step 2a (Watchdog Supervisor Agent + Health Monitoring + Shared Base Image) — COMPLETE** (2026-04-10)
**Walmart HTTP Adapter + Firecrawl/Decodo Routing — COMPLETE** (2026-04-10) — paradigm shift: walmart now uses `WALMART_ADAPTER={container,firecrawl,decodo_http}` routing instead of the browser container. Demo runs through Firecrawl, production flips to Decodo residential proxy with one env var change. 10 other retailers unchanged. See `docs/ARCHITECTURE.md#walmart-adapter-routing-post-step-2a-paradigm-shift` and `docs/SCRAPING_AGENT_ARCHITECTURE.md` Appendices A–C.
**Scan-to-Prices Live Demo (3 retailers) — COMPLETE** (2026-04-10) — first-ever live end-to-end run on a physical iPhone. Amazon + Best Buy via agent-browser containers on EC2 t3.xlarge (reached from Mac over SSH tunnel), Walmart via Firecrawl v2 adapter. 7 live-run bug fixes landed on `phase-2/scan-to-prices-deploy` (see `Barkain Prompts/Error_Report_Scan_to_Prices_Deployment.md`): fd-3 stdout pollution, 180s EXTRACT_TIMEOUT baseline, Xvfb lock cleanup, Firecrawl v2 `location.country` schema drift, `.env` overrides rot (`CONTAINER_URL_PATTERN`, `CONTAINER_TIMEOUT_SECONDS`), zero-price listing guard, iOS URLSession 240s timeout. See `docs/SCRAPING_AGENT_ARCHITECTURE.md` Appendix D for the extract.sh conventions now required of every retailer container.
**Step 2b (Demo Container Reliability) — COMPLETE** (2026-04-11), **Step 2b-val Live Validation — PASSED** (2026-04-12), **Post-2b-val Hardening — COMPLETE** (2026-04-12), **Step 2b-final Close-Out — COMPLETE** (2026-04-13)
**Step 2c (SSE Streaming) — COMPLETE** (2026-04-13), **Step 2c-fix (iOS byte-level SSE splitter) — COMPLETE** (2026-04-13)
**Step 2d (M5 Identity Profile + Discount Catalog) — COMPLETE** (2026-04-14)
**Step 2e (M5 Card Portfolio + Reward Matching) — COMPLETE** (2026-04-14), **Step 2e-val Smoke Test — PASSED** (2026-04-14, 0 bugs)
**Step 2f (M11 Billing — RevenueCat + Feature Gating) — COMPLETE** (2026-04-14)
**Step 2g (M12 Affiliate Router + In-App Browser) — COMPLETE** (2026-04-14)
**Step 2h (Background Workers — SQS + Price Ingestion + Portal Rates + Discount Verification) — COMPLETE** (2026-04-15)
**Phase 2 (Intelligence Layer) — COMPLETE** (awaiting `v0.2.0` tag via Step 2i)
**Step 2i-a (CLAUDE.md compaction + doc sweep) — COMPLETE** (2026-04-15, PR #17), **Step 2i-b (Code quality sweep) — COMPLETE** (2026-04-15, PR #18), **Step 2i-c (Operational validation + Phase 2 consolidation) — COMPLETE** (2026-04-15, PR #19), **Step 2i-d (Operational validation — EC2 redeploy + Watchdog live + BarkainUITests + path-bug fix) — COMPLETE** (2026-04-15)
**Tagged releases:** v0.1.0 (Phase 1)

---

## Step 0: Infrastructure Provisioning (Before Any Code)

> **Goal:** Every service the coding agent needs to connect to is live and accessible. No code is written in this step — it's pure setup.
> **Owner:** Developer (Mike), not the coding agent

### Pre-Requisites Already Complete
- [x] Apple Developer Program enrolled
- [x] Clerk Pro subscription active

### Sign-Ups (Instant Approval)

| Service | Action | Time |
|---------|--------|------|
| Best Buy Developer | Sign up, get API key | 10 min |
| eBay Developer Program | Sign up, create app, get Browse API credentials | 30 min |
| Keepa API | Sign up, subscribe ($15/mo), get API key | 10 min |

### Sign-Ups (Days-to-Weeks Approval — Start Now)

| Service | Action | Lead Time |
|---------|--------|-----------|
| Amazon Associates | Apply (requires live website with 10+ posts) | 1-3 weeks |
| eBay Partner Network | Apply (affiliate, separate from Browse API) | Hours to days |
| CJ Affiliate | Apply as publisher, then individually to Best Buy/Walmart/Target merchants | 1-3 weeks per merchant |

### Local Development Environment

| Task | Action |
|------|--------|
| Create GitHub repo | `gh repo create barkain --private` + branch protection + CI stubs |
| Install Docker Desktop | Verify `docker compose` works |
| Create `docker-compose.yml` | PostgreSQL 16 + TimescaleDB, Redis 7. LocalStack deferred to Phase 2 |
| Create `.env.example` | All env vars from DEPLOYMENT.md with placeholder values |
| Configure Clerk project | Create "Barkain" project, note publishable + secret keys |
| Install CLIs | `gh`, `ruff`, `swiftlint`, `jq`, `xcodes`, `aws` |
| Set up MCP servers | PostgreSQL MCP, Redis MCP, Context7, Clerk MCP, XcodeBuildMCP |

### Visual Prototype

| Task | Notes |
|------|-------|
| Create static prototype | Minimum: 4 main screens (Scan, Search, Savings, Profile) + recommendation result + loading state |
| Format | HTML/CSS, Figma, or static SwiftUI — committed to repo before Step 1d |

### Definition of Done (Step 0)
- [ ] `docker compose up` starts PostgreSQL+TimescaleDB and Redis
- [ ] `.env.example` has all required variables
- [ ] Clerk project created with keys noted
- [ ] Best Buy, eBay, Keepa API keys obtained (production optimization — not blocking Phase 1)
- [ ] GitHub repo created with branch protection
- [ ] All Day 1 CLIs installed and verified
- [ ] MCP servers configured for Claude Code
- [ ] Visual prototype committed to repo
- [ ] Affiliate applications submitted (don't wait for approval)

---

## Phase 1: Foundation + Scraper Infrastructure + Core Loop (Weeks 1-8) — ✅ COMPLETE

> **Goal:** User scans a barcode in-store and instantly sees prices across retailers, all scraped via agent-browser containers. Prove the core value prop at scale.
> **Tag:** v0.1.0
> **Retailers (9 active — 11 originally shipped):** Amazon, Best Buy, Walmart, Target, Home Depot, eBay (new), eBay (used/refurb), BackMarket, Facebook Marketplace. Lowe's + Sam's Club retired 2026-04-18 (`is_active=False` rows retained for FK integrity; brand-direct `*_direct` retailers remain active as identity-discount redirect targets).
> **Approach:** ALL retailers scraped via agent-browser containers. Free APIs (Best Buy, eBay Browse, Keepa) added as production speed optimization in a later phase.

### Steps

| Step | Scope | Status |
|------|-------|--------|
| 1a | PostgreSQL schema (ALL tables from DATA_MODEL.md), Alembic setup, FastAPI skeleton, Clerk auth, Docker dev environment verification | ✅ |
| 1b | M1 Product Resolution: Gemini API UPC lookup (primary) + UPCitemdb (backup), barcode → canonical product, ai/abstraction.py foundation, Redis caching (24hr TTL) | ✅ |
| 1c | agent-browser container infrastructure: Docker container template, Dockerfile, extraction script architecture (9-step pattern), health monitoring hooks, test fixture framework, container HTTP API (POST /extract) | ✅ |
| 1d | Retailer containers batch 1 (tested scripts): Amazon, Walmart, Target, Sam's Club, Facebook Marketplace — adapt existing tested scripts into container format | ✅ |
| 1e | Retailer containers batch 2 (new scripts): Best Buy, Home Depot, Lowe's, eBay (new + used/refurb), BackMarket — build and test new extraction scripts | ✅ |
| 1f | M2 Price Aggregation: backend service that dispatches to containers in parallel (asyncio.gather), collects results, caches in Redis (6hr TTL), records price_history | ✅ |
| 1g | iOS app shell: TabView navigation (Scan/Search/Savings/Profile), camera permissions, barcode scanner (AVFoundation), APIClient, design system foundation (tokens, core components) | ✅ |
| 1h | Price comparison UI: scan barcode → call backend → display 11 retailer prices with progressive loading, SavingsBadge showing delta, tap to open retailer URL, Best Barkain badge, refresh + scan another | ✅ |
| 1i | Hardening: google-genai migration, integration tests, error handling audit, guiding doc sweep, tag v0.1.0 | ✅ |

### What Phase 1 Establishes
- PostgreSQL on AWS RDS (dev: Docker) with full schema including discount/card/portal tables (empty, ready for Phase 2 seeding)
- FastAPI backend with Clerk auth, rate limiting, structured error handling
- Product resolution service (UPC → canonical product via Gemini API)
- **agent-browser container infrastructure** — Docker container template, retailer extraction scripts (9 active in prod; lowes + sams_club retired 2026-04-18), health monitoring
- Price aggregation from 9 active retailers via parallel container dispatch with Redis caching
- iOS app with working barcode scanner, progressive loading price comparison display
- CI pipeline (GitHub Actions) running pytest + XcodeBuild tests on every PR
- Docker-based local development (PostgreSQL+TimescaleDB, Redis)

### What Phase 1 Does NOT Build
- No identity discounts or card rewards (Phase 2)
- No AI recommendation (Phase 3)
- No subscription billing (Phase 2)
- No background workers (Phase 2)
- No Watchdog self-healing (Phase 2 — scripts monitored manually in Phase 1)
- No free API adapters (production optimization — added later)

---

## Phase 2: Identity Layer + Revenue + Watchdog (Weeks 9-12) — ✅ COMPLETE (awaiting v0.2.0 tag)

> **Goal:** Identity profile, card portfolio, subscription billing, affiliate routing, Watchdog self-healing, and background workers.
> **Tag:** v0.2.0 (pending Step 2i hardening sweep)

### Steps

| Step | Scope | Status |
|------|-------|--------|
| 2a | Watchdog supervisor agent, health monitoring, shared base image, Phase 1 pre-fixes | ✅ (2026-04-10) |
| (interstitial) | Scan-to-Prices Live Demo — first-ever 3-retailer end-to-end run on physical iPhone; 7 live-run bug fixes landed on `phase-2/scan-to-prices-deploy` | ✅ (2026-04-10) |
| **2b** | **Demo Container Reliability: COMPLETE** ✅ (2026-04-11) — cross-validation (Gemini+UPCitemdb second-opinion), relevance scoring (`_score_listing_relevance` 0.0–1.0 with model-number hard gate), Amazon title selector 5-level fallback, Walmart first-party filter, `.env.example` audit (SP-5 post-mortem), fd-3 stdout backfill to remaining 8 retailers, 6 real-API integration tests (`@pytest.mark.integration`). 24 new tests + 6 integration tests with skip guard. **Step 2b-final (2026-04-13):** Gemini `device_name` + `model` output, post-2b-val test coverage (+35 tests → 181 total), `.github/workflows/backend-tests.yml` CI, EC2 deploy MD5 verification, integration conftest `.env` auto-load. F.5 generation-without-digit + GPU-SKU limitations resolved. | ✅ (2026-04-11, closed 2026-04-13) |
| 2b-pre | **BLOCKERS before 2b can start.** (1) Product-match relevance scoring (SP-10): retailer on-site search returns similar-but-not-identical products; `_pick_best_listing` needs a relevance guardrail before any user-facing demo. (2) Gemini UPC accuracy (SP-L4): 3/3 test UPCs resolved wrong, needs UPCitemdb second-opinion fallback or confidence scoring. (3) Rotate leaked GitHub PAT in EC2 git config (SP-L1). (4) Backfill fd-3 stdout convention to the other 8 retailer extract.sh files (SP-L2). (5) Amazon extract.js title selector regression (SP-9). (6) Walmart first-party filter in `_walmart_parser.py` (SP-L5). See `Barkain Prompts/Error_Report_Scan_to_Prices_Deployment.md`. | ✅ (rolled into 2b) |
| 2c | M2 Streaming Per-Retailer Results (SSE) — `GET /api/v1/prices/{id}/stream` replaces 90–120s blocking batch with progressive reveal as each retailer resolves. Backend: `PriceAggregationService.stream_prices()` using `asyncio.as_completed`, new `sse.py` wire-format helper. iOS: `SSEParser` + `AsyncThrowingStream` consumer + in-place `PriceComparison` mutation + batch fallback. **Step 2c-fix** landed the manual byte-level line splitter (`URLSession.AsyncBytes.lines` buffered for small SSE payloads, defeating the progressive UX); fixed IPv6 happy-eyeballs penalty; added `com.barkain.app`/`SSE` os_log category. | ✅ (2026-04-13, PR #8 + PR #10) |
| **2d** | **M5 Identity Profile + Discount Catalog: COMPLETE ✅** (2026-04-14) — first feature that differentiates Barkain from coupon/cashback apps. Migration 0003 adds `is_government` column. Backend `m5_identity/{schemas,service,router}.py` with 4 endpoints and zero-LLM pure-SQL matching < 150ms. `scripts/seed_discount_catalog.py` seeds 8 brand-direct retailers (samsung_direct, apple_direct, hp_direct, dell_direct, lenovo_direct, microsoft_direct, sony_direct, lg_direct) + 52 discount program rows. iOS: `IdentityProfile.swift` model, 3-step `IdentityOnboardingView` (enum-driven wizard), new `ProfileView` with chips summary, `IdentityDiscountsSection` revealed below the retailer list after SSE `done` event. `ScannerViewModel.fetchIdentityDiscounts` fires at two call sites (post-SSE-success AND post-batch-fallback) — never inside `.done` to avoid racing still-streaming events. 30 new backend tests + 7 new iOS tests. | ✅ (2026-04-14) |
| **2e** | **M5 Card Portfolio + Reward Matching: COMPLETE ✅** (2026-04-14) — completes Barkain's "second pillar". `scripts/seed_card_catalog.py` seeds 30 Tier 1 cards across 8 issuers; `scripts/seed_rotating_categories.py` seeds Q2 2026 (Freedom Flex, Discover it — Cash+/Customized Cash remain user-selected only). Backend `m5_identity/card_{schemas,service,router}.py` with 7 endpoints under `/api/v1/cards/*` and zero-LLM pure-SQL matching < 50ms per product. In-code `_RETAILER_CATEGORY_TAGS` map bridges rotating/static category tags to retailer ids. iOS: new `CardReward.swift` models, `CardSelectionView`/`CardSelectionViewModel`/`CategorySelectionSheet`, Profile "My Cards" section, per-retailer card subtitle in `PriceRow`, "Add your cards" CTA in `PriceComparisonView` keyed off `userHasCards`. `ScannerViewModel.fetchCardRecommendations` chains after `fetchIdentityDiscounts` at both call sites. 30 new backend tests + 10 new iOS tests. | ✅ (2026-04-14) |
| **2f** | **M11 Billing: COMPLETE ✅** (2026-04-14) — RevenueCat SDK + RevenueCatUI added via SPM (v5.67.2). New `m11_billing` backend module: `POST /api/v1/billing/webhook` (RevenueCat events with bearer-token auth, idempotency dedup, tier cache bust) + `GET /api/v1/billing/status` (server-authoritative tier). Tier-aware rate limiter: free uses `RATE_LIMIT_GENERAL/WRITE/AI`, pro uses `× RATE_LIMIT_PRO_MULTIPLIER` (default 2). Tier resolved via Redis `tier:{user_id}` cache (60s TTL) → DB fallback → defaults to free on missing user row. Migration 0004 (PF-1) takes ownership of `idx_card_reward_programs_product` from the seed script. iOS: `SubscriptionService` (@Observable wrapper around RC SDK with PurchasesDelegate adapter), `FeatureGateService` (test-seam-friendly @Observable, free=10 scans/day in local TZ + 3 identity discounts max + cards hidden), `PaywallHost`/`CustomerCenterHost` thin wrappers. ScannerViewModel gates scan quota AFTER successful product resolve (no quota burn on resolve failures). PriceComparisonView slices identity discounts to first 3 + `UpgradeLockedDiscountsRow`, hides per-row card subtitles + shows ONE `UpgradeCardsBanner`. Profile gains tier badge + scan tally + Upgrade button + Customer Center NavigationLink for pro users. 14 new backend tests (`test_m11_billing.py`: webhooks × 8, status × 3, rate limiter × 2, migration 0004 × 1) + 10 new iOS tests (`FeatureGateServiceTests` × 8 + 2 ScannerViewModelTests). | ✅ (2026-04-14) |
| **2g** | **M12 Affiliate Router + In-App Browser: COMPLETE ✅** (2026-04-14) — Barkain's commission path. New `m12_affiliate` backend module: `POST /api/v1/affiliate/click` tags + logs, `GET /api/v1/affiliate/stats` groups by retailer, `POST /api/v1/affiliate/conversion` placeholder webhook with optional bearer auth. `AffiliateService.build_affiliate_url` is a pure `@staticmethod`: Amazon → `?tag=barkain-20` (live), eBay (new+used) → rover redirect with `campid=5339148665` (live), Walmart → Impact Radius placeholder (passthrough while `WALMART_AFFILIATE_ID` empty), Best Buy + others → untagged. `affiliate_clicks.affiliate_network='passthrough'` sentinel for untagged entries (NOT NULL column). iOS: new `InAppBrowserView` (`SFSafariViewController` wrapper — cookies shared with Safari so affiliate cookies persist) + `IdentifiableURL` helper. `AffiliateURL.swift` models + `Endpoints.swift` cases + `APIClientProtocol` methods + 6-conformer fanout. `ScannerViewModel.resolveAffiliateURL(for:)` testable seam — calls `getAffiliateURL`, falls back to original URL on any thrown error, never throws. `PriceComparisonView` retailer-row `Button` now fires `Task { browserURL = IdentifiableURL(url: await viewModel.resolveAffiliateURL(for: retailerPrice)) }` — `UIApplication.shared.open` is gone from `Features/Recommendation/*`. `IdentityDiscountsSection` refactored to `onOpen: (URL) -> Void` closure so verification URLs land in the **same** in-app browser sheet but NOT through `/affiliate/click` (verification pages are not affiliate links). `IdentityDiscountCard.resolvedURL` is a new testable computed property. 14 new backend tests (9 pure URL construction + 3 endpoint + 2 conversion webhook) + 6 new iOS tests (3 `ScannerViewModelTests.test_resolveAffiliateURL_*` + 3 `IdentityDiscountCardTests.test_resolvedURL_*`). 266→280 backend / 60→66 iOS. | ✅ (2026-04-14) |
| **2h** | **Background Workers: COMPLETE ✅** (2026-04-14) — operational backbone so data stays fresh without user traffic. LocalStack SQS in docker-compose (dev) + `backend/workers/queue_client.py` async-wrapped boto3 `SQSClient` (LocalStack via `SQS_ENDPOINT_URL`, real AWS via default credentials in prod). `backend/workers/price_ingestion.py` enqueue/process split reuses `PriceAggregationService.get_prices(force_refresh=True)` — zero duplication. `backend/workers/portal_rates.py` scrapes Rakuten (`aria-label` anchor + "was X%" baseline), TopCashBack (`nav-bar-standard-tenancy__value` span), BeFrugal (`txt-bold txt-under-store` span) via `httpx`+`BeautifulSoup` (deliberate deviation from Job 1's agent-browser pseudocode). Chase + Capital One deferred (auth-gated). `portal_bonuses.is_elevated` GENERATED ALWAYS STORED column auto-fires on spikes; `normal_value` preserved across runs except when Rakuten's "was X%" marker overrides. `backend/workers/discount_verification.py` weekly `httpx` GET with mentions-name check and "flagged vs hard-failed" distinction — soft flag never increments `consecutive_failures`; 3 consecutive hard failures flip `is_active=False`. Migration 0005 adds `idx_portal_bonuses_upsert` + `discount_programs.consecutive_failures`. `scripts/run_worker.py` unified CLI mirrors `run_watchdog.py` (argparse + asyncio.run + AsyncSessionLocal). 21 new backend tests (4 SQS via `moto[sqs]` + 4 price ingestion + 6 portal rates (parsers + normalize + 2 upsert) + 7 discount verification via `respx`). iOS untouched. 280→301 backend tests. | ✅ (2026-04-14) |
| 2i-a | Hardening: CLAUDE.md compaction + guiding-doc sweep + `.env.example` audit | ✅ (2026-04-15, PR #17) |
| 2i-b | Hardening: code quality, dead-code removal, renames, dedup extraction (`_classify_retailer_result`), `subscription_tier` CHECK constraint (migration 0006), `DEMO_MODE` rename. Group E (PreviewAPIClient consolidation) skipped — only 1 inline stub exists, no consolidation needed. 301→302 backend tests; 66 iOS unchanged. | ✅ (2026-04-15) |
| 2i-c | Hardening: operational validation (LocalStack workers end-to-end), conftest schema drift detection, CI ruff enforcement, Phase 2 consolidation docs (`docs/Consolidated_Error_Report_Phase_2.md` + `docs/Consolidated_Conversation_Summaries_Phase_2.md`), tag prep. XCUITest target deferred to Phase 3. Tag `v0.2.0` is a Mike action post-merge. | ✅ (2026-04-15) |
| 2i-d | Operational validation: EC2 redeployed via rsync (deploy keys disabled; GitHub auth broken) — 11/11 containers built, running, MD5 clean against repo copies (**2b-val-L1 resolved**). PAT scrubbed from EC2 `~/barkain/.git/config` and revoked by Mike in GitHub UI 2026-04-29 (SP-L1-b resolved). Watchdog `--check-all` live run caught a latent path bug: `CONTAINERS_ROOT = parents[1] / "containers"` pointed at `backend/containers/` instead of `<repo>/containers/`, so every `selector_drift` heal failed with "extract.js not found" before reaching Opus. One-line fix (`parents[2]`) validated end-to-end via a second live `--check-all` with a real `ANTHROPIC_API_KEY`: **`ebay_used` heal_staged** with 2399 Opus tokens and wrote `containers/ebay_used/staging/extract.js`, proving the pipeline path → Opus → JSON parse → staging dir → DB row. 4 of 5 drifts still fail at the Opus step because the heal prompt passes `page_html=error_details` (no real DOM), tracked as 2i-d-L4. Deferred retailer selector validation: **3 of 4 pass** (sams_club, home_depot, backmarket all `success`); `lowes` hangs >120s on extract (2i-d-L2, not missing selectors — Chromium init). `BarkainUITests` target wired end-to-end: `testManualUPCEntryToAffiliateSheet` drives manual UPC `194252818381` → SSE stream → retailer row → affiliate sheet; proof of the affiliate pipeline is the `affiliate_clicks` row with `tag=barkain-20` and `affiliate_network='amazon_associates'` post-tap. 3× accessibility-identifier additions (`manualEntryButton`, `upcTextField`, `resolveButton`, `retailerRow_<id>`). Backend untouched: 302/6. iOS: 66 unit + 2 UI (new `testManualUPCEntryToAffiliateSheet` + existing `testLaunch`). | ✅ (2026-04-15) |

### Infrastructure Phase 2 Extends
- Scraper containers (Phase 1) — add Watchdog self-healing + automated health monitoring
- iOS app shell — add Profile tab, subscription paywall, identity onboarding
- Backend — add subscription tier checking, identity matching, card matching
- Docker-compose — add LocalStack for SQS/S3/SNS

---

## Phase 3: AI Layer + Receipt Scanning + Card Optimization (Weeks 13-16) — ⬜ PLANNED

> **Goal:** AI-powered full-stack recommendations, receipt scanning for savings tracking, card reward optimization at purchase time, portal bonus stacking, coupon discovery.
> **Tag:** v0.3.0

### Steps

| Step | Scope | Status |
|------|-------|--------|
| 3a | M1 Product Text Search: `POST /products/search` with pg_trgm fuzzy match + Gemini grounding fallback; iOS SearchView with 300 ms debounce and recent-searches; migration 0007 | ✅ |
| 3b | eBay Browse API adapter replacing `ebay_new` / `ebay_used` scraper legs (sub-second vs 70 s selector-drift timeouts); `client_credentials` token refresh cached in-process; Marketplace Account Deletion webhook (GDPR prerequisite for production API access); backend deployed on scraper EC2 via Caddy + systemd (`ebay-webhook.barkain.app` HTTPS) | ✅ |
| 3c | M1 Search v2: 3-tier cascade (DB → BBY+UPCitemdb parallel → Gemini), brand-only routing, `force_gemini` deep-search, variant collapse, eBay affiliate URL fix; 3c-hardening (live-test bundle: Amazon platform-suffix accessory filter, Walmart/Best Buy retries, Redis device→UPC + scoped query caches, iOS sheet-anchor fix) | ✅ |
| 3d | Autocomplete (vocab + iOS integration): on-device prefix suggestions via `actor AutocompleteService` + sorted-array binary search; Apple-native `.searchable + .searchSuggestions + .searchCompletion`; `RecentSearches` service (UserDefaults, legacy-key migrated); offline `scripts/generate_autocomplete_vocab.py` sweep of Amazon's autocomplete API → bundled JSON; submit-driven search replaces auto-debounce-search | ✅ |
| 3e | **M6 Recommendation Engine (deterministic stacking — reclassified from AI to T).** `POST /api/v1/recommend` gathers prices + identity + cards + portals in one `asyncio.gather` and stacks in pure Python (p95 < 150 ms, no LLM). Winner picked by `effective_cost` (base − identity, minus deferred card + portal rebates) with new>refurb>used + well-known-retailer tiebreaks. Brand-direct callout fires on ≥15 % identity programs at `*_direct` retailers (3j fold-in). Sentence templates build headline + "why" copy. iOS `RecommendationHero` renders **only** after SSE done + identity + cards all settle — three settle flags in `ScannerViewModel` gate `attemptFetchRecommendation()`. Silent fallback on any failure (no user-facing alerts). `scripts/seed_portal_bonuses_demo.py` originally seeded 13 portal rows; deleted in 3g-B once the live worker landed | ✅ |
| 3f | **Purchase Interstitial + Activation Reminder.** `PurchaseInterstitialSheet` presents from both the `RecommendationHero` CTA and any retailer row tap — restates the winning card, conditional rotating-bonus activation block (opens issuer URL in SFSafari), primary Continue button opens the tagged affiliate URL. Reuses 3e `/api/v1/recommend` + `CardRecommendation`; no parallel stacking endpoint. Migration 0008 adds `affiliate_clicks.metadata` JSONB; `POST /affiliate/click` gains `activation_skipped` telemetry. M6 cache key extended with `:c<sha1(card_ids)>:i<sha1(identity_flags)>:v2` so adding a card busts stale recs. Alternatives rail now scrolls the list via `ScrollViewReader` (Pre-Fix #5). Pre-fixes: `BarePreviewAPIClient` base class, `scripts/_db_url.py` helper, `without_demo_mode` fixture + respx BBY route — killed 6 pre-existing auth test failures (8-step carry-forward). Portal guidance ("Open Rakuten first") explicitly deferred to 3g | ✅ |
| 3g-A | **Portal Live Integration — backend slice.** Migration 0012 (`portal_configs` w/ display + signup-promo + alerting state). New `m13_portal` module: `PortalMonetizationService.resolve_cta_list` runs a 5-step decision tree (feature-flag → 24h staleness → MEMBER_DEEPLINK with graceful fallthrough → SIGNUP_REFERRAL with FTC disclosure → GUIDED_ONLY); deterministic sort tiebreak + DEBUG-logging of rejected candidates (PR #52 lesson). `POST /api/v1/portal/cta` on `general` rate bucket. Resend alerting on 3 consecutive empty portal runs (24h `last_alerted_at` throttle; empty key → log+skip). AWS Lambda infra files (`infrastructure/lambda/portal_worker/`) + deploy runbook (Mike runs `deploy.sh`). EC2 has no PG so the cron CANNOT run there — Lambda hits the production DB host directly | ✅ |
| 3g-B | **Portal Live Integration — iOS slice.** `PortalCTA` model + interstitial portal row (≤3 sorted by rate desc; FTC disclosure conditional; signup promo amber line). M6 cache key bump `:v4` → `:c<...>:i<...>:p<sha1(active_portals)>:v5` so toggling membership busts stale recs (active-set-only hash so off+on doesn't double-bust). `affiliate_clicks.metadata.portal_event_type` ∈ `{member_deeplink, signup_referral, guided_only}` + `portal_source` for funnel split (no migration — JSONB already shipped 0008; server-side validation rejects unknown event types with 422). Profile → "The Kennel" portal-membership toggles wired to `PortalMembershipPreferences`. `seed_portal_bonuses_demo.py` deleted. **Codable acronym:** `.convertFromSnakeCase` maps `portal_ctas` → `portalCtas` so `StackedPath` uses lowercase form for wire round-trip while local `PurchaseInterstitialContext` keeps `portalCTAs`. CLAUDE.md compacted 33,952 → 26,095 chars before kickoff (separate first commit) | ✅ |
| 3g-B-fix-1 | Wire `portalMembershipsSection` into `ProfileView`'s second `ScrollView` branch (completed-profile path). Original 3g-B (#54) only patched the empty-profile branch, so users with an identity flag set saw no toggles. 1-line structural fix caught during sim validation; KDL bullet added to flag the dual-branch trap for future Profile additions | ✅ |
| search-resolve-perf-1 | Tiered `_merge()` by confidence (`_STRONG_CONFIDENCE=0.55`) fixes Switch OLED → Switch 2 substitution; parallel Gemini+UPCitemdb in resolve paths drops P50 from 17s→5s and 404 tail from 34s→13s; `upcitemdb.py` HTTPStatusError split; `ProductSearchResponse.cascade_path` populated so iOS telemetry can attribute slow queries. PR #61 | ✅ |
| search-relevance-1 | Marketplace relevance pack: price-outlier <40 % median on `{ebay,fb}` (≥4 listings); FB soft model gate (cap 0.5 when SKU absent) instead of hard reject; family-prefix SKU emission for long hyphenated codes (`RZ07-00740100`→`RZ07-0074`); new `[A-Z]\d{3,4}` pattern catches `G613`/`G915`/`K780`; `upcitemdb.model` plumbed into scorer; partial-listing regex widened (keycap/faceplate/skin/sleeve/mount-dock-grip/strap-band); Tier-2 noise tokens +accessor/thumbstick. PR #62 | ✅ |
| demo-prep-1 | F&F demo reliability pack, 7 items + 2 pre-fixes. **Item 1:** `/recommend` 422 → explicit `RecommendationState.insufficientData(reason:)` + dedicated `InsufficientRecommendationCard`; pre-existing FastAPI envelope `{detail:{error:...}}` decode fix in `APIClient.decodeErrorDetail`. **Item 2:** new `UnresolvedProductView` for 404s; `TabSelectionAction` env value unblocks cross-tab nav. **Item 3:** `LOW_CONFIDENCE_THRESHOLD=0.70` env-tunable gate on `/resolve-from-search` → 409 `RESOLUTION_NEEDS_CONFIRMATION`; new `POST /resolve-from-search/confirm` endpoint with `source_raw.user_confirmed=True` persistence; iOS `ConfirmationPromptView` sheet with primary + 2 alternatives. **Items 4+5:** `make demo-check` + `make demo-warm` CLIs (first repo-root Makefile). **Pre-fixes:** xcuserdata/ untracked; CLAUDE.md 29,951→26,970. **Item 6 deferred** on Figma handoff. PR #63 | ✅ |
| bench/vendor-compare-1 | Diagnostic head-to-head benchmarking the AI leg of `asyncio.gather(Gemini, UPCitemdb)`. 6 configurations × 20-UPC catalog × 5 runs (600 calls, ~28 min wall, 0 timeouts): A_grounded_dynamic (production parity), B_grounded_low, C_no_ground_dynamic, D_no_ground_low, E_serper_then_D (proposed migration target), F_serper_kg_only (no-LLM fast-path). `validate()` mirrors production gates (L4 brand/spec + Apple Rules 2c chip equality + 2d display-size equality, both disagreement-only). Output: `scripts/bench_results/bench_2026-04-27T01-53-45.895984_00-00.json` + `docs/BENCH_VENDOR_COMPARE.md` analysis. **Recommendation: DEFER** pending `bench/vendor-compare-2` clean-catalog re-run. Latency win for E_serper_then_D vs A_grounded_dynamic conclusive (p50 −59 %, p90 −71 %, p99 −85 %, $/call −98 %); recall comparison contaminated because 16/18 non-invalid catalog UPCs did not resolve to their labeled products (e.g. UPC labeled "MacBook Air M4" consistently resolved to "Mac mini M4 Pro"; UPC labeled "iPad Pro M4" resolved to a barstool). Catalog was synthesized without programmatic UPCitemdb verification. **No production code paths changed.** `_bench_serper.py` private to `scripts/`; production Serper integration (if MIGRATE wins post-vendor-compare-2) is a separate follow-up activity. Reusable framework: only the JSON catalog needs replacement | ✅ |
| feat/grounded-low-thinking | Production Gemini grounded leg in `backend/ai/abstraction.py:gemini_generate` switched from `ThinkingConfig(thinking_budget=-1)` to `ThinkingConfig(thinking_level=ThinkingLevel.LOW)` after `scripts/bench_mini_a_vs_b.py` (UPCitemdb-validated 5-UPC mini-bench, 30 calls) confirmed identical recall (8/10 vs 8/10) and tied p50 latency on clean inputs. Cost win ~37% per call holds at the Gemini billing layer regardless of latency. +2 regression tests in `tests/test_ai_abstraction.py` pin the new config shape. Side-finding: UPCitemdb-validated UPCs aren't always Gemini-resolvable (Galaxy Buds R170N → Goodcook can opener); vendor-compare-2's catalog needs both filters | ✅ |
| bench/vendor-compare-2 | Clean-catalog re-run of vendor-compare-1's 6-config head-to-head. New `scripts/bench_prevalidate_v2.py` runs both filters (Filter 1: UPCitemdb has a record + brand contains expected; Filter 2: Gemini A-config grounded probe agrees on brand+name+chip+display) → 32 candidates → 9 survivors (7 valid + 2 invalid). 270 calls, ~14 min wall, ~$5.5 spend. **No production code paths changed.** New `scripts/bench_data/test_upcs_v2.json` + `--catalog` CLI flag on `scripts/bench_vendor_compare.py`. **Headline**: B (current prod) and E_serper_then_D tie at 24/28 = 85.7% recall but on different UPCs (B fails iPad Air → confidently returns "Flash Furniture Lincoln Barstool" 4/4; E fails Xbox → null 4/4 due to non-deterministic synthesis-prompt-interpretation issue confirmed in 2/5 manual repro). E is 27% faster on p50, 31% on p90, 28× cheaper, safer failure mode (null vs confidently wrong). **Recommendation: MIGRATE B → E with synthesis-prompt hardening first**. Closes Known Issue `bench-cat-1`; opens `bench-cat-2` (broader-category catalog for vendor-compare-3, optional). New `docs/BENCH_VENDOR_COMPARE_V2.md` analysis | ✅ |
| bench/vendor-migrate-1 | Production AI-resolve leg switched from grounded-Gemini-only (B) to Serper-then-grounded (E-then-B). New `backend/ai/web_search.py:resolve_via_serper(upc)` — Serper SERP top-5 → Gemini synthesis (no grounding, `thinking_budget=0`, `max=1024`). `m1_product/service.py:_get_gemini_data` tries Serper first; soft-falls to grounded on null/error. `gemini_generate` gains `grounded` + `thinking_budget` kwargs (defaults preserve PR #75); fixes long-standing temperature-1.0 hardcode. Bench-validated against Mike-verified 9-UPC catalog: **E_current_budget0 45/45 (100%) vs B_grounded_low 24/45 (53%)**, p50 1627ms vs 3083ms (-47%), per-call cost $0.00109 vs $0.040 (~36× cheaper). Backend 694→711 (+17 tests). 5 bench scripts validated the migration (mini-grid, broader-category probe, wider-field grid, raw-SERP dump, verified-catalog head-to-head). The original v5.37 plan was synthesis-prompt hardening; vendor-migrate-1 found a stronger fix path during investigation — Xbox null was a `thinking_budget` issue, not a prompt issue (at budget=0 the model stops second-guessing snippets). Failure mode is graceful (Serper miss → grounded fallback). `SERPER_API_KEY` empty default = back-compat skip | ✅ |
| 3o-A | Autocomplete vocab expansion: drop in-script `is_electronics()` term-content filter (97%-electronics top-200 was structural, not necessary); default sweep now hits 6 Amazon scopes (`aps`, `electronics`, `grocery`, `pet-supplies`, `tools`, `beauty`) plus 3 probe-gated extras (`automotive`, `health-personal-care`, `office-products`) that auto-admit when their `(ca, pa, tir)` probe averages ≥ 5 suggestions/prefix. `sweep_all_sources` parallelizes per-source sweeps via `asyncio.gather(return_exceptions=True)` (~12 min wall-clock for 8 admitted scopes vs ~75 min sequential). `--max-terms` 5K → 15K. Bundle `version=2` (term schema unchanged). Vocab 4,448 → 15,000 / 128 KB → 470 KB. iOS code unchanged. Sim smoke confirmed: `cat` / `dog` surface 8 pet rows; `iph` regression-clean. Pre-fixes: UPCitemdb env-var name matches code (no fix); `source_raw->'gemini_raw'` shape is `{"name": str}` post-vendor-migrate-1, no docs reference the old `device_name` shape (no fix) | ✅ |
| 3o-B | Tier-2 noise filter narrowing: 14-entry `_TIER2_NOISE_CATEGORY_TOKENS` denylist split into three behavior pools — hard (`warrant`/`applecare`/`subscription`/`gift card`/`specialty gift`/`protection`/`monitor`/`physical video game`/`service`/`digital signage`/`screen protector`, unconditional drop), soft (`case`+`charger`, query-opt-out via `_SOFT_NOISE_QUERY_OPT_OUT`), and accessor-context (`accessor` substring drops only when category also names an electronics parent from `_ACCESSOR_CONTEXT_TOKENS`: gaming/controller/console/phone/smartphone/tablet/laptop/computer/tv/video game/camera/drone/headphone/earbud/keyboard/mouse). Resolves Discovery v1 §B3 cat-litter false-negative (`Litter Boxes & Accessories` no longer drops on bare `accessor`); proactively addresses 3o-A predictable false-negatives (`iphone case`/`anker charger` queries opt out). `monitor` and `screen protector` held in hard pool per wait-and-see. Sibling `_classify_tier2_noise` returns reason label; escalation log line gains per-pool `breakdown=` dict. Title denylist + brand-bleed/strict-spec/model-code gates untouched. Backend 754 → 773 passed (+19 tests). iOS sim smoke (cat litter unscented, iphone 17 pro max case, anker portable charger, ps5 controller) passed end-to-end | ✅ |
| 3o-C | Gemini UPC `system_instruction` rewrite: `UPC_LOOKUP_SYSTEM_INSTRUCTION` rewritten category-agnostic (3,489 → 4,310 chars). 9-step skeleton (validate → query → cross-verify → extract → identify → assemble → justify → source-discipline → null-on-uncertainty) preserved verbatim; JSON contract (`device_name` / `model` / `reasoning`) unchanged; 6 mixed-vertical examples replace 4 electronics-only examples (iPad Pro 13-inch M4 / KitchenAid Artisan 5-Quart Stand Mixer (KSM150PSER) / Royal Canin Adult Indoor 7lb Dry Cat Food / DeWalt 20V MAX Drill (DCD777C2) / Greenworks 80V Self-Propelled Mower (2532502) / iPhone 16 Pro Max 256GB). `build_upc_retry_prompt` rewritten to "all retail categories"; `build_upc_lookup_prompt` byte-unchanged. New `tests/ai/test_upc_lookup_prompt.py` anti-condensation regression suite (8 tests pinning markers / length ≥ 3,000 / 9 steps in order / all 6 examples / JSON contract / electronics-removal / retry rewrite / builder-byte-stable) — Phase 1 L13 (agent-condensing) is the load-bearing failure mode this catches. Mini-bench `scripts/bench_grounded_3o_c.py` 5 UPCs × old + new prompts = 10 grounded calls; pass criterion `no_electronics_regression=True` met. Pre-Fix #1 confirmed Makita-as-MacBook misresolve (UPC `088381675681`) FIXED — re-resolves to "Makita 18V LXT XFD10Z Driver-Drill". Backend 773 → 781 passed (+8 tests). iOS unchanged. Closes the 3o-A vocab + 3o-B noise filter + 3o-C prompt category-expansion trilogy. Surfaced bug `3o-C-L1-fabricated-upc-tap` (pre-existing since 3c, amplified by 3o-C breadth — Tier 3 Gemini search fabricates `primary_upc` values, iOS taps them and grounded resolve hallucinates) deferred to follow-up | ✅ |
| fix/dark-mode-contrast | iOS dark-mode contrast fix on warm-gold capsules + recommendation hero card. Root cause: `barkainOnPrimaryContainer` dark hex was `#2A1C00` on `barkainPrimaryFixed`'s `#3A2D15` warm-dark capsule (≈1.2:1 contrast, well below WCAG AA's 4.5:1 body-text minimum). Affected SavingsBadge, SearchResultRow "Any variant" pill, HomeView Recently-sniffed count, and four ProfileView capsules. Hero card had a related issue — `Color.barkainPrimaryContainer.opacity(0.55)` over near-black surface produced muted gold, then `barkainPrimary` "BEST BARKAIN" + "Save $X" landed at ≈2.6:1. Token split: `barkainOnPrimaryContainer` stays always-dark for `BestBarkainBadge`'s always-gold `PrimaryContainer` pill; new `barkainOnPrimaryFixed` (light `#694700`, dark `#F9B12D`) flips for warm-cream/warm-dark capsules. New `barkainHeroSurface` (light `#F7D18C` solid, dark `#2A1F0E`) replaces the translucent-gold hero fill so gold accents pop in dark. 7 sites migrated `OnPrimaryContainer` → `OnPrimaryFixed`; ScentTrail's `BestBarkainBadge` intentionally untouched. 0 new tests (cosmetic color-token change, visually verified on iPhone 17 Pro sim). PR #93 (merged) | ✅ |
| feat/search-thumbnail-fallback | Last-resort thumbnail cascade so every search row gets a picture, plus end-to-end visual consistency through resolve. Two-pass backfill in `ProductSearchService.search` after `_collapse_variants`: pass 1 = new `lookup_thumbnail` in `m2_prices/adapters/ebay_browse_api.py` (free, eBay Browse keyword search, `limit=1`); pass 2 = new `lookup_thumbnail_via_serper` in `ai/web_search.py` for rows pass 1 missed (paid ~$0.001/call, **Google Images** via `https://google.serper.dev/images` — switched mid-build from `/search` after live-sim testing surfaced a Johnson-Smith/Incredibuilds miss; `/search` only carries `imageUrl` on Google's og:image preview, `/images` is purpose-built). Per-row parallel via `asyncio.gather(return_exceptions=True)`, soft-fail every stage. New `SEARCH_THUMBNAIL_FALLBACK` config flag (default ON). Resolve wire-through: new `fallback_image_url` field on `ProductResolveRequest` + `ResolveFromSearchRequest` + `ResolveFromSearchConfirmRequest`; `resolve()` + `resolve_from_search()` + `_resolve_with_cross_validation()` + `_persist_product()` all take it as kwarg; backend uses it ONLY when no upstream resolver supplied an image, through the same `_KNOWN_BAD_IMAGE_HOSTS` filter. iOS: `APIClientProtocol.resolveProduct` + `resolveProductFromSearch` gain `fallbackImageURL: String?`; `Endpoints` encodes via `convertToSnakeCase`; `SearchViewModel.resolveTappedResult` + `OptimisticPriceVM.resolveTappedResult` forward `result.imageUrl`; `SearchViewModel.confirmResolution` puts it on `ResolveFromSearchConfirmRequest`; `ScannerViewModel` (barcode path) passes nil; `BarePreviewAPIClient` + `MockAPIClient` updated. Persisted to `Product.image_url` so loading state + Recently Sniffed inherit the same thumbnail. Backend 799 → 806 (+7 tests: 5 in `test_product_search.py` covering cascade order / eBay-hit short-circuit / Serper-runs-when-eBay-misses / flag disable / soft-fail; 2 in `test_m1_product.py` pinning fallback-used-when-no-upstream / fallback-ignored-when-upstream-supplies). Verified live in sim — `vintage 1970 transistor radio` and `obscure japanese rice cooker zojirushi` previously rendered the brand-initials placeholder, now show real product thumbnails. PR #94 | ✅ |
| feat/provisional-resolve | Dark-launched fallback path on `/resolve-from-search`: when both Gemini device→UPC AND UPCitemdb keyword search return null UPC, persist a best-effort `Product` with `upc=NULL`, `source="provisional"`, `source_raw["provisional"]=True` + `["search_query"]` (forwarded from new `query: str?` request field) instead of raising `UPC_NOT_FOUND_FOR_PRODUCT`. Closes the dead-end on real-product queries (Steam Deck OLED 1TB LE, ThinkPad X1 Carbon Gen 12 full-spec, Festool 577419, Traeger TFB97RLG) where Gemini refuses to commit to a single SKU and UPCitemdb has no row, the relevance pack would have caught noise, but resolve bailed before the price stream got a chance. Gated by new `PROVISIONAL_RESOLVE_ENABLED: bool = False` flag — schema additions (`Product.match_quality` `@property` reading `source_raw["provisional"]`; `match_quality: Literal["exact","provisional"]` on `ProductResponse`; `query: str?` on `ResolveFromSearchRequest`) ship safely with behavior unchanged until the flag flips. Only converts the upstream-empty branch — cache-mismatch (post-Redis-invalidate) and post-resolve-mismatch (`_resolved_matches_query` rejection like Toro→Greenworks) still raise so canonical-row gates keep authority. 409 confidence gate fires BEFORE provisional persist so a low-confidence tap still surfaces the iOS confirmation sheet (no row written until confirmed). 7-day dedup via SELECT-then-INSERT on `(name, brand, source='provisional')` keeps re-tapped dead-end queries pinned to one UUID. M2 `get_prices`/`stream_prices` auto-inject `query_override = product.name` server-side for provisional rows so the bare-name cache scope, container query, and per-container product_name hint all key off the user's intent (relevance gates do the rest at price-fetch time); caller-supplied override still wins. M6 `_gather_inputs` tags `prices_payload["_provisional"]` from the persisted row's source; existing inflight-skip cache-write guard generalized to cover both inflight + provisional payloads, log line renamed `recommendation_skip_cache_write` with `inflight=<bool> provisional=<bool>` tags for operator attribution. iOS: new `Product.matchQuality: String?` + `isProvisional` convenience; `RecommendationHero` adds optional `isProvisional`/`searchQuery` props that render a soft warm-cream banner above the card (`Best results for "<query>" — exact match unavailable. Verify before tapping Open.`) and downgrade the gold "BEST BARKAIN" pawprint eyebrow to muted-grey "APPROXIMATE MATCH" magnifying-glass; CTA + breakdown + savings unchanged so spending flow still works; `PriceComparisonView` reads both off the same Product the rest of the view has. `SearchView.swift` `recentlyScanned.record` skips provisional rows so the rail stays canonical-only. Wire-through: `query: String?` plumbed through `Endpoint.resolveFromSearch` + body encoder, `APIClientProtocol.resolveProductFromSearch`, `MockAPIClient`, `BarePreviewAPIClient` (Swift protocol default-args don't propagate through protocol-typed call sites — every conformer + holder passes explicitly, same gotcha thumbnail-fallback hit). Backend 806 → 815 (+9 tests: 6 in `test_product_resolve_from_search.py` covering provisional persist on flag-on / 404 preserved on flag-off / 7-day dedup / 409 precedes provisional / resolved-mismatch still 404 / `match_quality="exact"` on canonical; 2 in `test_m2_prices.py` pinning provisional auto-injection + caller-override-wins; 1 in `test_m6_recommend.py` pinning the cache-write skip with `provisional=True inflight=False` log assertion + 1 modified for the renamed log key). +1 new iOS hero snapshot baseline (`provisional_approximateMatch.provisional-approximate-match.png`) plus tier1/2/3 baselines re-recorded due to the new conditional banner branch shifting layout pixels. iOS unit 215 → 216. Live-verified Festool TS 60 KEBQ-Plus 577419 (yesterday's 404 sweep) → 200 with `match_quality: "provisional"`, M2 stream returned a real $700 used FB Marketplace listing while other 8 retailers correctly `no_match` at the relevance-gate level. PR TBD | ✅ |
| 3h | M8 Image scanning: Claude Vision for product ID from photos (not just barcodes) | ⬜ |
| 3i | M8+M10 Receipt scanning: on-device OCR (Vision framework) → structured text to backend → item extraction → savings calculation → dashboard | ⬜ |
| ~~3j~~ | ~~Identity discount stacking in recommendations~~ — **folded into 3e brand-direct callout** 2026-04-22 | ✅ |
| 3k | Savings dashboard populated with real receipt data | ⬜ |
| 3l | Coupon discovery + validation: agent-browser batch scraping of coupon sites, on-demand validation, confidence scoring | ⬜ |
| 3m | Hardening: AI integration tests with mock responses, tag v0.3.0 | ⬜ |

> **Note on renumbering:** the original PHASES stub named 3a "AI abstraction layer" — already shipped in Phase 1 at `backend/ai/abstraction.py`, so 3a was reassigned to Product Text Search. Step 3b (eBay Browse API + deletion webhook) was added mid-phase after live sim testing revealed eBay container legs were unrecoverable; it pushed the original 3b–3j down one letter. Step 3d (Autocomplete) was inserted 2026-04-19 between Search v2 (now 3c) and the original Card-rewards step, shifting the originally-numbered 3d–3k → 3f–3m one letter further (M6 Recommendation Engine became 3e). Phase 3 letter order has been demo-prep- and feature-priority-driven rather than strict plan order.

### Phase 3 API Endpoints (tagged for this phase)

| Method | Path | Module | Description |
|--------|------|--------|-------------|
| POST | /api/v1/products/search | M1 | Text query → ranked product list (pg_trgm + Gemini grounding) |
| POST | /api/v1/products/identify | M1 | Image → product (vision AI) |
| POST | /api/v1/recommend | M6 | Full-stack recommendation (Step 3e — deterministic, 60/min rate limit, no LLM) |
| POST | /api/v1/receipts/scan | M8+M10 | Receipt text → savings calc |
| GET | /api/v1/savings | M10 | Savings dashboard data |
| GET | /api/v1/card-match/{product_id} | M5 | Card recommendation for product |

---

## Phase 4: Intelligence + Watched Items + Launch Prep (Weeks 17-20) — ⬜ PLANNED

> **Goal:** Price prediction, watched items with price tracking, listing quality scoring, rotating category auto-refresh, production API optimization, App Store submission.
> **Tag:** v0.4.0

### Steps

| Step | Scope | Status |
|------|-------|--------|
| 4a | M7 Price prediction: Prophet model on TimescaleDB price_history + seasonal trends, buy/wait UI with confidence indicator | ⬜ |
| 4b | Watched items: user saves products, system monitors prices over set period, target price alerts, watch expiry | ⬜ |
| 4c | M3 Listing quality scoring for eBay (AI-powered): analyze photos, seller history, pricing anomalies | ⬜ |
| 4d | Quarterly category auto-refresh pipeline: agent-browser cron targeting Doctor of Credit, cross-validation, Slack alert for human review | ⬜ |
| 4e | User-selected category capture UI for US Bank Cash+, BofA Customized Cash | ⬜ |
| 4f | Production API optimization: add Best Buy Products API, eBay Browse API, Keepa API as speed layer alongside scrapers. Fallback chain: API → container → skip | ⬜ |
| 4g | Accessibility audit, performance profiling, error handling sweep | ⬜ |
| 4h | App Store submission prep: screenshots, metadata, privacy labels, FTC affiliate disclosure, privacy policy, TestFlight beta | ⬜ |

### Phase 4 API Endpoints

| Method | Path | Module | Description |
|--------|------|--------|-------------|
| GET | /api/v1/predict/{product_id} | M7 | Price prediction + buy/wait |
| POST | /api/v1/watch | M9 | Watch a product for price drop |
| GET | /api/v1/watch | M9 | User's watched items |
| DELETE | /api/v1/watch/{item_id} | M9 | Stop watching |

---

## Phase 5: Notifications + Post-Purchase + Scale (Months 6-9) — ⬜ FUTURE

> **Goal:** Push notifications, post-purchase price matching, expanded retailers and categories.
> **Tag:** v0.5.0

### What to build
- Push notifications: price drop alerts for watched items, incentive spike alerts (APNs via AWS SNS)
- Post-purchase price match detection and automation
- Negotiation intelligence for secondary market listings
- Expand identity discount catalog (apparel: Adidas 30% military, Nike 10%; telecom: T-Mobile military plans; streaming: Spotify student 50%)
- Web dashboard on Vercel (Next.js) — account management, savings analytics
- Card-linked offers exploration (Tier 4 — MCP integration with CardPointers, or browser extension, or crowd-sourced)

---

## Phase 6: Platform (Months 9-12) — ⬜ FUTURE

> **Goal:** Multi-platform, API product, advanced ML, brand partnerships.
> **Tag:** v1.0.0

### What to build
- Android app (Kotlin / KMP)
- API tier for third-party developers
- Advanced ML models retrained on real user data
- Brand cashback partnership program
- International expansion research
- Anonymized data infrastructure (opt-in, B2B product)

---

## Step Sizing Guidelines

Each step: ~500-1500 lines new code, 1 clear feature boundary, tests included, completable in one coding session.

Steps that will likely need splitting:
- 1d (5 retailer containers from tested scripts) — may split into 2-3 batches
- 1e (6 new retailer containers) — may split into 2-3 batches
- 3c (recommendation engine) — may split into backend + iOS UI
- 3d (card matching) — backend algorithm + iOS interstitial UI
- 4h (App Store submission) — screenshots/metadata + TestFlight

---

## Phase Boundary Checklist

Before tagging a release:
- [ ] All step PRs merged to main
- [ ] All tests passing (pytest + XCTest)
- [ ] Build clean (no warnings-as-errors)
- [ ] `ruff check` clean (backend)
- [ ] SwiftLint clean (iOS)
- [ ] CLAUDE.md passes "new session" test
- [ ] All guiding files accurate and up-to-date
- [ ] Git tag created (`v0.N.0`)
- [ ] Error reports consolidated
- [ ] Conversation summaries consolidated
