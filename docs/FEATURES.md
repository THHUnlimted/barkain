# Barkain — Feature Inventory

> Source: Project Planning Questionnaire + Architecture Sessions, March–April 2026
> Scope: Every feature, status, AI/Traditional/Hybrid classification, data source
> Last updated: April 2026 (v3 — cache TTL corrected, Open Food Facts deferred, Opus for Watchdog, nurse/healthcare flags)

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
| Price comparison (11 retailers — all scraped) | ⬜ | 1 | T | agent-browser containers for all retailers: Amazon, Best Buy, Walmart, Target, Home Depot, Lowe's, eBay (new), eBay (used/refurb), Sam's Club, BackMarket, Facebook Marketplace | Demo uses scrapers for everything. Free APIs (Best Buy, eBay Browse, Keepa) added as production speed optimization in Phase 4 |
| Price comparison (production API optimization) | ⬜ | 4 | T | Best Buy Products API (free), eBay Browse API (free), Keepa API ($15/mo) layered on top of scraper containers | API results return ~500ms vs 3-8s for containers. Fallback: API → container → skip |
| Price caching (6hr TTL, TimescaleDB) | ⬜ | 1 | T | TimescaleDB hypertable | First query triggers live scrape; subsequent queries read from cache |
| Background price ingestion workers | ⬜ | 2 | T | SQS + scheduled fetchers per retailer container | Keeps cache warm for popular products |
| Coupon discovery (top sources) | ⬜ | 3 | T | agent-browser batch scraping of coupon sites | Deprioritized from Phase 2 — focus on price + identity + cards first |
| Coupon validation engine | ⬜ | 3 | H | Crawlers fetch codes (T); AI validates stacking compatibility (AI) | Confidence scoring pipeline |
| Incentive spike detection | ⬜ | 4 | T | Portal bonus table — `is_elevated` computed column flags when rate > 1.5x normal | Feeds into push notifications |
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
| User identity profile (onboarding) | ⬜ | 2 | T | User input → `user_discount_profiles` table | Captures: military/veteran, student, teacher, first responder, nurse, healthcare worker, government, senior, memberships |
| Card portfolio management | ⬜ | 2 | T | User selects from `card_reward_programs` catalog → `user_cards` table | Seed top ~30 cards covering 80%+ of US cardholders |
| Discount catalog (retailer identity programs) | ⬜ | 2 | T | `discount_programs` table seeded from IDENTITY_DISCOUNTS.md; maintained by weekly agent-browser batch scraping of ID.me, SheerID, GovX, WeSalute, UNiDAYS, StudentBeans directories | Zero-LLM query-time matching |
| Identity discount stacking in recommendations | ⬜ | 3 | H | DB lookup for eligible discounts (T); AI synthesizes stacking rules and picks best total-cost option (AI) | Must respect per-brand stacking rules (e.g., Apple military ≠ Apple education) |
| Card reward optimization (purchase interstitial) | ⬜ | 3 | T | `card_reward_programs` + `rotating_categories` + `portal_bonuses` tables → pure SQL matching at query time | Zero-LLM. < 50ms target. Shows card recommendation overlay before affiliate redirect |
| Rotating category tracking (quarterly) | ⬜ | 3 | T | Doctor of Credit quarterly roundup (primary), issuer pages (fallback). Scraped 4x/year via agent-browser. Human review before publish | Chase Freedom Flex, Discover it, Citi Dividend, US Bank Cash+, BofA Customized Cash |
| User-selected category capture | ⬜ | 4 | T | `user_category_selections` table for US Bank Cash+, BofA Customized Cash (user picks own categories) | Prompt users at quarter start |
| Shopping portal rate tracking | ⬜ | 3 | T | agent-browser batch job every 6 hours scraping Rakuten, TopCashBack, BeFrugal, Chase Shop Through Chase, Capital One Shopping | `portal_bonuses` table with `is_elevated` spike detection |
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
| Barcode scanning (AVFoundation) | ⬜ | 1 | T | Native iOS since iOS 7. UPC sent to backend for resolution | Triggers full price comparison pipeline |
| Image-based product identification | ⬜ | 3 | AI | Claude Sonnet vision via backend; no deterministic path | Camera → backend → Claude Vision → product resolution |
| Receipt scanning (OCR → savings calc) | ⬜ | 3 | H | **On-device:** VisionKit `VNDocumentCameraViewController` (iOS 13+) for capture, Vision `VNRecognizeTextRequest` (iOS 13+) for text extraction. Backend receives structured text only (not images) — cost optimization | Code matches products + calcs savings (T) |
| Product resolution (UPC → canonical) | 🚧 | 1 | H | Gemini API UPC lookup (primary, 4-6s, high accuracy, YC credits) → UPCitemdb API (backup, free 100/day) → PostgreSQL persistent + Redis cache (24hr TTL) | AI resolves barcode to product name/brand/category. Cached aggressively — most barcodes only looked up once. **Step 1b: backend service + endpoint operational** |

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
| Full-stack recommendation engine | ⬜ | 3 | AI | Synthesizes all layers (prices + identity + cards + portals + coupons + secondary market + wait signal) into single recommendation via Claude Sonnet. Re-fires as more data streams in |
| Push notifications (price drops) | 🔮 | 5 | T | Coming soon — requires item tracking infrastructure with higher compute costs. Event-driven dispatch on threshold triggers |
| Push notifications (incentive spikes) | 🔮 | 5 | T | Coming soon — scheduled spike check from `portal_bonuses.is_elevated` → notify |
| Savings dashboard (running totals) | ⬜ | 3 | T | Aggregation queries on receipt data |
| Listing quality scoring (eBay/secondary) | ⬜ | 4 | AI | Analyze photos, seller history, pricing anomalies |
| Negotiation intelligence (Marketplace) | 🔮 | 5+ | AI | Listing age, price history → suggested offer |
| Watched items list | ⬜ | 4 | T | User saves products, system monitors prices over time. Paired with price prediction for buy/wait intelligence |

