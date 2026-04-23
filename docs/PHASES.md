# Barkain — Phase Roadmap

> Source: Project Planning Questionnaire + Architecture Sessions, March–April 2026
> Scope: All planned phases, current position, infrastructure dependencies
> Last updated: 2026-04-22 (v3.5 — Phase 3 through fb-resolver-followups + extractor post-fix; migrations 0008–0011)
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
| 2i-d | Operational validation: EC2 redeployed via rsync (deploy keys disabled; GitHub auth broken) — 11/11 containers built, running, MD5 clean against repo copies (**2b-val-L1 resolved**). PAT `gho_UUsp9ML7…` scrubbed from EC2 `~/barkain/.git/config`; Mike still needs to revoke it in GitHub UI (SP-L1-b). Watchdog `--check-all` live run caught a latent path bug: `CONTAINERS_ROOT = parents[1] / "containers"` pointed at `backend/containers/` instead of `<repo>/containers/`, so every `selector_drift` heal failed with "extract.js not found" before reaching Opus. One-line fix (`parents[2]`) validated end-to-end via a second live `--check-all` with a real `ANTHROPIC_API_KEY`: **`ebay_used` heal_staged** with 2399 Opus tokens and wrote `containers/ebay_used/staging/extract.js`, proving the pipeline path → Opus → JSON parse → staging dir → DB row. 4 of 5 drifts still fail at the Opus step because the heal prompt passes `page_html=error_details` (no real DOM), tracked as 2i-d-L4. Deferred retailer selector validation: **3 of 4 pass** (sams_club, home_depot, backmarket all `success`); `lowes` hangs >120s on extract (2i-d-L2, not missing selectors — Chromium init). `BarkainUITests` target wired end-to-end: `testManualUPCEntryToAffiliateSheet` drives manual UPC `194252818381` → SSE stream → retailer row → affiliate sheet; proof of the affiliate pipeline is the `affiliate_clicks` row with `tag=barkain-20` and `affiliate_network='amazon_associates'` post-tap. 3× accessibility-identifier additions (`manualEntryButton`, `upcTextField`, `resolveButton`, `retailerRow_<id>`). Backend untouched: 302/6. iOS: 66 unit + 2 UI (new `testManualUPCEntryToAffiliateSheet` + existing `testLaunch`). | ✅ (2026-04-15) |

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
| 3e | **M6 Recommendation Engine (deterministic stacking — reclassified from AI to T).** `POST /api/v1/recommend` gathers prices + identity + cards + portals in one `asyncio.gather` and stacks in pure Python (p95 < 150 ms, no LLM). Winner picked by `effective_cost` (base − identity, minus deferred card + portal rebates) with new>refurb>used + well-known-retailer tiebreaks. Brand-direct callout fires on ≥15 % identity programs at `*_direct` retailers (3j fold-in). Sentence templates build headline + "why" copy. iOS `RecommendationHero` renders **only** after SSE done + identity + cards all settle — three settle flags in `ScannerViewModel` gate `attemptFetchRecommendation()`. Silent fallback on any failure (no user-facing alerts). `scripts/seed_portal_bonuses_demo.py` seeds 13 portal rows pending 3g replacement | ✅ |
| 3f | **Purchase Interstitial + Activation Reminder.** `PurchaseInterstitialSheet` presents from both the `RecommendationHero` CTA and any retailer row tap — restates the winning card, conditional rotating-bonus activation block (opens issuer URL in SFSafari), primary Continue button opens the tagged affiliate URL. Reuses 3e `/api/v1/recommend` + `CardRecommendation`; no parallel stacking endpoint. Migration 0008 adds `affiliate_clicks.metadata` JSONB; `POST /affiliate/click` gains `activation_skipped` telemetry. M6 cache key extended with `:c<sha1(card_ids)>:i<sha1(identity_flags)>:v2` so adding a card busts stale recs. Alternatives rail now scrolls the list via `ScrollViewReader` (Pre-Fix #5). Pre-fixes: `BarePreviewAPIClient` base class, `scripts/_db_url.py` helper, `without_demo_mode` fixture + respx BBY route — killed 6 pre-existing auth test failures (8-step carry-forward). Portal guidance ("Open Rakuten first") explicitly deferred to 3g | ✅ |
| 3g | Portal bonus integration: portal worker goes live (replaces `seed_portal_bonuses_demo.py`); "Open Rakuten first" guided flow extends the 3f interstitial; portal vs. direct tracking for analytics | ⬜ |
| 3h | M8 Image scanning: Claude Vision for product ID from photos (not just barcodes) | ⬜ |
| 3i | M8+M10 Receipt scanning: on-device OCR (Vision framework) → structured text to backend → item extraction → savings calculation → dashboard | ⬜ |
| ~~3j~~ | ~~Identity discount stacking in recommendations~~ — **folded into 3e brand-direct callout** 2026-04-22 | ✅ |
| fb-marketplace-location | Per-user FB Marketplace city + radius override; iOS picker via CoreLocation; query-param plumbing through `/prices/{id}/stream` | ✅ |
| fb-marketplace-location-resolver | Numeric FB Page ID end-to-end (slug retired). Migration 0011 + 3-tier `FbLocationResolver` (Redis→PG→Startpage/DDG/Brave); GCRA token bucket; singleflight w/ subscribe-before-recheck; iOS bigint-safe `Stored.fbLocationId`; storage v1→v2; canonical-name redirect banner | ✅ |
| experiment/tier2-ebay-search | Opt-in flags swap M1 Tier 2 UPCitemdb→eBay Browse keyword search; `_sanitize_ebay_title` strips seller noise; `M2_EBAY_DROP_PARTIAL_LISTINGS` filter on `ebay_browse_api`. All defaults off — A/B in dev | ✅ |
| fb-resolver-followups | FB resolver follow-up bundle (L3/L4/L8/L9/L11/L12/L13). Dedicated `fb_location_resolve` rate bucket (5/min hard cap, no pro multiplier); DTO `source` → `resolution_path` rename + engine-name collapse to `{cache, live, seed, unresolved, throttled}`; `location_default_used` flag + iOS "Using SF default" pill on fb_marketplace; picker `retry()` + 3-attempt cap + 429-aware copy + canonical-redirect "Don't use this — start over"; top-50 US-metro local PG seed (50/50 after hand-resolve of Oakland/Raleigh/Seattle) | ✅ |
| fb-resolver-postfix-1 | Canonical-name validation in `_parse_result_html` (rejects sub-region IDs like West Raleigh for Raleigh queries). New verb-agnostic `\bin\s+...\| Facebook` extractor pattern that handles full state names ("Raleigh, North Carolina"). Three-way decision: VALIDATED > FALLBACK > REJECTED. Live-verified Seattle resolves end-to-end via Brave post-fix | ✅ |
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
