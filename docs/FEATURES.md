# Barkain — Feature Inventory

> Source: Project Planning Questionnaire + Architecture Sessions, March–April 2026
> Scope: Every feature, status, AI/Traditional/Hybrid classification, data source
> Last updated: April 2026 (v3.1 — Phase 2 feature statuses flipped ✅ through Step 2h; Phase 1 barcode/price/resolve flipped from 🚧 to ✅)

---

## Feature Status Key

| Status | Meaning |
|--------|---------|
| ✅ | Shipped and tested |
| 🚧 | In progress |
| ⬜ | Planned, not started |
| 🔮 | Future / aspirational |
| ❌ | Dropped / descoped |

## Classification Key

| Class | Meaning |
|-------|---------|
| **T** | Traditional — deterministic code only, no LLM |
| **AI** | AI-powered — requires LLM reasoning |
| **H** | Hybrid — AI generates, code validates/executes |

---

## Pillar 1: Price Intelligence Engine

| Feature | Status | Phase | Class | Data Source | Notes |
|---------|--------|-------|-------|-------------|-------|
| Price comparison (9 active retailers — mixed extraction) | ✅ | 1 | T | **9 active retailers** (11 originally shipped; Lowe's + Sam's Club retired 2026-04-18 with `is_active=False` rows retained for FK integrity): Amazon, Best Buy, Target, Home Depot, eBay (new + used), BackMarket, Facebook Marketplace via agent-browser containers; **Walmart via HTTP adapter routing** (Firecrawl for demo, Decodo residential proxy for production). Brand-direct `*_direct` retailers remain `is_active=True` as identity-discount redirect targets (not scraped) | Paradigm shift 2026-04-10: walmart moved to HTTP adapter. Free APIs (Best Buy, eBay Browse, Keepa) added as production speed optimization in Phase 4 |
| Walmart HTTP adapter (`WALMART_ADAPTER` flag) | ✅ | 2 | T | `backend/modules/m2_prices/adapters/{walmart_firecrawl,walmart_http}.py` — both paths parse `<script id="__NEXT_DATA__">` JSON. Firecrawl demo (~$0.00125/scrape), Decodo rotating US residential production (~$0.000466/scrape). Shared parser in `_walmart_parser.py` | Bypasses PerimeterX client-side JS fingerprinting by never executing JS. 5/5 PASS on Decodo probe 2026-04-10. One-env-var demo→prod switch |
| Price comparison (production API optimization) | ⬜ | 4 | T | Best Buy Products API (free), eBay Browse API (free), Keepa API ($15/mo) layered on top of scraper containers | API results return ~500ms vs 3-8s for containers. Fallback: API → container → skip |
| Misc retailer slot (Serper Shopping, 10th data source) | 🚧 3n | 3 | T | Step 3n / `m14_misc_retailer/` — `_serper_shopping_fetch` POSTs `google.serper.dev/shopping` (thumbnails stripped server-side, 2 credits/call ≈ $0.002 at Starter tier). Service applies `KNOWN_RETAILER_DOMAINS` filter to drop the 9 already-scraped retailers + `*_direct` mirrors, caps to top-3 by position, caches Redis 6h. PR #73 inflight pattern at 30s TTL (sized for Serper's 1.4–2.5s p50). 5 adapters swap-clean via `MISC_RETAILER_ADAPTER`: `serper_shopping` primary; `disabled` default at launch; `google_shopping_container` Z-standby + 3 managed-SERP fallbacks (`decodo_serp_api`/`oxylabs_serp_api`/`brightdata_serp_api`) as `NotImplementedError` stubs. iOS `MiscRetailerCard` behind `experiment.miscRetailerEnabled` UserDefaults flag — **Debug-default-ON / Release-default-OFF** (PR #81); standard-suite-gated so test suites still default OFF | No LLM in the call path — pure API consumer + filter + cap + cache. Vendor concentration with `vendor-migrate-1` (both use Serper) hedged by Z-standby; build trigger is bench `panel_below_alert` <75% × 2 weekly runs. Canary lever is server-side `MISC_RETAILER_ADAPTER` only (5%→50%→100% post `make bench-misc-retailer` ≥80% pass) |
| Price caching (6hr TTL, Redis + TimescaleDB hypertable) | ✅ | 1 | T | Redis 6hr TTL + `prices` table + `price_history` TimescaleDB hypertable | First query triggers live scrape; subsequent queries read from Redis → DB → containers |
| Background price ingestion workers | ✅ 2h | 2 | T | `backend/workers/price_ingestion.py` — SQS enqueue/process split reusing `PriceAggregationService.get_prices(force_refresh=True)`. Enqueue runs via `scripts/run_worker.py price-enqueue` (cron every 6h); process long-polls the queue | Keeps cache warm without duplicating service logic |
| Coupon discovery (top sources) | ⬜ | 3 | T | agent-browser batch scraping of coupon sites | Deprioritized from Phase 2 — focus on price + identity + cards first |
| Coupon validation engine | ⬜ | 3 | H | Crawlers fetch codes (T); AI validates stacking compatibility (AI) | Confidence scoring pipeline |
| Incentive spike detection | ⬜ | 4 | T | Portal bonus table — `is_elevated` computed column flags when rate > 1.5x normal | Feeds into push notifications |
| Portal bonus integration (Rakuten/TopCashback/BeFrugal) | ✅ 3g | 3 | T | Live `portal_rates` worker upserts `portal_bonuses` every 6h via AWS Lambda + EventBridge cron (3g-A, #53). `m13_portal.PortalMonetizationService.resolve_cta_list` runs a 5-step decision tree per portal: feature-flag → 24h staleness gate → MEMBER_DEEPLINK with graceful fallthrough → SIGNUP_REFERRAL with FTC disclosure → GUIDED_ONLY. Sort `(rate desc, portal asc)`; rejected candidates logged at DEBUG. iOS interstitial portal row (3g-B) renders ≤3 sorted CTAs; FTC disclosure inline + per-CTA on SIGNUP_REFERRAL only. M6 cache key extended `:c<...>:i<...>:p<sha1(active_portals)>:v5` so toggling membership in Profile busts stale recs. Funnel attribution via `affiliate_clicks.metadata.portal_event_type` (member_deeplink / signup_referral / guided_only) + `portal_source`. Resend alerting on 3 consecutive empty portal runs (24h throttle, empty key → log+skip) | Replaces `seed_portal_bonuses_demo.py` (deleted in 3g-B). Lambda hits the prod DB host directly — EC2 has no DB so the cron CANNOT share that fleet. Mike runs `infrastructure/lambda/portal_worker/deploy.sh` post-merge with `LAMBDA_ROLE_ARN` + `SECRETS_ARN` set; secrets in AWS Secrets Manager keyed `barkain/portal-worker` |
| Price prediction (buy/wait) | ⬜ | 4 | AI | Keepa historical data (Amazon) + TimescaleDB price_history + general seasonal trends (ShopSavvy-style calendars) | Prophet model + Claude reasoning on seasonal patterns |
| Post-purchase price match detection | 🔮 | 5 | H | Code monitors prices (T); AI drafts claim (AI) | Deferred — high complexity, lower priority |

### Key API & Architecture Discoveries (v3)

- **Demo uses scrapers for everything.** All 11 Phase 1 retailers use agent-browser containers. Free APIs (Best Buy Products API, eBay Browse API) and Keepa ($15/mo) are deferred to Phase 4 as a production speed optimization layer — API results return ~500ms vs 3-8s for containers.
- **Amazon PA-API deprecated April 30, 2026.** Replacement (Creators API) requires 10 qualified sales/month. **Keepa API ($15/mo) is the practical Amazon data source** — no sales gate, instant access, includes historical data. Added in Phase 4.
- **Walmart has no public pricing API.** All APIs are seller/partner only. Price data requires agent-browser scraping.
- **Target has no public API at all.** Same as Walmart — agent-browser containers only.
- **UPCitemdb requires paid tier for usable rates.** Free tier (100/day) insufficient as primary. **OpenAI charges $10/1K calls — unacceptable.** Gemini API is the primary UPC→product resolution source — cost-effective, high accuracy, 4-6s latency, YC credits. UPCitemdb kept as backup fallback.
- **Best Buy Products API** is the cleanest: free, instant key, 50K calls/day, UPC/SKU lookup with pricing. Added in Phase 4 as speed optimization.
- **eBay Browse API** is free with instant access: product search, pricing, 5K calls/day. Added in Phase 4 as speed optimization.

---

## Pillar 2: Identity & Rewards Layer

| Feature | Status | Phase | Class | Data Source | Notes |
|---------|--------|-------|-------|-------------|-------|
| User identity profile (onboarding) | ✅ 2d + Benefits Expansion | 2→3 | T | User input → `user_discount_profiles` table (17 boolean flags — 16 original + `is_young_adult` via migration 0010). Captured via 3-step iOS `IdentityOnboardingView` wizard; persisted via `POST /api/v1/identity/profile` full-replace semantics. | Captures: military/veteran, student, teacher, first responder, nurse, healthcare worker, **government** (migration 0003, Step 2d), senior, memberships (AAA/AARP/Costco/Sam's/Prime), **young adult 18–24** (migration 0010, Benefits Expansion), verification (ID.me/SheerID) |
| Card portfolio management | ✅ 2e | 2 | T | `scripts/seed_card_catalog.py` seeds 30 Tier 1 cards across 8 issuers into `card_reward_programs`. Users select cards via `CardSelectionView` → `user_cards` table. CRUD via 7 endpoints under `/api/v1/cards/*`. Profile tab shows "My Cards" chips with preferred-star badge. | 30 cards covers Chase + Amex + Capital One + Citi + Discover + BofA + Wells Fargo + US Bank. Card network cross-section chosen per CARD_REWARDS.md Tier 1. |
| Discount catalog (retailer identity programs) | ✅ 2d + Benefits Expansion | 2→3 | T | `discount_programs` table seeded via `scripts/seed_discount_catalog.py` from IDENTITY_DISCOUNTS.md (**12 brand-direct retailers** — 8 original + acer/asus/razer/logitech added in Benefits Expansion — **+ 63 program rows** expanded from 28 templates per eligibility_type). Pure-SQL zero-LLM matching in `IdentityService.get_eligible_discounts` < 150 ms, deduplicated by `(retailer_id, program_name)`. Weekly URL verification landed in Step 2h (`backend/workers/discount_verification.py`). Benefits Expansion adds 10 student-tech programs + Amazon Prime Young Adult (scope=`membership_fee`) and one new eligibility axis (`is_young_adult`, migration 0010). | Zero-LLM query-time matching via `GET /api/v1/identity/discounts?product_id=` returning EligibleDiscount list with estimated_savings computed against the program's own retailer price (per-retailer, scope-aware — 3f-hotfix) |
| Discount program URL verification (weekly) | ✅ 2h | 2 | T | `backend/workers/discount_verification.py` — httpx GET with Chrome UA + mentions-name body check. Three-state outcome: verified / `flagged_missing_mention` (soft, counter NOT incremented) / hard-failed (4xx/5xx/network → `consecutive_failures += 1`). 3 consecutive hard failures flip `is_active=False`. `last_verified` updates on every run | `discount_programs.consecutive_failures` added via migration 0005. Weekly cron via `scripts/run_worker.py discount-verify` |
| Identity discount stacking in recommendations | ⬜ | 3 | H | DB lookup for eligible discounts (T); AI synthesizes stacking rules and picks best total-cost option (AI) | Must respect per-brand stacking rules (e.g., Apple military ≠ Apple education) |
| Card reward matching (per-retailer best card) | ✅ 2e | 2 | T | `CardService.get_best_cards_for_product` — pure SQL preload of user cards + rotating + user_selections + retailer prices, then in-memory max over (base, rotating, user_selected, static) per card. < 50ms measured. Per-retailer card subtitle renders inline below `PriceRow`. | Zero-LLM. `_RETAILER_CATEGORY_TAGS` constant bridges rotating/static category strings to retailer ids. |
| Card reward purchase interstitial | ✅ 3f | 3 | T | `PurchaseInterstitialSheet` slides up before the browser hand-off from both hero CTA + retailer row taps. Restates winning card + baseline-1% delta + conditional rotating-bonus activation block (opens issuer URL in SFSafari, flips `activationAcknowledged` optimistically). Continue button calls `/affiliate/click` with `activation_skipped` telemetry (2026-04-21). **Portal CTA row + FTC disclosure shipped Step 3g (3g-A backend / 3g-B iOS).** **savings-math-prominence:** the canonical `StackingReceiptView` (also rendered on the recommendation hero) replaces the previous 1-line `summaryBlock` so the per-line math is visible at the same hierarchy in both surfaces. | Reuses `/api/v1/recommend` + existing `CardRecommendation` list; zero new backend stacking logic. Migration 0008 adds `affiliate_clicks.metadata` JSONB; 3g-B extends the JSONB shape with `portal_event_type` + `portal_source` (no migration). Activation ack is session-scoped — issuer is source of truth. `PurchaseInterstitialContext` extended w/ `identitySavings` / `identitySource` / `portalSavings` / `portalSource` so the receipt has its data on the winner-init path (price-row init defaults to zeros, suppressing those lines) |
| Rotating category tracking (quarterly) | 🟡 2e→3 | 2→3 | T | Step 2e seeded Q2 2026 manually from CARD_REWARDS.md (Freedom Flex, Discover it). Phase 3 adds scraping 4x/year via agent-browser (Doctor of Credit quarterly roundup → issuer pages fallback). | Chase Freedom Flex, Discover it, Citi Dividend, US Bank Cash+, BofA Customized Cash |
| User-selected category capture | ✅ 2e | 2 | T | `user_category_selections` table + `POST /api/v1/cards/my-cards/{id}/categories`. iOS `CategorySelectionSheet` renders after adding a Cash+ / Customized Cash card. Allowed-list enforced by backend against `category_bonuses[user_selected].allowed`. | Cash+, Customized Cash, Shopper Cash Rewards — each card carries its own `allowed` picker list in the seed catalog |
| Shopping portal rate tracking | ✅ 2h | 2 | T | `backend/workers/portal_rates.py` — httpx+BeautifulSoup scrape of Rakuten / TopCashBack / BeFrugal every 6 hours via `scripts/run_worker.py portal-rates`. Chase Shop Through Chase + Capital One Shopping deferred (auth-gated). Pure-function parsers anchored on stable attributes (aria-label / semantic class names); committed HTML fixtures in `backend/tests/fixtures/portal_rates/` | `portal_bonuses` table with `is_elevated` GENERATED ALWAYS STORED column; Rakuten's "was X%" marker refreshes `normal_value` baseline |
| Card-linked offers (Amex/Chase/Citi Offers) | 🔮 | 5+ | H | DEFERRED — requires issuer auth flows, 2FA, anti-bot. Unsustainable for solo dev | Phase 1-4: passive guidance ("Check your Chase app for offers at Best Buy") |

### Verification Platforms Tracked

| Platform | Groups Verified | Used By |
|----------|----------------|---------|
| ID.me | Military, veterans, first responders, nurses, students, teachers, government, seniors | Apple, Samsung, HP, Lenovo, Sony, LG, Lowe's, T-Mobile, Verizon |
| SheerID | Military, students, teachers, first responders, healthcare, seniors | Home Depot, Amazon (select), Spotify, Microsoft |
| WeSalute | Military, veterans, family | Samsung, Dell, Acer |
| GovX | Military, government, law enforcement, firefighters | 1,000+ brands (standalone marketplace) |
| UNiDAYS | Students | Apple, Samsung, Nike, Adidas, ASOS |
| StudentBeans | Students | Dell, ASOS, various apparel |

---

## Pillar 3: Scanning & Recognition

| Feature | Status | Phase | Class | Data Source | Notes |
|---------|--------|-------|-------|-------------|-------|
| Barcode scanning (AVFoundation) | ✅ | 1 | T | Native iOS since iOS 7. UPC sent to backend for resolution | Triggers full price comparison pipeline. Step 1g: scanner captures barcodes, resolves product via backend. Step 1h: scan → resolve → price comparison UI complete. Post-2b-val: `ScannerView` also exposes a `⌨️` toolbar button that opens a manual UPC entry sheet — same code path via `ScannerViewModel.handleBarcodeScan(upc:)` — used for simulator testing (no camera) and as a fallback for damaged/missing barcodes. **sim-edge-case-fixes-v1 (#65):** Manual UPC field is now `.numberPad` w/ on-input digit-only filter (handles paste); client-side 12/13-digit guard surfaces an inline red error and KEEPS THE SHEET OPEN with the typed text intact, rather than auto-dismissing into a generic scanner "Try Again" |
| Image-based product identification | ⬜ | 3 | AI | Claude Sonnet vision via backend; no deterministic path | Camera → backend → Claude Vision → product resolution |
| Receipt scanning (OCR → savings calc) | ⬜ | 3 | H | **On-device:** VisionKit `VNDocumentCameraViewController` (iOS 13+) for capture, Vision `VNRecognizeTextRequest` (iOS 13+) for text extraction. Backend receives structured text only (not images) — cost optimization | Code matches products + calcs savings (T) |
| Product resolution (UPC → canonical) | ✅ | 1 | H | Gemini API UPC lookup (primary, 4-6s, high accuracy, YC credits) → UPCitemdb API (backup, free 100/day, cross-validation) → PostgreSQL persistent + Redis cache (24hr TTL). Gemini output includes `device_name` + `model` (shortest unambiguous identifier) which is stored in `source_raw.gemini_model` and feeds M2 relevance scoring | AI resolves barcode to product name/brand/category. Cached aggressively — most barcodes only looked up once. Cross-validation added in Step 2b. **sim-edge-case-fixes-v1 (#65):** `service.py:resolve` now reject-short-circuits all-same-digit UPCs (`^(\d)\1{11,12}$`) BEFORE Gemini is invoked, returning `ProductNotFoundError`. Without this guard, Gemini hallucinated a plausible product for any 12-digit input and `_persist_product()` polluted PG with the speculative row forever (verified in original sim drive: `000000000000` → "ORGANIC BLUE CORN TORTILLA CHIPS"). Cheaper / more specific than a GS1 mod-10 checksum, which would also reject many legitimate UPCs |

### iOS Scanning Framework Notes

- **AVFoundation** barcode scanning: iOS 7+ (very mature)
- **Vision framework** OCR (`VNRecognizeTextRequest`): iOS 13+
- **VisionKit `VNDocumentCameraViewController`**: iOS 13+ (document camera UI)
- **VisionKit `DataScannerViewController`**: iOS 16+ (live camera text/barcode recognition — requires A12 Bionic or later)
- Receipt OCR strategy: extract text on-device via Vision framework, send only structured strings to backend. Never send full images — saves bandwidth and API costs.

---

## Pillar 4: Intelligence & Alerts

| Feature | Status | Phase | Class | Notes |
|---------|--------|-------|-------|-------|
| Full-stack recommendation engine | ✅ | 3 | T | **Step 3e (deterministic stacking — reclassified from AI)**. `POST /api/v1/recommend` gathers prices + identity + cards + portals in one `asyncio.gather` then stacks in pure Python (p95 < 150 ms). Winner = lowest `effective_cost` (base − identity, minus deferred card + portal rebates); tiebreaks = new>refurb>used, then well-known retailer. Brand-direct callout for ≥15 % identity program at `*_direct` retailer. Sentence templates generate headline + "why" copy. iOS `RecommendationHero` renders only after SSE done + identity + cards all settle. No LLM — can layer Sonnet narration in Phase 4 if demo feedback demands flair |
| Push notifications (price drops) | 🔮 | 5 | T | Coming soon — requires item tracking infrastructure with higher compute costs. Event-driven dispatch on threshold triggers |
| Push notifications (incentive spikes) | 🔮 | 5 | T | Coming soon — scheduled spike check from `portal_bonuses.is_elevated` → notify |
| Savings dashboard (running totals) | ⬜ | 3 | T | Aggregation queries on receipt data |
| Listing quality scoring (eBay/secondary) | ⬜ | 4 | AI | Analyze photos, seller history, pricing anomalies |
| Negotiation intelligence (Marketplace) | 🔮 | 5+ | AI | Listing age, price history → suggested offer |
| Watched items list | ⬜ | 4 | T | User saves products, system monitors prices over time. Paired with price prediction for buy/wait intelligence |

### Changes from v2

- **9 active retailers in prod** (11 originally shipped; Lowe's + Sam's Club retired 2026-04-18). Container infrastructure moves from Phase 2 → Phase 1.
- **Free APIs (Best Buy, eBay Browse) and Keepa moved to Phase 4** as production speed optimization.
- **Watched items moved to Phase 4** (from Phase 5). Paired with price prediction — natural fit.
- **Push notifications remain Phase 5.**

---

## Pillar 5: Revenue Infrastructure

| Feature | Status | Phase | Class | Notes |
|---------|--------|-------|-------|-------|
| StoreKit 2 subscription (free/pro ~$7.99/mo) | ✅ | 2 | T | Via RevenueCat purchases-ios-spm v5.67.2. `Barkain Pro` entitlement gates UI; backend `users.subscription_tier` syncs via `POST /api/v1/billing/webhook`. Three product slots (lifetime / yearly / monthly) configured in RC dashboard — pricing not hardcoded in client (Step 2f) |
| Feature gating (tier-based) | ✅ | 2 | T | `FeatureGateService` + `SubscriptionService`. Free: 10 scans/day (local TZ rollover), first 3 identity discounts, no card recommendations. Pro: unlimited. Backend rate limiter doubles thresholds for pro users via Redis-cached tier (60s TTL) (Step 2f) |
| Affiliate link routing | ✅ | 2 | T | **Step 2g** — `AffiliateService.build_affiliate_url` pure `@staticmethod`. Amazon → `?tag=barkain-20`, eBay → rover redirect with `campid=5339148665`, Walmart → Impact Radius placeholder (passthrough while `WALMART_AFFILIATE_ID` empty), Best Buy + others → untagged. iOS retailer taps round-trip through `POST /api/v1/affiliate/click` — tagged URL opens in `SFSafariViewController` (cookies shared with Safari). |
| Affiliate commission tracking | ✅ | 2 | T | **Step 2g** — `POST /api/v1/affiliate/click` logs every tap in `affiliate_clicks` with `affiliate_network` set to `amazon_associates` / `ebay_partner` / `walmart_impact` / `passthrough` sentinel. `GET /api/v1/affiliate/stats` groups by retailer. `POST /api/v1/affiliate/conversion` placeholder webhook in place for future sale-attribution callbacks. |
| Brand cashback partnerships | 🔮 | 6+ | T | Partner with brands for cash back offers — future revenue stream |
| Anonymized data product (opt-in) | 🔮 | 6+ | T | B2B data pipeline, aggregated only. Deferred post-scale — one data scandal kills trust |

### Affiliate Timeline Reality

Affiliate connections take weeks to establish (Amazon Associates requires live website with 10+ posts, eBay Partner Network takes days, CJ Affiliate network + per-merchant approvals take 1-3 weeks each). **Subscription revenue covers the gap.** Affiliate infrastructure is Phase 2 but revenue from it won't flow until well after launch.

---

## Platform Features

| Feature | Status | Phase | Class | Notes |
|---------|--------|-------|-------|-------|
| Clerk authentication | ✅ | 1 | T | JWT validation via `clerk-backend-api`, session management. MCP server for dev inspection. `DEMO_MODE=1` bypass (renamed from `BARKAIN_DEMO_MODE` in 2i-b; read via `settings.DEMO_MODE`) for local physical-device testing |
| API rate limiting | ✅ | 1 | T | Redis-backed sliding window, per-user. Tier-aware in 2f: pro users get base × `RATE_LIMIT_PRO_MULTIPLIER` (default 2×). Tier cached in Redis `tier:{user_id}` with 60s TTL |
| Docker local development | ✅ | 1 | T | PostgreSQL+TimescaleDB, Test DB, Redis via docker-compose.yml. LocalStack added in Step 2h for SQS emulation |
| agent-browser scraper containers | ✅ | 1 | T | Per-retailer Docker containers: Chrome + agent-browser + extraction script. 9 active retailers (Lowe's + Sam's Club retired 2026-04-18; rows kept `is_active=False` for FK integrity) + shared base image (`containers/base/`) |
| Self-healing Watchdog (supervisor agent) | ✅ 2a | 2 | H | `backend/workers/watchdog.py` — monitors script health, classifies failures (transient/selector_drift/blocked), auto-heals via Claude Opus (YC credits). Escalates to developer after 3 failed heal attempts. Nightly via `scripts/run_watchdog.py --check-all` |
| Background job processing | ✅ 2h | 2 | T | SQS (LocalStack in dev, real AWS in prod) + `scripts/run_worker.py` CLI. 4 workers: price ingestion, portal rates, discount verification, watchdog |
| Web dashboard | 🔮 | 5+ | T | Next.js on Vercel |
| Android app | 🔮 | 6+ | T | Kotlin / KMP |
| Dark mode | ⬜ | 1 | T | Design system uses semantic colors but full dark-mode audit deferred |

---

## Classification Summary

| Classification | Count | Percentage |
|---|---|---|
| Traditional (T) | 25 | 61% |
| AI | 5 | 12% |
| Hybrid (H) | 7 | 17% |
| Future (🔮, not classified) | 4 | 10% |

**Rule:** If a feature is classified as Traditional, do NOT use LLM calls for it. Check this table before implementing.

---

## Cross-Reference

| Document | What It Adds |
|----------|-------------|
| CARD_REWARDS.md | Full card catalog data model, rotating category sources, portal rate tracking, query-time matching algorithm, purchase interstitial UX |
| IDENTITY_DISCOUNTS.md | Complete identity group × retailer matrix, verification platform registry, stacking rules, scraping priority URLs |
| SEARCH_STRATEGY.md | Query flow (scan → resolve → cache check → scrape → recommend), tool-to-site matrix, cost model, fallback chain |
| SCRAPING_AGENT_ARCHITECTURE.md | Container architecture, Watchdog self-healing flow, probe template library, full schema definitions |
| agent-browser-scraping-guide.md | DOM eval extraction pattern, site-specific findings, anti-detection strategies, anchor selector rules |
