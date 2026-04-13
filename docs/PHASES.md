# Barkain — Phase Roadmap

> Source: Project Planning Questionnaire + Architecture Sessions, March–April 2026
> Scope: All planned phases, current position, infrastructure dependencies
> Last updated: April 2026 (v3.1 — first live 3-retailer scan-to-prices demo validated on physical iPhone; 7 live-run bug fixes landed on `phase-2/scan-to-prices-deploy`)
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

> **Goal:** User scans a barcode in-store and instantly sees prices from 11 retailers, all scraped via agent-browser containers. Prove the core value prop at scale.
> **Tag:** v0.1.0
> **Retailers (11):** Amazon, Best Buy, Walmart, Target, Home Depot, Lowe's, eBay (new), eBay (used/refurb), Sam's Club, BackMarket, Facebook Marketplace
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
- **agent-browser container infrastructure** — Docker container template, 11 retailer extraction scripts, health monitoring
- Price aggregation from 11 retailers via parallel container dispatch with Redis caching
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

## Phase 2: Identity Layer + Revenue + Watchdog (Weeks 9-12) — ⬜ PLANNED

> **Goal:** Identity profile, card portfolio, subscription billing, affiliate routing, Watchdog self-healing, and background workers.
> **Tag:** v0.2.0

### Steps

| Step | Scope | Status |
|------|-------|--------|
| 2a | Watchdog supervisor agent, health monitoring, shared base image, Phase 1 pre-fixes | ✅ (2026-04-10) |
| (interstitial) | Scan-to-Prices Live Demo — first-ever 3-retailer end-to-end run on physical iPhone; 7 live-run bug fixes landed on `phase-2/scan-to-prices-deploy` | ✅ (2026-04-10) |
| **2b** | **Demo Container Reliability: COMPLETE** ✅ (2026-04-11) — cross-validation (Gemini+UPCitemdb second-opinion), relevance scoring (`_score_listing_relevance` 0.0–1.0 with model-number hard gate), Amazon title selector 5-level fallback, Walmart first-party filter, `.env.example` audit (SP-5 post-mortem), fd-3 stdout backfill to remaining 8 retailers, 6 real-API integration tests (`@pytest.mark.integration`). 24 new tests + 6 integration tests with skip guard. **Step 2b-final (2026-04-13):** Gemini `device_name` + `model` output, post-2b-val test coverage (+35 tests → 181 total), `.github/workflows/backend-tests.yml` CI, EC2 deploy MD5 verification, integration conftest `.env` auto-load. F.5 generation-without-digit + GPU-SKU limitations resolved. | ✅ (2026-04-11, closed 2026-04-13) |
| 2b-pre | **BLOCKERS before 2b can start.** (1) Product-match relevance scoring (SP-10): retailer on-site search returns similar-but-not-identical products; `_pick_best_listing` needs a relevance guardrail before any user-facing demo. (2) Gemini UPC accuracy (SP-L4): 3/3 test UPCs resolved wrong, needs UPCitemdb second-opinion fallback or confidence scoring. (3) Rotate leaked GitHub PAT in EC2 git config (SP-L1). (4) Backfill fd-3 stdout convention to the other 8 retailer extract.sh files (SP-L2). (5) Amazon extract.js title selector regression (SP-9). (6) Walmart first-party filter in `_walmart_parser.py` (SP-L5). See `Barkain Prompts/Error_Report_Scan_to_Prices_Deployment.md`. | ⬜ |
| 2b | M5 Identity Profile: onboarding flow (capture identity groups + memberships), discount catalog seeding from IDENTITY_DISCOUNTS.md, weekly batch scraping of ID.me/SheerID/GovX/WeSalute/UNiDAYS/StudentBeans directories | ⬜ |
| 2c | M5 Card Portfolio: card catalog seeding (top 30 cards from CARD_REWARDS.md), user card selection, rotating_categories seeding (current + next quarter) | ⬜ |
| 2d | M11 Billing: StoreKit 2 via RevenueCat, free/pro tier gating, feature flags | ⬜ |
| 2e | M12 Affiliate Router: link construction (Amazon Associates tag, eBay Partner Network campaign ID, CJ tracking), attribution logging | ⬜ |
| 2f | Background workers: SQS (LocalStack for dev) + price ingestion worker + portal rate scraping (every 6hr) + discount program verification (weekly) | ⬜ |
| 2g | Hardening: guiding doc sweep, tag v0.2.0 | ⬜ |

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
| 3a | AI abstraction layer: `backend/ai/`, model routing (Opus for Watchdog, Sonnet for tasks, Qwen/ERNIE for parsing, GPT fallback), Instructor for structured output parsing | ⬜ |
| 3b | M6 Recommendation Engine: synthesize all layers (prices + identity + cards + portals + secondary market + wait signal) into single recommendation via Claude Sonnet. Progressive updates as data streams in | ⬜ |
| 3c | Card reward matching: query-time algorithm (pure SQL, < 50ms), purchase interstitial overlay UI ("Use your Chase Freedom Flex for 5% back"), portal instruction, activation reminder | ⬜ |
| 3d | Portal bonus integration: portal stacking with card recommendations, "Open Rakuten first" guidance, portal vs. direct tracking for analytics | ⬜ |
| 3e | M8 Image scanning: Claude Vision for product ID from photos (not just barcodes) | ⬜ |
| 3f | M8+M10 Receipt scanning: on-device OCR (Vision framework) → structured text to backend → item extraction → savings calculation → dashboard | ⬜ |
| 3g | Identity discount stacking in recommendations: brand-specific stacking rules, identity redirect opportunities (e.g., "Buy at Samsung.com with military discount for $450 less than Best Buy") | ⬜ |
| 3h | Savings dashboard populated with real receipt data | ⬜ |
| 3i | Coupon discovery + validation: agent-browser batch scraping of coupon sites, on-demand validation, confidence scoring | ⬜ |
| 3j | Hardening: AI integration tests with mock responses, tag v0.3.0 | ⬜ |

### Phase 3 API Endpoints (tagged for this phase)

| Method | Path | Module | Description |
|--------|------|--------|-------------|
| POST | /api/v1/products/identify | M1 | Image → product (vision AI) |
| POST | /api/v1/recommend | M6 | Full-stack recommendation |
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
- 3b (recommendation engine) — may split into backend + iOS UI
- 3c (card matching) — backend algorithm + iOS interstitial UI
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
