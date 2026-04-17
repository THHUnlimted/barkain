# Barkain — Search & Data Acquisition Strategy

> Source: Planning sessions, March–April 2026
> Last updated: April 3, 2026 (v5 — all 11 Phase 1 retailers scraped, APIs deferred to Phase 4 production optimization, Costco/Newegg/B&H/Kohl's deferred)
> Companion docs: SCRAPING_AGENT_ARCHITECTURE.md, agent-browser-scraping-guide.md, IDENTITY_DISCOUNTS.md

---

## Design Principles

1. **Speed-first, progressive loading.** Retail prices from DB cache render in <250ms. On cache miss, onboarding filter questions buy 3-5s of background scraping time. Secondary market results stream in progressively.
2. **Per-query scraping, cached to 6hr DB.** First query for a product triggers live agent-browser scrapes across retailers. Results are cached in TimescaleDB with 6hr TTL. Subsequent queries for the same product within 6hr read from DB at near-zero cost.
3. **agent-browser for demo, APIs for production speed.** Demo uses agent-browser containers for ALL retailers. Phase 4 adds free APIs (Best Buy, eBay Browse) and Keepa as a speed optimization layer. Firecrawl is the absolute last resort.
4. **Pre-filter before fetch.** Condition, price range, seller location, and listing age are gate checks on secondary markets. Never spend credits on a listing that fails the gate.
5. **6-hour cache default.** All retail prices cache for 6 hours in TimescaleDB. Secondary market listings cache for 30 min in Redis.
6. **Containerized per-retailer.** Each retailer runs in its own Docker container with: the extraction script, an agent-browser + Chromium instance, an AI health-management agent, and any required auth state. The backend sends requests to containers; containers return structured JSON.
7. **Coupons deprioritized this phase.** Coupon discovery/validation is deferred. Focus is on price comparison + identity discounts + card rewards.

---

## Scraping Tool: agent-browser

`agent-browser` is a CLI tool that controls Chrome/Chromium via Chrome DevTools Protocol (CDP). It's the **only** scraping tool used — no Playwright.

**Why agent-browser over Playwright:**
- Shell-scriptable — bash-based automation pipelines, no Node.js runtime needed
- DOM eval pattern wins every time — fastest (avg 515ms) AND highest quality (grade A) across all tested sites
- Anti-detection built into launch flags (`--disable-blink-features=AutomationControlled`)
- Tested and proven on Walmart, Amazon, Target, Facebook Marketplace, Costco (35+ method tests, 100+ live requests)

**Winning extraction pattern:** DOM eval via `eval --stdin` — runs targeted JS in page context, returns structured JSON. Every production script follows the same 9-step architecture: kill stale sessions → launch Chrome → warm up → navigate → bot check → handle overlays → scroll → extract via DOM eval → validate output.

**Anchor selector rule:** Always use data attributes (`[data-item-id]`, `[data-test="..."]`) or URL patterns (`a[href*="/item/"]`), never CSS classes.

### Site-Specific Findings (from 35+ tests)

| Site | Bot Detection | Anchor Selector | Key Gotchas |
|---|---|---|---|
| **Walmart** | PerimeterX — NEVER use `agent-browser open` for nav; launch Chrome directly with target URL | `[data-item-id]` | Prices split across 3 `<span>` elements; use `innerText` of container |
| **Amazon** | Moderate — headed Chrome works, headless blocked | `[data-component-type="s-search-result"]` + `data-asin` | Two title layouts; sponsored noise in title text; 17 fields extractable |
| **Target** | Akamai — occasional, rare with headed Chrome | `[data-test="@web/site-top-of-funnel/ProductCardWrapper"]` | Use `wait --load load` NOT `networkidle` (analytics pixels hang forever) |
| **Facebook Marketplace** | None observed — more permissive than Costco. Faster response, no pricing gates. | `a[href*="/marketplace/item/"]` | A11y tree gated behind auth, but DOM fully rendered behind CSS overlay. Modal-hide (`display:none`) completely reliable at volume. |
| **Costco** | None — 100 rapid-fire requests, 0 blocks | `a[href*=".product."]` + `data-testid` | **Member pricing is server-side gated** — zero price data without auth. **PRODUCTION ONLY — drop from demo.** |

---

## Launch Scope

### Product Categories (Phase 1)

| Category | Example Products | Why First |
|---|---|---|
| Consumer Electronics | TVs, headphones, tablets, laptops, cameras | Highest price variance, universal UPCs, 5+ retailer overlap, tariff-driven volatility |
| Small Kitchen Appliances | Air fryers, Instant Pots, coffee makers, blenders | 7+ retailer availability, $30-300 range, $20-40 swings common |
| Smart Home Devices | Smart speakers, security cameras, thermostats, plugs | Universal SKUs, sold everywhere, price fluctuates around events |
| Major Appliances | Refrigerators, washers, dryers, dishwashers | Highest absolute savings ($100-400), hero marketing story |

---

## Phase 1 Demo Retailers (11 — All Scraped)

### Extraction Method per Retailer

> **Architecture:** ALL retailers use agent-browser containers for the demo. Free APIs (Best Buy Products API, eBay Browse API) and Keepa are deferred to Phase 4 as a production speed optimization layer (API ~500ms vs container 3-8s).

| # | Retailer | Demo Method | Production Optimization (Phase 4) | Container? | Identity Layer Value |
|---|---|---|---|---|---|
| 1 | **Amazon** | **agent-browser** — DOM eval, `[data-component-type]` + `data-asin`, headed Chrome required | Keepa API ($15/mo) for price + history | Yes | Prime membership |
| 2 | **Best Buy** | **agent-browser** — DOM eval | Best Buy Products API (free, 50K/day) | Yes | My Best Buy rewards, credit card 5% |
| 3 | **Walmart** | **agent-browser** — DOM eval, `[data-item-id]`, PerimeterX workaround (launch Chrome with URL directly) | None (no public API) | Yes | Walmart+ membership |
| 4 | **Target** | **agent-browser** — DOM eval, `[data-test]` selectors, `load` wait strategy | None (no public API) | Yes | Target Circle, RedCard 5% |
| 5 | **Home Depot** | **agent-browser** — DOM eval | None (no public API) | Yes | Military 10% (SheerID), Pro Xtra |
| 6 | **Lowe's** | **agent-browser** — DOM eval | None (no public API) | Yes | Military 10% (ID.me), MyLowe's |
| 7 | **eBay (new)** | **agent-browser** — DOM eval, condition filter | eBay Browse API (free, 5K/day) | Yes | eBay Bucks |
| 8 | **eBay (used/refurb)** | **agent-browser** — DOM eval, condition filter | Same Browse API | Yes | — |
| 9 | **Sam's Club** | **agent-browser** — DOM eval. No auth issues — works without login. | None | Yes | Membership pricing, Sam's Mastercard 5% |
| 10 | **BackMarket** | **agent-browser** — DOM eval. Pursuing API access for production. | BackMarket API (if approved) | Yes | Certified refurb with warranty |
| 11 | **Facebook Marketplace** | **agent-browser** — DOM eval, hide login modal (`display:none`), URL-pattern selector. | None | Yes | Local deals |

**Summary: ALL 11 retailers scraped via agent-browser containers. UPC→product resolution via Gemini API (primary) + UPCitemdb (backup). Free retail APIs + Keepa added as Phase 4 production speed layer.**

### Retailers Deferred (Not in Phase 1 Demo)

| Retailer | Reason | When |
|----------|--------|------|
| Costco | Member pricing is server-side gated — requires auth session | Production (Phase 2+) |
| Newegg | Lower priority — add after core 11 are stable | Phase 2+ |
| B&H Photo | Lower priority | Phase 2+ |
| Kohl's | Lower priority | Phase 2+ |

### Container Architecture

Each agent-browser retailer runs in its own Docker container:

```
┌─────────────────────────────────────┐
│  Container: walmart-scraper          │
│  ├── chromium (headed mode)          │
│  ├── agent-browser CLI               │
│  ├── walmart-extract.sh              │
│  ├── extract.js (DOM eval script)    │
│  ├── config.json (selectors, health) │
│  ├── test_fixtures.json              │
│  └── AI health agent (Watchdog)      │
│       └── monitors extraction health │
│           auto-heals selector drift  │
│           uses Claude Opus (YC cred) │
└─────────────────────────────────────┘
```

Backend sends requests to containers via internal API:
```
POST /extract
{
  "query": "Samsung 65 inch TV",
  "product_id": "UPC-123456",
  "max_listings": 10
}

→ Container runs extraction script
→ Returns structured JSON with prices, availability, URLs
→ Backend caches result in TimescaleDB (6hr TTL)
```

---

## Query Flow: Scan to Recommendation

### Step 3a — Text Search Entry Point (LIVE since Step 3a, 2026-04-16)

The Search tab is now the third discovery surface alongside barcode scan and manual UPC entry. `POST /api/v1/products/search` accepts a normalized free-text query and returns a ranked list of products that the user taps to enter the standard price-comparison flow.

Flow:
```
User types query in Search tab (iOS SearchView, 300 ms debounce)
         │
         ▼
┌─────────────────────────────────────────────────┐
│  POST /api/v1/products/search                    │
│  ───────────────────────────────                 │
│  1. Normalize (lowercase, collapse whitespace,   │
│     strip surrounding punctuation)               │
│  2. Check Redis: search:query:{sha256[:16]}:{n}  │
│     (24h TTL — shared across users)              │
│  3. DB fuzzy match via pg_trgm similarity on     │
│     products.name (threshold 0.3, backed by      │
│     idx_products_name_trgm GIN index from        │
│     migration 0007)                              │
│  4. If <3 DB rows OR top similarity <0.5 →       │
│     call Gemini with Google Search grounding     │
│     (system instruction in                       │
│      ai/prompts/product_search.py — DO NOT       │
│      CONDENSE marker). Retry once on null.       │
│  5. Dedupe Gemini vs DB on lowercased            │
│     (brand, name) tuple — DB results win ties.   │
│  6. Cache the merged response. Gemini rows are   │
│     NOT persisted to products.                   │
└─────────────────────────────────────────────────┘
         │
         ▼
User taps a result
         │
         ├── source == "db"  → reuse Product row (no extra request)
         └── source == "gemini" + primary_upc set → POST /products/resolve
                                                    (standard Gemini + UPCitemdb
                                                    cross-validation path)
         │
         ▼
   ┌───────────────┐
   │   Step 0      │  (existing barcode flow continues from here)
   └───────────────┘
```

Indexing scope: the DB leg matches against whatever is already in `products`. Barkain does not index a full retailer catalog — `products` grows organically as users scan/resolve UPCs. For cold brand + category queries the DB leg will miss and Gemini's grounded search fills the gap. Redis caching ensures the second user asking the same question in 24h avoids both legs entirely.

---

```
USER ACTION (barcode scan / image scan / text search)
         │
         ▼
┌─────────────────────────────────────┐
│  STEP 0: Product Resolution (<200ms)│
│  ─────────────────────────────────  │
│  Input → UPC / ASIN / search text   │
│  Check: PG product cache            │
│  Miss → Gemini API UPC lookup (4-6s) │
│  Result: canonical product_id,      │
│          name, brand, category,     │
│          known ASINs/UPCs           │
│  Gate: If unresolved → Claude       │
│        Vision for image scan        │
└──────────────┬──────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  STEP 1: Cache Check + Onboarding Buffer                 │
│  ──────────────────────────────────                      │
│  Check TimescaleDB: product_id → cached prices           │
│                                                          │
│  IF CACHE HIT (within 6hr):                              │
│    → Return retail prices immediately (<50ms)             │
│    → Skip to Step 3 (AI recommendation)                  │
│                                                          │
│  IF CACHE MISS:                                          │
│    → Start background scraping (Step 2)                  │
│    → SIMULTANEOUSLY show onboarding filter questions:    │
│      "New or used?" / "Any condition preferences?"       │
│      "Which stores do you shop at?"                      │
│      These questions buy 3-5 seconds for scrapers.       │
│    → As user answers, results stream in progressively    │
│                                                          │
│  >>> UI: Either instant prices OR filter questions <<<   │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  STEP 2: Live Scraping — PARALLEL (on cache miss only)   │
│  ──────────────────────────────────                      │
│  Fires requests to retailer containers simultaneously.   │
│  Results stream to UI as each container responds.        │
│                                                          │
│  [A] Best Buy API (FREE, ~200ms)                         │
│      → Products API: price, availability, open-box       │
│      → Always first to respond (fastest)                 │
│                                                          │
│  [B] eBay Browse API (FREE, ~300ms)                      │
│      → New condition: third-party sellers undercutting    │
│      → Used/refurb: pre-filtered by condition, price     │
│         ±50%, seller score >95%                          │
│                                                          │
│  [C] Keepa API ($0.01, ~500ms)                           │
│      → Amazon price + 90-day history                     │
│      → Buy-now-or-wait signal                            │
│                                                          │
│  [D] agent-browser containers (~3-8s each)               │
│      → Walmart, Target, Home Depot, Lowe's, Costco,     │
│        Newegg, B&H, Kohl's, Sam's Club, BackMarket      │
│      → Each container: launch Chrome → warm up →         │
│        navigate → bot check → scroll → DOM eval →        │
│        return structured JSON                            │
│      → Results cached to TimescaleDB (6hr TTL)           │
│                                                          │
│  [E] Facebook Marketplace (agent-browser, gated)         │
│      → ONLY fires if: location enabled + electronics/    │
│        appliances + retail price >$50                    │
│      → Pre-filter: age <21d, price ±50%, metro area      │
│      → Hide login modal (display:none) — reliable        │
│      → More permissive than Costco — no pricing gates,   │
│        faster response times                             │
│                                                          │
│  >>> UI: Cards appear progressively as each source <<<   │
│  >>> resolves. Free APIs first, containers stream in <<< │
│                                                          │
│  MERGE: Deduplicate by retailer.                         │
│  Cache ALL results to TimescaleDB (6hr TTL).             │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  STEP 3: AI Recommendation — Claude Sonnet (<2s)         │
│  ──────────────────────────────────                      │
│  Fires as soon as first prices arrive (even partial).    │
│  Re-fires as more results stream in (updated rec).       │
│                                                          │
│  Input:                                                  │
│   - All prices received so far                           │
│   - User identity profile (from onboarding):             │
│     military/veteran, student, teacher, first responder  │
│   - Identity discounts per retailer (from DB — scraped   │
│     continuously from ID.me, SheerID, WeSalute, GovX,   │
│     UNiDAYS, StudentBeans directories)                   │
│   - Card reward rates per retailer (quarterly DB)        │
│   - Portal bonuses per retailer (from DB)                │
│                                                          │
│  Output: Single "best move" recommendation               │
│   - Best retailer + total effective price                │
│   - Which card to use and why                            │
│   - Applicable identity discounts + verification path    │
│   - Portal bonus to stack                                │
│   - Wait/buy signal (if Keepa history available)         │
│   - Secondary market alternative if >20% savings         │
│                                                          │
│  >>> UI: Recommendation banner. Updates as data flows <<< │
└──────────────────────────────────────────────────────────┘
```

### The Onboarding Buffer Pattern

On a cold cache miss, onboarding filter questions serve dual purpose:

1. **UX value** — filters narrow results to what the user actually wants (new vs used, condition preferences, preferred stores)
2. **Loading buffer** — while the user is answering 2-3 quick-tap questions (~3-5 seconds), agent-browser containers are scraping retailers in the background

By the time the user finishes the last filter question, free API results (Best Buy, eBay, Keepa) are ready, and several agent-browser containers have responded. The UI transitions seamlessly from questions to results.

**On subsequent searches** (cache hit), no questions needed — prices appear instantly from the 6hr cache.

---

## Identity Discounts (Continuously Scraped)

Identity discount data is scraped from verification platform directories and maintained in the `discount_programs` table. This runs on a separate schedule from price scraping.

### Scraping Sources

| Platform | URL Pattern | Groups Covered | Method |
|---|---|---|---|
| **ID.me** | `shop.id.me/military`, `/students`, `/first-responders` | Military, veterans, students, teachers, first responders, nurses, government | agent-browser batch scrape |
| **SheerID** | Press releases + partner directory | Students, military, teachers, first responders | agent-browser batch scrape |
| **WeSalute** | `wesalute.com` partner directory | Military, veterans | agent-browser batch scrape |
| **GovX** | `govx.com/brands/all` | Military, first responders, government | agent-browser batch scrape |
| **UNiDAYS** | `myunidays.com` brand directory | Students | agent-browser batch scrape |
| **StudentBeans** | `studentbeans.com` brand directory | Students | agent-browser batch scrape |

### High-Value Identity Redirect Opportunities

These are cases where Barkain redirects users from a retailer (e.g., Best Buy) to a brand's direct store for a better identity-discounted price:

| Brand | Best Identity Discount | Verification | Example Savings |
|---|---|---|---|
| **Samsung** | Up to 30% off (military, student, teacher, nurse, govt) | WeSalute / ID.me | $1,500 TV → $1,050 = **$450 saved** |
| **HP** | Up to 55% off (healthcare workers) | ID.me | Varies by SKU |
| **Apple** | 10% off (military, first responders) | ID.me | $999 MacBook → $899 = **$100 saved** |
| **LG** | Up to 40% off appliances (all identity groups) | ID.me | Major appliance savings |
| **Home Depot** | 10% off ($400 annual cap) — military | SheerID | $400/year cap |
| **Lowe's** | 10% off ($400 annual cap) — military, in-store only | ID.me | $400/year cap |

### Maintenance Schedule

| Job | Frequency | Method | Cost |
|---|---|---|---|
| Scrape ID.me/GovX/WeSalute directories | Weekly | agent-browser batch | ~$0 (self-hosted) |
| Verify specific discount program pages | Weekly | agent-browser + text match | ~$0 |
| Probe stale programs (no stable URL) | Weekly | agent-browser + AI | ~$0.02/run |
| Update seasonal programs (back-to-school, Veterans Day) | Monthly | Manual + scrape | $0 |

---

## Tool-to-Site Matrix

| Site/Source | Tool | Query Type | Pre-Fetch Filters | Cache TTL | Cost/Query |
|---|---|---|---|---|---|
| **Amazon** | Keepa API | Per-query (cached 6hr) | — | 6 hours | $0.01-0.02 |
| **Best Buy** | Best Buy Products API (free) | Per-query (cached 6hr) | — | 6 hours | Free |
| **Walmart** | agent-browser container | Per-query (cached 6hr) | — | 6 hours | ~$0.0075 (proxy) |
| **Target** | agent-browser container | Per-query (cached 6hr) | — | 6 hours | ~$0.0075 |
| **Home Depot** | agent-browser container | Per-query (cached 6hr) | — | 6 hours | ~$0.0075 |
| **Lowe's** | agent-browser container | Per-query (cached 6hr) | — | 6 hours | ~$0.0075 |
| **Costco** | agent-browser container (auth required) | Per-query (cached 6hr) | Membership flag | 6 hours | ~$0.0075 | **PRODUCTION ONLY — drop from demo** |
| **Newegg** | agent-browser container | Per-query (cached 6hr) | — | 6 hours | ~$0.0075 |
| **B&H Photo** | agent-browser container | Per-query (cached 6hr) | — | 6 hours | ~$0.0075 |
| **Kohl's** | agent-browser container | Per-query (cached 6hr) | — | 6 hours | ~$0.0075 |
| **Sam's Club** | agent-browser container | Per-query (cached 6hr) | Membership flag | 6 hours | ~$0.0075 |
| **BackMarket** | agent-browser container | Per-query (cached 6hr) | Certified refurb only | 6 hours | ~$0.0075 |
| **eBay (new)** | eBay Browse API (free) | Per-query (cached 30min) | Condition: new | 30 min | Free |
| **eBay (used/refurb)** | eBay Browse API (free) | Per-query (cached 30min) | Condition, price ±50%, seller >95% | 30 min | Free |
| **Facebook Marketplace** | agent-browser container | Per-query (gated, cached 30min) | Location, age <21d, price ±50% | 30 min | ~$0.0075 |
| **Keepa (history)** | Keepa API | Per-query (cached 6hr) | — | 6 hours | $0.01-0.02 |
| **Gemini UPC** | Gemini API | On-demand + PG cache | — | 24 hours (Redis) + persistent (PostgreSQL) | ~$0.002-0.005/lookup (YC credits). 4-6s latency, high accuracy. UPCitemdb as backup (free 100/day). |
| **Identity discounts** | agent-browser batch (ID.me, SheerID, GovX, etc.) | Weekly batch | — | 7 days | ~$0 |
| **Card rewards** | Quarterly manual + DB | Quarterly | — | 90 days | $0 |
| **Portal bonuses** | agent-browser batch | Every 6 hours | — | 6 hours | ~$0 |

---

## Tool Selection Logic

```
IS THERE A FREE/DIRECT API?
  ├─ YES → Use it (Best Buy API, eBay Browse API, Keepa — Phase 4 production)
  └─ NO
      │
      └─ agent-browser container
           - Each retailer gets its own Docker container
           - Chrome + agent-browser + extraction script + AI health agent
           - DOM eval pattern (fastest, highest quality)
           - Anti-detection: jitter, warm-up, headed Chrome, rotating user agents
           - Self-healing: Watchdog AI detects selector drift, rediscovers via Claude Opus
           │
           └─ STILL BLOCKED? (after retries + Watchdog heal attempts)
               │
               └─ Firecrawl (YC credits, absolute last resort)
```

### Cost Hierarchy

1. **DB cache hit** — $0.00 (majority of queries after initial scrape)
2. **Free APIs** (Best Buy, eBay Browse — Phase 4 production) — $0.00
3. **Keepa API** — $0.01-0.02/call
4. **agent-browser** (self-hosted) — ~$0.0075/search (proxy cost at scale)
5. **Claude API** — YC credits (recommendation synthesis)
6. **Firecrawl** — YC credits (last resort only)

---

## Pre-Fetch Filter Specifications

### Condition Filter (secondary market sources)

```python
ALLOWED_CONDITIONS = {
    "new": True,
    "like_new": True,
    "refurbished_certified": True,
    "refurbished_seller": True,
    "used_good": True,
    "used_acceptable": False,  # Exclude by default
    "for_parts": False,        # Always exclude
}
# User overrides via onboarding filter questions
```

### Price Range Filter

```python
def price_gate(listing_price, retail_baseline):
    """Gate check before spending scraping credits."""
    floor = retail_baseline * 0.15  # Below 15% = likely scam
    ceiling = retail_baseline * 1.50  # Above 150% = irrelevant
    return floor <= listing_price <= ceiling
```

### Secondary Market Filters

```python
MAX_LISTING_AGE_DAYS = {"ebay": 30, "facebook_marketplace": 21, "backmarket": None}
MIN_SELLER_SCORE = {"ebay": 95.0, "facebook_marketplace": None, "backmarket": 4.0}
```

---

## Caching Architecture

### TimescaleDB (persistent, cron-populated + per-query populated)

```
prices table:        product_id, retailer_id, price, url, condition, availability, scraped_at
price_history table: product_id, retailer_id, price, recorded_at (append-only, time-series)
discount_programs:   retailer_id, eligibility_type, discount_value, verification_platform, last_verified
portal_bonuses:      retailer_id, portal_name, bonus_rate, effective_until
card_rewards:        card_id, retailer_id, reward_rate, category, is_rotating, quarter
```

### Redis (live-query ephemeral cache)

```
secondary:{product_id}:{platform} → {listings array}     TTL: 30 min
recommendation:{product_id}:{user_id} → {rec + input_hash} TTL: until input changes
product:{upc} → {product_id, name, brand, category}      TTL: 30 days
```

### Cache Invalidation

- **6hr TTL expiry** on retail prices — next query re-scrapes
- **Price change >5%** on re-scrape → flag for recommendation re-synthesis
- **User profile change** → invalidate user's recommendation cache
- **Watchdog heal** → immediate re-scrape for affected retailer

---

## Progressive Loading UX Contract

**Step 2c update (2026-04-13):** The contract below is delivered via Server-Sent Events on `GET /api/v1/prices/{product_id}/stream`. Each retailer emits a `retailer_result` event the moment its data lands, terminated by a `done` event. The iOS `ScannerViewModel` consumes the stream and mutates `PriceComparison` in place so SwiftUI re-renders on each event. The batch endpoint `GET /api/v1/prices/{product_id}` remains as a fallback if the stream fails.

### Cache Hit Path (~80%+ of queries after ramp-up)

| Time | What the User Sees |
|---|---|
| 0ms | Scan animation |
| ~200ms | Product identified — name, image, category |
| **~250ms** | **All retail prices replayed from cache via SSE** (one rapid-fire event per retailer + `done.cached=true`) |
| 1-2s | Secondary market results (eBay live query) |

### Cache Miss Path — Demo Reality (Step 2c SSE streaming, 2026-04-13)

Post-streaming: the user sees retailers arrive at their natural completion time, cheapest-first as they land. Best Buy's 91s leg no longer blocks the iPhone.

| Time | What the User Sees |
|---|---|
| 0ms | Scan animation |
| 2-4s | Product identified (Gemini + UPCitemdb) |
| ~4s | Empty retailer list opens; spinner in place |
| **~16s** | **Walmart row fills** (~12s after dispatch — Firecrawl adapter leg) |
| **~34s** | **Amazon row fills** (~30s after dispatch — EC2 container) |
| **~95s** | **Best Buy row fills** (~91s after dispatch — dominant leg, but non-blocking for the other two) |
| ~95s | `done` event arrives, "Best Barkain" badge settles on the cheapest of the three |

Compare the pre-2c blocking contract: the user saw a spinner for ~90-120s with no feedback, then the entire list popped in at once. Streaming replaces the wall with a flowing list.

### Cache Miss Path — Aspirational (11 retailers, once 8 more come online)

| Time | What the User Sees |
|---|---|
| 0ms | Scan animation |
| ~200ms | Product identified from cache — name, image, category |
| ~200ms (miss) | Cache miss → Gemini API UPC lookup (4-6s) — loading spinner shown |
| ~300ms | **11 retailer rows rendered with spinners** via SSE stream open |
| ~300ms | **Onboarding filter questions appear** ("New or used?", "Preferred stores?") — buys scraping time |
| 3-5s | First container results stream in (fastest retailers: Sam's Club, Facebook Marketplace) — each as a `retailer_result` SSE event |
| 3-8s | Remaining container results populate progressively (Walmart, Amazon, Target, etc.) |
| ~5s | User finishes filter questions → results already populating |
| ~8s | All results in — sorted by price, savings badge shown — `done` event closes the stream |
| ~10s | AI recommendation banner appears (Phase 3 — updates as more data arrives) |

> **Production optimization (Phase 4):** Adding free APIs (Best Buy, eBay Browse) and Keepa brings the first 3 results down to ~500ms-1.5s, dramatically improving perceived speed while containers fill in the rest.

---

## Cost Model (Phase 1 — Beta, All Scraped)

### Assumptions
- 500 beta users, 50% DAU = 250 active
- 5 scans/day = 1,250 queries/day = ~37,500/month
- Cache hit rate: ~70% after ramp-up (many users search similar products)
- Cache miss queries: ~11,250/month → trigger live scraping

### Per-Query Costs

| Component | Cache Hit | Cache Miss | Monthly (37.5K queries, 70% hit rate) |
|---|---|---|---|
| DB read | $0.00 | $0.00 | $0 |
| agent-browser (11 containers × $0.0075) | — | ~$0.0825 | ~$928 (at scale with proxies) |
| Claude recommendation (Phase 3+) | ~$0.01-0.03 | ~$0.01-0.03 | ~$375-1,125 (YC credits) |
| **Per-query total** | **~$0.02** | **~$0.10-0.12** | |

### Monthly Estimate

| Category | Demo (no proxy) | Production (with proxy) |
|---|---|---|
| Keepa API | $0 (Phase 4) | ~$112 |
| Proxy costs | $0 (monitor block rates) | ~$126/mo (Decodo residential) |
| Railway/cloud compute (containers) | ~$50-100 | ~$50-100 |
| YC credits (Claude) | ~$375-1,125 | ~$375-1,125 |
| Gemini UPC lookup | ~$0.002-0.005 per miss (YC credits) | ~$0.002-0.005 per miss (YC credits) |
| **Total** | **~$425-1,225/mo** | **~$670-1,470/mo** |

Note: Demo runs 11 retailers, all scraped. No API costs until Phase 4 production optimization.

---

## Fallback Chain

```
agent-browser container fails → Retry (2-3 attempts with jitter + fresh Chrome profile)
                              → Watchdog AI diagnoses: bot block vs selector drift vs site down
                              → Selector drift: auto-heal via Claude Opus (YC credits)
                              → Bot block: rotate user agent, add proxy, retry
                              → If 3 heal attempts fail: skip retailer, escalate to Mike
                              → NEVER fall back to paid aggregator API

Production (Phase 4):
Best Buy container slow       → Best Buy Products API (free, ~500ms)
eBay container slow           → eBay Browse API (free, ~800ms)
Amazon container slow         → Keepa API (~1.5s)

Firecrawl (last resort)       → Only if agent-browser + Watchdog heal all fail
                              → YC credits, used sparingly

Claude API fails              → Return prices without AI recommendation
                              → Show raw "lowest price" sort
                              → GPT fallback via abstraction layer if down >5 min
```

---

## Scraper Maintenance

| Component | Maintenance Burden | Who Handles It |
|---|---|---|
| agent-browser scripts (11 retailers) | **Medium — auto-healed (Phase 2+)** | Watchdog AI via Claude Opus (90%+). Mike for structural redesigns. ~2-4 hr/month. Phase 1: manual monitoring. |
| Best Buy API (Phase 4) | Low (stable, versioned) | Best Buy — deprecation notice gives months of lead time |
| eBay Browse API (Phase 4) | Low (stable) | eBay — well-documented |
| Keepa API (Phase 4) | Low | Pricing changes only |
| Container infrastructure | Low | Docker + Railway managed |
| Watchdog AI (Phase 2+) | Low | Autonomous. Mike reviews alerts. |

---

## Proxy Options (Investigation)

For production scaling when single-IP scraping starts hitting blocks (especially Walmart/PerimeterX):

### Recommended: Decodo (formerly Smartproxy)

Best value for mid-size projects. No minimum commitment, lowest per-GB rate among quality providers.

| Attribute | Details |
|---|---|
| IP pool | 125M+ residential IPs, 195+ countries |
| Success rate | Up to 99.86% |
| Pricing | ~$1.50/GB residential (cheapest quality option) |
| Per-search cost | ~$0.0075 at 500KB-1MB per search page |
| Sticky sessions | Supported (needed for multi-step flows) |
| Integration | Chrome launch flag: `--proxy-server="http://gate.decodo.com:7777"` or agent-browser `--proxy` flag |

### Alternatives

| Provider | Per GB | Best For | Notes |
|---|---|---|---|
| **Decodo/Smartproxy** | ~$1.50/GB | Best value, mid-scale | Recommended starting point |
| **IPRoyal** | ~$7.00/GB | Non-expiring traffic, irregular schedules | Pay once, use anytime |
| **Bright Data** | ~$8.40/GB (10GB), drops to ~$3.30/GB at 10TB | Enterprise scale, ZIP-code targeting | Premium but most features |
| **Oxylabs** | ~$10/GB | Raw speed, enterprise | $300 minimum, expensive for beta |

### When to Add Proxies

| Signal | Action |
|---|---|
| Single session, <500 req/day per site | No proxy needed (demo) |
| Walmart blocks increasing | Add residential proxy for Walmart container only |
| Multiple parallel sessions, cloud server | Residential proxy for all containers |
| Logged-in sessions (Costco production) | Sticky residential proxy required |

### Cost at Beta Scale

At 11,250 cache-miss queries/month × 10 retailers × ~750KB avg = ~84GB/month:
- **Decodo:** ~$126/month
- **Bright Data:** ~$706/month
- **No proxy (demo):** $0 — test threshold first, add only when needed

**Recommendation:** Start without proxies for demo. Monitor block rates. Add Decodo for Walmart first (most aggressive anti-bot), expand to other retailers as needed.

---

## Resolved Questions

| # | Question | Resolution |
|---|---|---|
| 1 | Sam's Club auth | **No issues.** Works without login — no auth required. |
| 2 | Costco member pricing | **Server-side gated.** Get working in production with auth session. **Drop from demo.** |
| 3 | Facebook Marketplace reliability | **More permissive than Costco.** Faster response, no pricing gates. Modal-hide technique (`display:none`) completely reliable at this volume. |
| 4 | UPC resolution source | **Gemini API (primary) + UPCitemdb (backup).** OpenAI charges $10/1K calls — unacceptable. Gemini is cost-effective. UPCitemdb free tier (100/day) kept as fallback. |
| 5 | BackMarket API | **Scraper (agent-browser) for demo.** Pursue full API access for production. |
| 6 | Container cold start | **Accept first-query latency.** Onboarding filter questions buffer the 4-5s Chrome launch. No need to pre-warm. |
| 7 | Home Depot, Lowe's, Newegg, B&H, Kohl's | **Assume they work.** Mike to confirm with agent-browser testing. Expect similar patterns to Walmart/Target/Amazon (data attributes or URL patterns as anchor selectors). |
| 8 | Coupons | **Deprioritized this phase.** Focus on price comparison + identity discounts + card rewards. |
| 9 | Paid aggregator APIs | **None.** No ShopSavvy, no Zinc. Free APIs > agent-browser > Firecrawl. |

## Remaining Open Questions

1. **Walmart proxy timing** — At what daily volume does PerimeterX start blocking from cloud IPs? Test early; may need Decodo proxy from day 1 for Walmart container.
2. **BackMarket API access** — Contact partnerships@backmarket.com. If API available, switch from scraper in production.
3. **Costco production auth** — Design credential management for authenticated Costco sessions. Sticky proxy required.
4. **Keepa batch efficiency** — Confirm multi-ASIN request support and optimal batch sizes.
5. **Untested retailers** — Home Depot, Lowe's, Newegg, B&H, Kohl's need agent-browser battery tests. Mike to confirm.