### Changes from v2

- **All 11 Phase 1 retailers now use scrapers** (was 3 APIs). Container infrastructure moves from Phase 2 → Phase 1.
- **Free APIs (Best Buy, eBay Browse) and Keepa moved to Phase 4** as production speed optimization.
- **Watched items moved to Phase 4** (from Phase 5). Paired with price prediction — natural fit.
- **Push notifications remain Phase 5.**

---

## Pillar 5: Revenue Infrastructure

| Feature | Status | Phase | Class | Notes |
|---------|--------|-------|-------|-------|
| StoreKit 2 subscription (free/pro ~$7.99/mo) | ⬜ | 2 | T | Via RevenueCat for simplified management. Must be deterministic and auditable |
| Feature gating (tier-based) | ⬜ | 2 | T | Feature flags per subscription level |
| Affiliate link routing | ⬜ | 2 | T | URL construction with tracking params. Amazon Associates tag, eBay Partner Network campaign ID, CJ Affiliate links (Best Buy, Walmart, Target) |
| Affiliate commission tracking | ⬜ | 2 | T | Click → sale attribution logging in `affiliate_clicks` table |
| Brand cashback partnerships | 🔮 | 6+ | T | Partner with brands for cash back offers — future revenue stream |
| Anonymized data product (opt-in) | 🔮 | 6+ | T | B2B data pipeline, aggregated only. Deferred post-scale — one data scandal kills trust |

### Affiliate Timeline Reality

Affiliate connections take weeks to establish (Amazon Associates requires live website with 10+ posts, eBay Partner Network takes days, CJ Affiliate network + per-merchant approvals take 1-3 weeks each). **Subscription revenue covers the gap.** Affiliate infrastructure is Phase 2 but revenue from it won't flow until well after launch.

---

## Platform Features

| Feature | Status | Phase | Class | Notes |
|---------|--------|-------|-------|-------|
| Clerk authentication | ⬜ | 1 | T | JWT validation, session management. MCP server for dev inspection |
| API rate limiting | ⬜ | 1 | T | Redis-backed per-user limits |
| Docker local development | ⬜ | 1 | T | PostgreSQL+TimescaleDB, Redis via docker-compose.yml. LocalStack added in Phase 2 |
| agent-browser scraper containers | ⬜ | 1 | T | Per-retailer Docker containers: Chrome + agent-browser + extraction script. 11 retailers from day 1 |
| Self-healing Watchdog (supervisor agent) | ⬜ | 2 | H | Monitors script health, classifies failures (transient/selector_drift/blocked), auto-heals via Claude Opus (YC credits). Escalates to developer after 3 failed heal attempts |
| Background job processing | ⬜ | 2 | T | SQS + worker scripts |
| Web dashboard | 🔮 | 5+ | T | Next.js on Vercel |
| Android app | 🔮 | 6+ | T | Kotlin / KMP |
| Dark mode | ⬜ | 1 | T | Part of design system from day one |

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
