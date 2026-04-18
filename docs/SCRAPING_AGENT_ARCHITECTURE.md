# Barkain — Scraping & Agentic Discount Architecture

> Source: Architecture session, March 2026
> Scope: Deterministic scraper pipeline, self-healing supervisor agent, probe template library, discount catalog schema, coupon validation agents
> Last updated: April 2026 (v2 — renamed to Barkain, Playwright replaced by agent-browser, Browser Use dropped, Opus for Watchdog)

---

## Design Philosophy

The system splits into two fundamentally different workloads:

1. **Deterministic extraction** — agent-browser replays known scripts against known retailers via DOM eval. Zero LLM cost. Runs on schedule. This is the price comparison engine.
2. **Agentic probing** — LLM-driven browser agents fire on-demand to discover, verify, and test discounts that are dynamic, user-specific, or require interactive validation. This is where AI earns its cost.

A **supervisor agent** monitors the health of all deterministic scripts and triggers self-healing when extraction fails — the only always-on AI component.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         SCHEDULED LAYER                             │
│                    (Deterministic, Zero LLM Cost)                    │
│                                                                     │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐     │
│  │ Best Buy │    │  Amazon  │    │   eBay   │    │ [Future] │     │
│  │  Script  │    │  Script  │    │  Script  │    │  Script  │     │
│  └────┬─────┘    └────┬─────┘    └────┬─────┘    └────┬─────┘     │
│       │               │               │               │            │
│       └───────────────┴───────────────┴───────────────┘            │
│                           │                                         │
│                    ┌──────▼──────┐                                  │
│                    │ TimescaleDB │  ← prices, price_history         │
│                    └──────┬──────┘                                  │
│                           │                                         │
│              ┌────────────▼────────────┐                           │
│              │   Supervisor Agent (AI) │  ← monitors script health  │
│              │   "The Watchdog"        │    triggers self-healing    │
│              └─────────────────────────┘                           │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                         ON-DEMAND LAYER                             │
│                   (Agentic, Per-Query LLM Cost)                     │
│                                                                     │
│  User Query + Identity Profile                                      │
│       │                                                             │
│       ├──→ [1] Discount Catalog Lookup (DB, $0)                    │
│       ├──→ [2] Discount Probe Agents (agent-browser, ~$0.005/probe)  │
│       ├──→ [3] Card Reward Match (DB from nightly batch, $0)       │
│       ├──→ [4] Coupon Validation Agents (agent-browser, ~$0.01)      │
│       ├──→ [5] Portal Bonus Match (DB from nightly batch, $0)      │
│       │                                                             │
│       └──→ [6] Claude Synthesis → Final Recommendation             │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Part 1: Deterministic Scraper Pipeline

### Per-Retailer Script Registry

Each retailer gets a self-contained script package stored in the database and on disk:

```
scripts/
├── retailers/
│   ├── best_buy/
│   │   ├── config.json          # Retailer metadata, URLs, selectors
│   │   ├── search.py            # Product search by UPC/name
│   │   ├── price_extract.py     # Price + availability extraction
│   │   ├── category_map.json    # Retailer categories → internal categories
│   │   └── test_fixtures.json   # Known products with expected outputs
│   ├── ebay/
│   │   ├── config.json
│   │   ├── browse_api.py        # eBay Browse API client (official)
│   │   ├── listing_extract.py   # Secondary market listing parser
│   │   └── test_fixtures.json
│   └── amazon/
│       ├── config.json
│       ├── keepa_client.py      # Keepa API client
│       └── test_fixtures.json
```

### config.json Schema (Per Retailer)

```json
{
  "retailer_id": "best_buy",
  "display_name": "Best Buy",
  "base_url": "https://www.bestbuy.com",
  "script_version": "1.4.2",
  "last_generated": "2026-03-28T14:30:00Z",
  "last_validated": "2026-03-30T06:00:00Z",
  "generation_method": "agent_browser_discovery",
  "extraction_type": "agent_browser_script",

  "selectors": {
    "product_name": "h1.sku-title",
    "current_price": ".priceView-hero-price span[aria-hidden='true']",
    "original_price": ".pricing-price__regular-price",
    "availability": ".fulfillment-add-to-cart-button",
    "sku": ".sku-value",
    "upc": "meta[itemprop='gtin13']"
  },

  "search_url_template": "https://www.bestbuy.com/site/searchpage.jsp?st={query}",
  "search_result_selector": ".sku-item",
  "search_result_fields": {
    "name": ".sku-title a",
    "price": ".priceView-hero-price span",
    "url": ".sku-title a@href",
    "image": ".product-image img@src"
  },

  "rate_limit": {
    "requests_per_minute": 10,
    "concurrent": 2,
    "backoff_seconds": [5, 15, 60]
  },

  "health": {
    "consecutive_failures": 0,
    "max_failures_before_alert": 3,
    "last_success": "2026-03-30T06:00:00Z",
    "last_failure": null,
    "status": "healthy"
  }
}
```

### Scheduled Extraction Flow

```python
# Simplified pipeline - runs every 6 hours per retailer
async def run_retailer_extraction(retailer_id: str):
    config = load_retailer_config(retailer_id)
    watched_products = get_watched_products_for_retailer(retailer_id)

    for product in watched_products:
        try:
            # Each container exposes POST /extract
            price_data = await call_container_extract(
                retailer_id=retailer_id,
                product_url=product.retailer_url,
                selectors=config["selectors"]
            )

            # Write to prices table (current) + price_history (append)
            await upsert_price(retailer_id, product.id, price_data)
            await append_price_history(retailer_id, product.id, price_data)

            # Reset failure counter on success
            await mark_script_healthy(retailer_id)

        except ExtractionError as e:
            await record_extraction_failure(retailer_id, product.id, e)

            # After N consecutive failures, alert supervisor
            if await check_failure_threshold(retailer_id):
                await notify_supervisor_agent(
                    retailer_id=retailer_id,
                    error_type=e.error_type,
                    sample_url=product.retailer_url,
                    last_known_selectors=config["selectors"]
                )
```

---

## Part 2: Self-Healing Supervisor Agent ("The Watchdog")

### Design Principles

1. **The Watchdog is NOT in the hot path.** It never runs during a user query. It monitors and repairs.
2. **It runs on a schedule + on-alert.** Nightly health check of all scripts, plus immediate response when a retailer hits failure threshold.
3. **It uses agent-browser + Claude Opus (YC credits)** to rediscover selectors.
4. **It never deploys blindly.** New selectors go through validation against test fixtures before replacing live config.
5. **It escalates to human (you) when it can't self-heal after N attempts.**

### Watchdog Architecture

```
┌─────────────────────────────────────────────────────┐
│                  SUPERVISOR AGENT                     │
│              ("The Watchdog")                         │
│                                                       │
│  Triggers:                                           │
│  ├── Nightly health check (cron, 2 AM)               │
│  ├── Failure threshold alert (from extraction worker) │
│  └── Manual trigger (developer command)              │
│                                                       │
│  Actions:                                            │
│  ├── [1] Diagnose: What broke?                       │
│  │       - Selector returns null/empty                │
│  │       - Page structure changed                     │
│  │       - Anti-bot block (403/captcha)               │
│  │       - Network/timeout issue                      │
│  │                                                    │
│  ├── [2] Classify severity:                          │
│  │       - TRANSIENT: retry with backoff             │
│  │       - SELECTOR_DRIFT: rediscover selectors      │
│  │       - LAYOUT_REDESIGN: full page re-analysis    │
│  │       - BLOCKED: rotate UA/proxy, escalate        │
│  │                                                    │
│  ├── [3] Self-heal (for SELECTOR_DRIFT):             │
│  │       - Launch agent-browser with LLM               │
│  │       - Navigate to known product page             │
│  │       - Ask: "Find the CSS selector for price"    │
│  │       - Validate against 3+ test fixture products │
│  │       - If all pass → update config.json          │
│  │       - If any fail → escalate                    │
│  │                                                    │
│  └── [4] Escalate:                                   │
│          - Push notification to developer             │
│          - Log full diagnostic to watchdog_events     │
│          - Disable retailer extraction (graceful)     │
│          - Mark retailer as "degraded" in API         │
│                                                       │
└─────────────────────────────────────────────────────┘
```

### Watchdog Database Schema

```sql
-- Tracks every watchdog intervention
CREATE TABLE watchdog_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    retailer_id     TEXT NOT NULL REFERENCES retailers(id),
    event_type      TEXT NOT NULL,  -- 'health_check', 'failure_alert', 'manual'
    diagnosis       TEXT NOT NULL,  -- 'transient', 'selector_drift', 'layout_redesign', 'blocked'
    action_taken    TEXT NOT NULL,  -- 'retry', 'rediscover', 'escalate', 'disable'
    success         BOOLEAN NOT NULL,
    old_selectors   JSONB,          -- snapshot before change
    new_selectors   JSONB,          -- snapshot after change (if changed)
    llm_model       TEXT,           -- which model was used
    llm_tokens_used INTEGER,        -- cost tracking
    error_details   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for dashboard queries
CREATE INDEX idx_watchdog_retailer_time
    ON watchdog_events (retailer_id, created_at DESC);

-- Retailer health status (denormalized for fast reads)
CREATE TABLE retailer_health (
    retailer_id             TEXT PRIMARY KEY REFERENCES retailers(id),
    status                  TEXT NOT NULL DEFAULT 'healthy',
        -- 'healthy', 'degraded', 'healing', 'disabled'
    consecutive_failures    INTEGER NOT NULL DEFAULT 0,
    last_successful_extract TIMESTAMPTZ,
    last_failed_extract     TIMESTAMPTZ,
    last_healed_at          TIMESTAMPTZ,
    heal_attempts           INTEGER NOT NULL DEFAULT 0,
    max_heal_attempts       INTEGER NOT NULL DEFAULT 3,
    script_version          TEXT NOT NULL,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Self-Healing Flow (Selector Rediscovery)

```python
async def heal_retailer(retailer_id: str, failure_context: dict):
    """
    Uses agent-browser + Claude Opus (YC credits) to rediscover broken selectors.
    Only called when diagnosis = SELECTOR_DRIFT.
    """
    config = load_retailer_config(retailer_id)
    test_fixtures = load_test_fixtures(retailer_id)

    # Step 1: Use agent-browser to capture current page DOM structure
    page_html = await run_agent_browser_eval(
        url=test_fixtures[0]["url"],
        js_code="document.documentElement.outerHTML"
    )

    # Step 2: Ask Claude Opus to analyze DOM and find new selectors
    prompt = f"""
    This is a {config['display_name']} product page.
    The following CSS selectors are broken and returning empty:
    {json.dumps(failure_context['broken_selectors'])}

    Given the current page HTML below, find the NEW correct CSS selectors
    that extract the same data. Return as JSON:
    {{
        "product_name": "new.selector.here",
        "current_price": "new.selector.here",
        ...
    }}

    Only return selectors you have verified exist in the DOM.

    Page HTML (truncated):
    {page_html[:50000]}
    """

    result = await ai_abstraction.call(
        task="watchdog_heal",
        prompt=prompt,
        model="claude_opus"
    )
    candidate_selectors = parse_selector_response(result)

    # Step 3: Validate candidates against ALL test fixtures via agent-browser
    validation_results = []
    for fixture in test_fixtures:
        for field, selector in candidate_selectors.items():
            try:
                extracted = await run_agent_browser_eval(
                    url=fixture["url"],
                    js_code=f"document.querySelector('{selector}')?.innerText || null"
                )
                expected = fixture["expected"].get(field)

                validation_results.append({
                    "fixture": fixture["url"],
                    "field": field,
                    "selector": selector,
                    "extracted": extracted,
                    "expected_pattern": expected,
                    "passed": validate_extraction(extracted, expected, field)
                })
            except Exception as e:
                validation_results.append({
                    "fixture": fixture["url"],
                    "field": field,
                    "selector": selector,
                    "error": str(e),
                    "passed": False
                })

    # Step 3: Decide — deploy or escalate
    pass_rate = sum(1 for v in validation_results if v["passed"]) / len(validation_results)

    if pass_rate >= 0.9:  # 90%+ validation pass rate
        # Deploy new selectors
        old_selectors = config["selectors"].copy()
        config["selectors"].update(candidate_selectors)
        config["script_version"] = bump_patch_version(config["script_version"])
        config["last_generated"] = datetime.utcnow().isoformat()
        save_retailer_config(retailer_id, config)

        await log_watchdog_event(
            retailer_id=retailer_id,
            diagnosis="selector_drift",
            action_taken="rediscover",
            success=True,
            old_selectors=old_selectors,
            new_selectors=candidate_selectors
        )
        await set_retailer_status(retailer_id, "healthy")
    else:
        # Escalate — selectors couldn't be validated
        await log_watchdog_event(
            retailer_id=retailer_id,
            diagnosis="selector_drift",
            action_taken="escalate",
            success=False,
            error_details=f"Validation pass rate: {pass_rate:.0%}"
        )
        await increment_heal_attempts(retailer_id)

        if await should_disable_retailer(retailer_id):
            await set_retailer_status(retailer_id, "disabled")
            await send_developer_alert(
                f"[WATCHDOG] {config['display_name']} disabled after "
                f"{config['health']['max_heal_attempts']} failed heal attempts. "
                f"Manual intervention required."
            )
```

### Test Fixtures Schema (Per Retailer)

```json
{
  "retailer_id": "best_buy",
  "fixtures": [
    {
      "url": "https://www.bestbuy.com/site/sony-65-class-bravia-xr/6578594.p",
      "product_id": "6578594",
      "expected": {
        "product_name": {"contains": "Sony", "contains": "65"},
        "current_price": {"pattern": "^\\$[\\d,]+\\.\\d{2}$"},
        "availability": {"one_of": ["Add to Cart", "Sold Out", "Coming Soon"]},
        "sku": {"pattern": "^\\d{7}$"}
      }
    },
    {
      "url": "https://www.bestbuy.com/site/apple-airpods-pro/6447382.p",
      "product_id": "6447382",
      "expected": {
        "product_name": {"contains": "AirPods"},
        "current_price": {"pattern": "^\\$[\\d,]+\\.\\d{2}$", "range": [100, 400]}
      }
    }
  ]
}
```

---

## Part 3: Discount Catalog Database

### Core Principle

Every retailer has a finite, known set of discount programs. These change slowly (monthly at most). We catalog them once, keep them updated via the Watchdog's nightly batch, and match them to user profiles at query time with zero LLM cost.

### Schema

```sql
-- Master retailer table
CREATE TABLE retailers (
    id              TEXT PRIMARY KEY,          -- 'best_buy', 'amazon', 'ebay'
    display_name    TEXT NOT NULL,
    base_url        TEXT NOT NULL,
    logo_url        TEXT,
    supports_coupons    BOOLEAN DEFAULT false,
    supports_identity   BOOLEAN DEFAULT false,
    supports_portals    BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ================================================================
-- DISCOUNT PROGRAMS: What discounts each retailer offers
-- ================================================================
CREATE TABLE discount_programs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    retailer_id         TEXT NOT NULL REFERENCES retailers(id),
    program_name        TEXT NOT NULL,           -- 'Military Discount', 'Student Deals'
    program_type        TEXT NOT NULL,
        -- 'identity'     = requires user attribute (military, student, etc.)
        -- 'membership'   = requires paid membership (Costco, Prime, etc.)
        -- 'portal'       = cashback portal (Rakuten, card shopping portals)
        -- 'card_offer'   = card-linked offer (Amex Offers, Chase Offers)
        -- 'category'     = rotating card bonus category
        -- 'coupon'       = promo code
        -- 'loyalty'      = retailer loyalty program (My Best Buy, etc.)
        -- 'bundle'       = multi-item bundle discount
        -- 'trade_in'     = trade-in credit program

    -- Eligibility: what user attribute qualifies them
    eligibility_type    TEXT,
        -- 'military', 'veteran', 'student', 'teacher', 'first_responder',
        -- 'senior', 'aaa', 'aarp', 'employee_[company]', 'alumni_[school]',
        -- 'union_[name]', 'costco_member', 'prime_member',
        -- 'card_[network]_[product]'  (e.g., 'card_chase_sapphire_preferred')

    -- Discount structure
    discount_type       TEXT NOT NULL,
        -- 'percentage', 'fixed_amount', 'cashback_percentage',
        -- 'points_multiplier', 'free_shipping', 'bogo', 'tiered'
    discount_value      NUMERIC,                 -- 10 = 10% or $10 depending on type
    discount_max_value  NUMERIC,                 -- cap (e.g., "up to $500 off")
    discount_details    TEXT,                     -- human-readable description

    -- Applicability
    applies_to_categories   TEXT[],              -- internal category IDs, NULL = all
    excluded_categories     TEXT[],              -- categories this does NOT apply to
    excluded_brands         TEXT[],              -- brands excluded
    minimum_purchase        NUMERIC,             -- minimum order value
    stackable               BOOLEAN DEFAULT false,-- can combine with other discounts?
    stacks_with             TEXT[],              -- program_types it stacks with

    -- Verification
    verification_method TEXT,
        -- 'id_me', 'sheer_id', 'manual_upload', 'email_domain',
        -- 'self_attestation', 'card_linked', 'membership_number', 'none'
    verification_url    TEXT,                    -- direct link to verification page

    -- Metadata
    url                 TEXT,                    -- program info page
    is_active           BOOLEAN DEFAULT true,
    last_verified       TIMESTAMPTZ,            -- when watchdog last confirmed active
    last_verified_by    TEXT,                   -- 'watchdog_batch', 'manual', 'probe_agent'
    effective_from      DATE,
    effective_until     DATE,                    -- NULL = ongoing
    notes               TEXT,

    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (retailer_id, program_name, eligibility_type)
);

-- Index for the hot query path: "what discounts apply to this user at this retailer?"
CREATE INDEX idx_discount_programs_lookup
    ON discount_programs (retailer_id, program_type, is_active)
    WHERE is_active = true;

CREATE INDEX idx_discount_programs_eligibility
    ON discount_programs (eligibility_type, is_active)
    WHERE is_active = true;

-- ================================================================
-- CARD REWARD RATES: Per-card, per-category bonus structures
-- ================================================================
CREATE TABLE card_reward_programs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    card_network        TEXT NOT NULL,            -- 'visa', 'mastercard', 'amex'
    card_issuer         TEXT NOT NULL,            -- 'chase', 'amex', 'citi', 'capital_one'
    card_product        TEXT NOT NULL,            -- 'sapphire_preferred', 'gold_card'
    card_display_name   TEXT NOT NULL,            -- 'Chase Sapphire Preferred'

    -- Base earn rate
    base_reward_rate    NUMERIC NOT NULL,         -- 1.0 = 1x points / 1% cashback
    reward_currency     TEXT NOT NULL,            -- 'ultimate_rewards', 'membership_rewards', 'cashback'
    point_value_cents   NUMERIC,                 -- estimated cpp (1.25 for CSP, 2.0 for CSR, etc.)

    -- Category bonuses (the static, non-rotating ones)
    category_bonuses    JSONB NOT NULL DEFAULT '[]',
    -- Example: [
    --   {"category": "dining", "rate": 3.0, "description": "3x on dining"},
    --   {"category": "travel", "rate": 5.0, "description": "5x on travel via portal"},
    --   {"category": "groceries", "rate": 4.0, "cap_annual": 25000, "description": "4x groceries up to $25K/yr"}
    -- ]

    -- Shopping portal
    has_shopping_portal     BOOLEAN DEFAULT false,
    portal_url              TEXT,
    portal_base_rate        NUMERIC,             -- base portal earn rate (often 1x extra)

    is_active               BOOLEAN DEFAULT true,
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

-- ================================================================
-- ROTATING CATEGORIES: Time-bound bonus categories that change quarterly/monthly
-- ================================================================
CREATE TABLE rotating_categories (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    card_program_id     UUID NOT NULL REFERENCES card_reward_programs(id),
    quarter             TEXT NOT NULL,            -- '2026-Q2', '2026-03' for monthly
    categories          TEXT[] NOT NULL,          -- ['groceries', 'gas_stations', 'amazon']
    bonus_rate          NUMERIC NOT NULL,         -- 5.0 = 5x/5%
    activation_required BOOLEAN DEFAULT true,
    activation_url      TEXT,
    cap_amount          NUMERIC,                 -- quarterly spend cap
    effective_from      DATE NOT NULL,
    effective_until     DATE NOT NULL,
    last_verified       TIMESTAMPTZ,

    UNIQUE (card_program_id, quarter)
);

-- ================================================================
-- PORTAL BONUSES: Time-bound elevated cashback on shopping portals
-- ================================================================
CREATE TABLE portal_bonuses (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portal_source       TEXT NOT NULL,
        -- 'rakuten', 'topcashback', 'chase_shop_through_chase',
        -- 'amex_shop_small', 'citi_bonus_cash', 'capital_one_shopping'
    retailer_id         TEXT NOT NULL REFERENCES retailers(id),
    bonus_type          TEXT NOT NULL,            -- 'cashback_percentage', 'points_multiplier'
    bonus_value         NUMERIC NOT NULL,         -- e.g., 8.0 = 8% cashback
    normal_value        NUMERIC,                 -- what it usually is (for spike detection)
    is_elevated         BOOLEAN GENERATED ALWAYS AS (
        bonus_value > COALESCE(normal_value, 0) * 1.5
    ) STORED,                                    -- auto-flag spikes
    effective_from      TIMESTAMPTZ NOT NULL,
    effective_until     TIMESTAMPTZ,
    last_verified       TIMESTAMPTZ,
    verified_by         TEXT,                    -- 'nightly_batch', 'probe_agent'

    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Hot path: "what portal bonuses are active for this retailer right now?"
CREATE INDEX idx_portal_bonuses_active
    ON portal_bonuses (retailer_id, effective_until)
    WHERE effective_until IS NULL OR effective_until > NOW();

-- ================================================================
-- COUPON CACHE: Known promo codes with validation status
-- ================================================================
CREATE TABLE coupon_cache (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    retailer_id         TEXT NOT NULL REFERENCES retailers(id),
    code                TEXT NOT NULL,
    description         TEXT,
    discount_type       TEXT NOT NULL,            -- 'percentage', 'fixed', 'free_shipping'
    discount_value      NUMERIC,
    minimum_purchase    NUMERIC,
    applies_to          TEXT[],                   -- category restrictions
    source              TEXT NOT NULL,            -- 'crawl_retailmenot', 'crawl_honey', 'user_submitted'

    -- Validation
    validation_status   TEXT NOT NULL DEFAULT 'unvalidated',
        -- 'unvalidated', 'valid', 'invalid', 'expired', 'conditional'
    last_validated      TIMESTAMPTZ,
    validated_by        TEXT,                     -- 'coupon_agent', 'user_report'
    validation_notes    TEXT,                     -- e.g., "works only with $50+ cart"
    success_count       INTEGER DEFAULT 0,
    failure_count       INTEGER DEFAULT 0,
    confidence_score    NUMERIC GENERATED ALWAYS AS (
        CASE WHEN (success_count + failure_count) = 0 THEN 0.5
        ELSE success_count::numeric / (success_count + failure_count)
        END
    ) STORED,

    -- Lifecycle
    discovered_at       TIMESTAMPTZ DEFAULT NOW(),
    expires_at          TIMESTAMPTZ,
    is_active           BOOLEAN DEFAULT true,

    UNIQUE (retailer_id, code)
);

-- ================================================================
-- USER IDENTITY PROFILES: What discounts each user qualifies for
-- ================================================================
-- (Lives alongside your existing user table from Clerk)
CREATE TABLE user_discount_profiles (
    user_id             TEXT PRIMARY KEY,         -- Clerk user ID
    -- Identity attributes (boolean flags — simple and fast to query)
    is_military         BOOLEAN DEFAULT false,
    is_veteran          BOOLEAN DEFAULT false,
    is_student          BOOLEAN DEFAULT false,
    is_teacher          BOOLEAN DEFAULT false,
    is_first_responder  BOOLEAN DEFAULT false,
    is_senior           BOOLEAN DEFAULT false,
    is_aaa_member       BOOLEAN DEFAULT false,
    is_aarp_member      BOOLEAN DEFAULT false,
    email_domain        TEXT,                     -- for .edu detection
    employer            TEXT,                     -- for employer partnership matching
    alumni_school       TEXT,
    union_membership    TEXT,

    -- Memberships
    is_costco_member    BOOLEAN DEFAULT false,
    is_prime_member     BOOLEAN DEFAULT false,
    is_sams_member      BOOLEAN DEFAULT false,

    -- Verification status
    id_me_verified      BOOLEAN DEFAULT false,
    sheer_id_verified   BOOLEAN DEFAULT false,

    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- User's card portfolio
CREATE TABLE user_cards (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             TEXT NOT NULL,
    card_program_id     UUID NOT NULL REFERENCES card_reward_programs(id),
    nickname            TEXT,                     -- user-friendly label
    is_active           BOOLEAN DEFAULT true,
    added_at            TIMESTAMPTZ DEFAULT NOW()
);
```

### Query-Time Discount Matching (Zero LLM Cost)

```python
async def find_applicable_discounts(
    user_id: str,
    retailer_id: str,
    product_category: str,
    cart_total: float
) -> list[DiscountMatch]:
    """
    Pure database query. No LLM calls.
    Returns all discounts this user qualifies for at this retailer.
    """
    user_profile = await get_user_discount_profile(user_id)
    user_cards = await get_user_cards(user_id)

    # Build eligibility list from user profile
    eligibility_types = []
    if user_profile.is_military: eligibility_types.append("military")
    if user_profile.is_veteran: eligibility_types.append("veteran")
    if user_profile.is_student: eligibility_types.append("student")
    # ... etc

    # Query 1: Identity-based discounts
    identity_discounts = await db.fetch_all("""
        SELECT * FROM discount_programs
        WHERE retailer_id = $1
          AND is_active = true
          AND eligibility_type = ANY($2)
          AND (applies_to_categories IS NULL
               OR $3 = ANY(applies_to_categories))
          AND (excluded_categories IS NULL
               OR NOT ($3 = ANY(excluded_categories)))
          AND (minimum_purchase IS NULL
               OR minimum_purchase <= $4)
    """, retailer_id, eligibility_types, product_category, cart_total)

    # Query 2: Best card for this purchase
    card_matches = await find_best_card(
        user_cards, retailer_id, product_category
    )

    # Query 3: Active portal bonuses
    portal_bonuses = await db.fetch_all("""
        SELECT * FROM portal_bonuses
        WHERE retailer_id = $1
          AND (effective_until IS NULL OR effective_until > NOW())
        ORDER BY bonus_value DESC
    """, retailer_id)

    # Query 4: Valid coupons
    valid_coupons = await db.fetch_all("""
        SELECT * FROM coupon_cache
        WHERE retailer_id = $1
          AND is_active = true
          AND validation_status IN ('valid', 'unvalidated')
          AND (expires_at IS NULL OR expires_at > NOW())
          AND confidence_score >= 0.5
        ORDER BY discount_value DESC
        LIMIT 5
    """, retailer_id)

    return compile_discount_stack(
        identity_discounts, card_matches, portal_bonuses, valid_coupons
    )
```

---

## Part 4: Probe Template Library

### When Probes Fire

Probes are **on-demand, user-triggered** browser agent tasks. They fire only when:

1. A discount program exists in the catalog but has `last_verified` older than threshold
2. A discount is marked `conditional` and needs live verification for this specific product
3. No cached coupon validation exists for a retailer in the user's cart
4. A new discount type is detected during nightly batch that needs confirmation

### Probe Template Structure

```python
from dataclasses import dataclass
from enum import Enum

class ProbeType(Enum):
    IDENTITY_DISCOUNT_CHECK = "identity_discount_check"
    COUPON_VALIDATION = "coupon_validation"
    PORTAL_RATE_CHECK = "portal_rate_check"
    CARD_OFFER_CHECK = "card_offer_check"
    PRICE_MATCH_POLICY = "price_match_policy"

@dataclass
class ProbeTemplate:
    probe_type: ProbeType
    retailer_id: str
    task_template: str           # Prompt template with {placeholders}
    navigation_hints: list[str]  # Known URL patterns to try first
    expected_output_schema: dict # JSON schema for structured response
    max_steps: int = 10          # agent-browser step limit (cost control)
    timeout_seconds: int = 30
    llm_model: str = "qwen-flash"  # Cheap, good at structured output
    fallback_model: str = "claude-sonnet"  # Quality fallback (YC credits)

    # Cost controls
    max_input_tokens: int = 2000
    max_output_tokens: int = 500
```

### Probe Templates (Examples)

```python
PROBE_TEMPLATES = {
    # ─── Identity Discount Verification ────────────────────────
    "best_buy_military": ProbeTemplate(
        probe_type=ProbeType.IDENTITY_DISCOUNT_CHECK,
        retailer_id="best_buy",
        task_template="""
        Navigate to {verification_url}.
        Determine if Best Buy's military/veteran discount applies to
        the product category "{product_category}".
        Return JSON:
        {{
            "discount_available": true/false,
            "discount_percentage": <number or null>,
            "excluded_brands": [<list>],
            "verification_required": "id_me" | "sheer_id" | "none",
            "notes": "<any conditions or restrictions>"
        }}
        """,
        navigation_hints=[
            "https://www.bestbuy.com/site/misc/military-discount/pcmcat311300050015.c",
            "https://www.bestbuy.com/site/help-topics/military-discount/pcmcat311300050015.c"
        ],
        expected_output_schema={
            "type": "object",
            "required": ["discount_available"],
            "properties": {
                "discount_available": {"type": "boolean"},
                "discount_percentage": {"type": ["number", "null"]},
                "excluded_brands": {"type": "array", "items": {"type": "string"}},
                "verification_required": {"type": "string"},
                "notes": {"type": "string"}
            }
        },
        max_steps=6
    ),

    # ─── Coupon Validation ─────────────────────────────────────
    "generic_coupon_test": ProbeTemplate(
        probe_type=ProbeType.COUPON_VALIDATION,
        retailer_id="*",  # works for any retailer
        task_template="""
        Go to {retailer_url}.
        Add the product at {product_url} to cart.
        Navigate to cart/checkout.
        Apply promo code: {coupon_code}
        Report the result as JSON:
        {{
            "code": "{coupon_code}",
            "accepted": true/false,
            "discount_applied": <dollar amount or null>,
            "error_message": "<text shown if rejected, or null>",
            "requires_minimum": <minimum purchase amount or null>
        }}
        Do NOT complete any purchase. Stop after seeing the discount result.
        """,
        navigation_hints=[],
        expected_output_schema={
            "type": "object",
            "required": ["code", "accepted"],
            "properties": {
                "code": {"type": "string"},
                "accepted": {"type": "boolean"},
                "discount_applied": {"type": ["number", "null"]},
                "error_message": {"type": ["string", "null"]},
                "requires_minimum": {"type": ["number", "null"]}
            }
        },
        max_steps=12,  # More steps needed for cart interaction
        timeout_seconds=45
    ),

    # ─── Portal Rate Check ─────────────────────────────────────
    "rakuten_rate_check": ProbeTemplate(
        probe_type=ProbeType.PORTAL_RATE_CHECK,
        retailer_id="*",
        task_template="""
        Navigate to https://www.rakuten.com/search?query={retailer_name}
        Find the current cashback rate for {retailer_name}.
        Return JSON:
        {{
            "retailer": "{retailer_name}",
            "portal": "rakuten",
            "cashback_rate": <percentage as number>,
            "is_elevated": true/false,
            "normal_rate": <if visible, otherwise null>,
            "special_terms": "<any conditions>"
        }}
        """,
        navigation_hints=[
            "https://www.rakuten.com/{retailer_slug}"
        ],
        expected_output_schema={
            "type": "object",
            "required": ["retailer", "cashback_rate"],
            "properties": {
                "cashback_rate": {"type": "number"},
                "is_elevated": {"type": "boolean"}
            }
        },
        max_steps=5
    ),

    # ─── Card-Linked Offer Check ───────────────────────────────
    "chase_offers_check": ProbeTemplate(
        probe_type=ProbeType.CARD_OFFER_CHECK,
        retailer_id="*",
        task_template="""
        Navigate to the Chase Offers page.
        Search for any active offer related to "{retailer_name}".
        Return JSON:
        {{
            "retailer": "{retailer_name}",
            "offer_found": true/false,
            "offer_type": "cashback" | "points" | null,
            "offer_value": "<description, e.g., '5% back up to $25'>",
            "activation_required": true/false,
            "expires": "<date or null>"
        }}
        NOTE: This requires authentication. If not logged in, return
        {{"retailer": "{retailer_name}", "offer_found": null, "reason": "auth_required"}}
        """,
        navigation_hints=[
            "https://creditcards.chase.com/cash-back-credit-cards/freedom/offers"
        ],
        expected_output_schema={
            "type": "object",
            "required": ["retailer", "offer_found"]
        },
        max_steps=8
    )
}
```

### Probe Execution Engine

```python
async def execute_probe(
    template: ProbeTemplate,
    params: dict,
    user_context: dict | None = None
) -> ProbeResult:
    """
    Execute a single probe using agent-browser.
    Returns structured result + cost tracking.
    """
    # Fill template with parameters
    task = template.task_template.format(**params)

    # Select LLM (primary, then fallback)
    llm = get_llm(template.llm_model)

    try:
        # Execute via agent-browser: navigate + DOM eval with LLM fallback
        raw_result = await asyncio.wait_for(
            run_agent_browser_probe(
                url=params.get("url", template.navigation_hints[0]),
                js_code=task,
                llm_model=template.llm_model,
                max_steps=template.max_steps,
                headless=True
            ),
            timeout=template.timeout_seconds
        )

        # Parse and validate against expected schema
        structured = parse_and_validate(raw_result, template.expected_output_schema)

        return ProbeResult(
            success=True,
            data=structured,
            tokens_used=raw_result.get("tokens_used", 0),
            model_used=template.llm_model,
            steps_taken=raw_result.get("steps_taken", 1)
        )

    except asyncio.TimeoutError:
        return ProbeResult(success=False, error="timeout")
    except ValidationError as e:
        # Try fallback model if primary gave bad output
        if template.fallback_model != template.llm_model:
            return await execute_probe(
                template._replace(llm_model=template.fallback_model),
                params, user_context
            )
        return ProbeResult(success=False, error=f"validation: {e}")
```

---

## Part 5: Coupon Validation Agents

### Batch Coupon Discovery (Nightly)

```python
async def discover_coupons_batch():
    """
    Nightly job: crawl coupon aggregator sites for each retailer.
    Traditional scraping — no LLM needed.
    """
    sources = [
        ("retailmenot", "https://www.retailmenot.com/view/{retailer_slug}"),
        ("coupons_com", "https://www.coupons.com/coupon-codes/{retailer_slug}"),
        ("dealspotr", "https://dealspotr.com/promo-codes/{retailer_slug}"),
    ]

    for retailer in get_active_retailers():
        for source_name, url_template in sources:
            url = url_template.format(retailer_slug=retailer.slug)
            codes = await scrape_coupon_page(url, retailer.id)

            for code_data in codes:
                await upsert_coupon(
                    retailer_id=retailer.id,
                    code=code_data["code"],
                    description=code_data.get("description"),
                    discount_type=infer_discount_type(code_data),
                    discount_value=code_data.get("value"),
                    source=f"crawl_{source_name}",
                    expires_at=code_data.get("expires"),
                    validation_status="unvalidated"
                )
```

### On-Demand Coupon Validation

```python
async def validate_coupons_for_purchase(
    retailer_id: str,
    product_url: str,
    coupon_candidates: list[dict]
) -> list[CouponResult]:
    """
    Fires when a user queries a product and we have unvalidated coupons.
    Uses agent-browser to test each code at checkout.
    """
    results = []

    # Sort by confidence (previously validated > unvalidated)
    candidates = sorted(
        coupon_candidates,
        key=lambda c: c.get("confidence_score", 0.5),
        reverse=True
    )[:5]  # Test max 5 codes per query (cost control)

    for coupon in candidates:
        probe = PROBE_TEMPLATES["generic_coupon_test"]
        result = await execute_probe(probe, {
            "retailer_url": get_retailer_base_url(retailer_id),
            "product_url": product_url,
            "coupon_code": coupon["code"]
        })

        if result.success:
            # Update coupon cache with validation result
            await update_coupon_validation(
                retailer_id=retailer_id,
                code=coupon["code"],
                accepted=result.data["accepted"],
                discount_applied=result.data.get("discount_applied"),
                error_message=result.data.get("error_message"),
                validated_by="coupon_agent"
            )

            if result.data["accepted"]:
                results.append(result.data)

        # Stop testing if we found a good one that's not stackable
        if results and not is_stackable_retailer(retailer_id):
            break

    return results
```

---

## Part 6: Nightly Batch Jobs (Populating the Catalog)

These run on schedule and keep the discount catalog fresh. Zero user-facing latency impact.

```python
# ─── Job 1: Portal Rate Scraping ──────────────────────────────
# Runs: Every 6 hours
# Original plan: agent-browser scripts (deterministic, no LLM)
# Updates: portal_bonuses table
#
# >>> IMPLEMENTED in Step 2h — backend/workers/portal_rates.py <<<
# Deliberate deviation from the pseudocode below: the real worker uses
# httpx + BeautifulSoup, NOT agent-browser. Portal rate pages are static
# enough that a browser render is overkill; pure-function parsers are
# trivially unit-testable against committed HTML fixtures. Rakuten,
# TopCashBack, and BeFrugal are the three "Low difficulty" portals
# from docs/CARD_REWARDS.md; Chase Shop Through Chase and Capital One
# Shopping are deferred (auth-gated). See docs/CHANGELOG.md §Step 2h
# decision #6 for the full reasoning.
async def batch_portal_rates():
    portals = ["rakuten", "topcashback", "mr_rebates"]
    for portal in portals:
        for retailer in get_active_retailers():
            rate = await scrape_portal_rate(portal, retailer.slug)
            await upsert_portal_bonus(portal, retailer.id, rate)

# ─── Job 2: Rotating Category Update ──────────────────────────
# Runs: 1st of each month + 1st of each quarter
# Method: agent-browser scripts hitting card issuer pages
# Updates: rotating_categories table
async def batch_rotating_categories():
    # Chase Freedom categories page, Discover it page, etc.
    for card_program in get_cards_with_rotating():
        categories = await scrape_rotating_categories(card_program)
        await upsert_rotating_categories(card_program.id, categories)

# ─── Job 3: Discount Program Verification ─────────────────────
# Runs: Weekly
# Original plan: Mix of agent-browser + probe agents
# Updates: discount_programs.last_verified + consecutive_failures + is_active
#
# >>> IMPLEMENTED in Step 2h — backend/workers/discount_verification.py <<<
# Real worker uses a plain httpx GET with Chrome headers and checks
# whether the program name appears in the response body. Introduces a
# "flagged but not failed" distinction: a 200 response without the
# program name is a soft flag (operator review) that does NOT
# increment the failure counter — a program rename should not
# auto-deactivate. Only hard HTTP 4xx/5xx and network errors count
# toward the 3-consecutive-failure deactivation threshold. The
# `consecutive_failures` column was added by migration 0005.
async def batch_verify_discount_programs():
    stale_programs = await get_programs_needing_verification(
        stale_threshold=timedelta(days=7)
    )
    for program in stale_programs:
        if program.verification_url:
            # Simple check — does the page still exist and mention the discount?
            still_active = await check_page_mentions_discount(
                program.verification_url,
                program.program_name
            )
            await update_program_verification(program.id, still_active)
        else:
            # Use probe agent for programs without stable URLs
            probe = build_verification_probe(program)
            result = await execute_probe(probe, {
                "retailer_name": program.retailer.display_name,
                "program_name": program.program_name
            })
            await update_program_verification(program.id, result.success)

# ─── Job 4: Coupon Cleanup ────────────────────────────────────
# Runs: Daily
# Method: Pure SQL
async def batch_coupon_cleanup():
    await db.execute("""
        UPDATE coupon_cache
        SET is_active = false, validation_status = 'expired'
        WHERE expires_at < NOW()
          AND is_active = true
    """)
    await db.execute("""
        UPDATE coupon_cache
        SET validation_status = 'invalid', is_active = false
        WHERE failure_count >= 3
          AND success_count = 0
          AND is_active = true
    """)
```

---

## Cost Model Summary

| Component | Trigger | LLM Cost | Frequency |
|-----------|---------|----------|-----------|
| Price extraction (agent-browser) | Cron (every 6h) | $0 | 4x/day |
| Portal rate scraping | Cron (every 6h) | $0 | 4x/day |
| Rotating category update | Cron (monthly) | $0 | 1x/month |
| Coupon discovery | Cron (nightly) | $0 | 1x/day |
| Coupon cleanup | Cron (daily) | $0 | 1x/day |
| **Watchdog health check** | Cron (nightly) | **~$0.01** | 1x/day |
| **Watchdog self-heal** | On failure threshold | **~$0.05-0.20** | Rare |
| Discount catalog verification | Cron (weekly) | ~$0.02 | 1x/week |
| **Identity discount probes** | Per user query | **~$0.003-0.005** | On demand |
| **Coupon validation** | Per user query | **~$0.005-0.015** | On demand |
| **Portal bonus probes** | Per user query (if stale) | **~$0.003** | On demand |
| **Claude recommendation** | Per user query | **~$0.01-0.03** | On demand |

**Estimated per-query cost (full stack): $0.02 - $0.05**
**Estimated monthly cost at 500 beta users (5 queries/day avg): $75 - $190**

---

## Implementation Priority

1. **Phase 1 (Weeks 1-8):** Retailers table + retailer configs + agent-browser container infrastructure + extraction scripts for all 11 retailers. Basic price extraction pipeline. Free APIs (Best Buy, eBay Browse, Keepa) deferred to Phase 4 production optimization.
2. **Phase 2 (Weeks 9-10):** Discount catalog schema + seed data. User discount profile + card portfolio tables. Watchdog agent — health monitoring + self-healing for selector drift (Claude Opus). Test fixture validation framework.
3. **Phase 2 (Weeks 11-12):** Probe template library — identity discount probes + portal rate checks. Nightly batch jobs. Background workers (SQS via LocalStack).
4. **Phase 3 (Weeks 13-14):** Coupon discovery + validation agents. Confidence scoring pipeline.
5. **Phase 3 (Weeks 15-16):** Claude synthesis layer — combines all data sources into personalized recommendation.

---

## Appendix A — Datacenter-IP HTTP-only Scraping Probe (2026-04-10)

> Motivation: investigate whether retailer search pages can be scraped via plain HTTP (no browser, no JS execution) from a production cloud environment, skipping the browser-container fingerprint layer entirely. Prompted by the discovery that Walmart's search page server-renders its full product list into `__NEXT_DATA__` — meaning the data we need is in the raw HTML response, and the "Robot or human?" page we hit in containers was a client-side JS replacement that only runs when JS executes.

### A.1 Methodology

**Test run:** 2026-04-10, 16:39:41Z → 16:43:19Z. Wall-clock 3 min 38 s for 50 requests across 5 parallel EC2 instances.

**Instances:** 5 × `t4g.nano` (ARM, AL2023) launched into `us-east-1b`, no subnet pinning. Cost: ~$0.0001 total.

**Source IPs (all `AS14618 Amazon.com, Inc.`):**
- `3.83.24.192`
- `18.212.29.146`
- `44.211.131.75`
- `34.238.240.166`
- `18.233.225.77`

**Client configuration:**
- `curl` from Debian OpenSSL stack with `--compressed`, `-L --max-redirs 3`
- Full Chrome 132 browser header set: `User-Agent`, `Accept`, `Accept-Language`, `Accept-Encoding: gzip, deflate, br`, `Sec-Ch-Ua`, `Sec-Ch-Ua-Mobile`, `Sec-Ch-Ua-Platform`, `Sec-Fetch-Dest/Mode/Site/User`, `Upgrade-Insecure-Requests`
- 1-3 s jitter between retailers

**Query:** `"Apple AirPods Pro"` — universal for the electronics subset. Home Depot / Lowe's may yield 0-result pages, which is still a valid signal for bot-detection testing (the search page itself should load).

**Retailers tested:** 10 of 11 Phase 1 retailers. Facebook Marketplace excluded — requires authenticated session, not HTTP-testable.

### A.2 Results — per-retailer matrix (5 IPs each)

| Retailer | Pass/5 | Avg time | Avg size | SSR marker | HTTP code(s) | Verdict |
|---|---:|---:|---:|---|---|---|
| **amazon** | **5/5** | 1.03 s | 965 KB | — (direct HTML) | 200 | ✅ **HTTP viable** |
| **target** | **5/5** | 0.50 s | 165 KB | `__NEXT_DATA__` | 200 | ✅ **HTTP viable** |
| **ebay_new** | **5/5** | 1.25 s | 1 624 KB | — (direct HTML) | 200 | ✅ **HTTP viable** |
| sams_club | 1/5 | 0.50 s | 97 KB (pass) / 16 KB (fail) | `__NEXT_DATA__` | 200 | ⚠️ flaky — "Let us know you're not a robot" on 4/5 |
| walmart | 0/5 | 0.50 s | 15 KB | — | 200 | ❌ "Robot or human?" PerimeterX challenge |
| ebay_used | 0/5 | 0.31 s | 14 KB | — | 200 | ❌ "Pardon Our Interruption" interstitial |
| backmarket | 0/5 | 0.42 s | 0 KB | — | **403** | ❌ explicit IP block |
| best_buy | 0/5 | 0.05 s | 0 KB | — | **000** | ❌ Akamai edge rejects TCP/TLS |
| home_depot | 0/5 | 0.25 s | 2.4 KB | — | 200 | ❓ small response, URL format likely wrong — inconclusive |
| lowes | 0/5 | 0.18 s | 2.4 KB | — | 200 | ❓ small response, URL format likely wrong — inconclusive |

> **Correction note:** the initial auto-classifier marked `ebay_used` as PASS because the response contained the substring "airpods" (template text in the interstitial). Manual inspection of the title (`"Pardon Our Interruption..."`) shows it was actually blocked on all 5. Classifier has been updated locally but raw probe data preserved.

### A.3 Anomaly: Walmart's "first IP was clean" result

An earlier single-instance AWS probe at 16:27Z from IP `3.227.243.49` returned the full Walmart page (921 KB, `__NEXT_DATA__` present, real product prices). The 5-instance stability run 12 minutes later from 5 different IPs in the same region and ASN failed 5/5 with "Robot or human?".

**Interpretation:** Walmart / PerimeterX's IP reputation feed on AWS `us-east-1` IPs is **majority-burned** (5/6 tested IPs flagged). A single lucky IP is not production-viable. **Do not architect around Walmart HTTP scraping from AWS without a residential-proxy fallback.**

### A.4 Cross-environment comparison

Combining this test with the earlier two probes:

| Environment | IP / ASN | Walmart HTTP + headers outcome |
|---|---|---|
| User's home (residential ISP) | residential | ✅ 200, 926 KB, full `__NEXT_DATA__`, real prices |
| AWS EC2 us-east-1 (single) | `3.227.243.49` / AS14618 | ✅ 200, 921 KB (lucky IP) |
| AWS EC2 us-east-1 (5-IP pool) | 5 × AS14618 | ❌ 5/5 challenge |
| GitHub Actions runner | `57.151.137.148` / Azure | ❌ all 4 variations blocked at layer 1 (307 / challenge) |
| Container Chromium on home IP | residential (same as above) | ❌ "Robot or human?" — JS-layer fingerprint block |

**Walmart layered defenses confirmed:**
- **Layer 1 (edge):** IP reputation + header sanity. Cleanly passes residential. Most AWS IPs flagged. Azure/GitHub Actions IPs fully flagged.
- **Layer 2 (JS challenge):** Fingerprints canvas/WebGL/timing when JS runs. Detects headless Chromium / Xvfb / missing `/sys/cpu` even on a clean residential IP.
- **Skip layer 2:** Only possible by not executing JS (curl or httpx, not a browser). Requires passing layer 1 first.

**curl_cffi with perfect Chrome TLS fingerprint did NOT help on datacenter IPs** (tested in earlier probe). IP reputation dominates over TLS/fingerprint when scoring from AWS/Azure ranges.

### A.5 Per-retailer verdicts & recommendations

**HTTP-only viable (drop browser container):**

| Retailer | Parser strategy | Est. LOC |
|---|---|---|
| **amazon** | HTML parse via `selectolax` — products are in `[data-component-type="s-search-result"]` divs (same anchor as current DOM-eval container) | ~60 |
| **target** | JSON parse — extract `__NEXT_DATA__` → `props.pageProps.__PRELOADED_STATE__.*.items` (or similar Target shape, needs verification) | ~40 |
| **ebay_new** | HTML parse via `selectolax` — products in `.s-item` divs (same anchor as current DOM-eval container) | ~60 |

Each replaces an entire `containers/<retailer>/` subdirectory (Dockerfile + `server.py` + `entrypoint.sh` + `extract.sh` + `extract.js` + `config.json` + `test_fixtures.json` ≈ 400 LOC + 900 MB image) with a single Python adapter (~50 LOC, no image, no browser).

**Browser container still required (for now):**

| Retailer | Reason | Future mitigation |
|---|---|---|
| walmart | PerimeterX challenge on most datacenter IPs | Residential proxy pool; revisit if pool expands / reputation changes |
| sams_club | "Not a robot" challenge on 4/5 IPs (same pattern as Walmart) | Same as walmart |
| best_buy | Akamai edge rejects TCP/TLS from AWS IPs (HTTP 000) | Residential proxy required; or use Best Buy Products API (free, keyed) in production |
| backmarket | Explicit 403 on all 5 IPs | Residential proxy required; or API partnership |
| ebay_used | "Pardon Our Interruption" bot interstitial on all 5 IPs (eBay PX-style) | Residential proxy for scraping; or use eBay Browse API (free, OAuth) for both ebay_new and ebay_used |

**Inconclusive — needs re-test with different URL format:**

| Retailer | Issue | Follow-up |
|---|---|---|
| home_depot | 2.4 KB response on path-URL template `/s/Apple+AirPods+Pro` — likely URL format rejected, not a challenge | Retry with `?keyword=` or `?NCNI-5` format; inspect the 2.4 KB body for clues |
| lowes | 2.4 KB response on `/search?searchTerm=` — same pattern as HD | Same — retry with alternate URL format and inspect body |

### A.6 Time & resource savings — if 3 HTTP adapters replace 3 browser containers

**Per-extraction latency (single request):**

| Path | P50 | P95 | Notes |
|---|---:|---:|---|
| Browser container (current) | ~17.9 s | ~25 s | Chromium boot + navigate + wait + DOM eval + close |
| HTTP adapter (measured) | **0.5 – 1.3 s** | ~1.8 s | curl + parse |

**~14–35× faster per request on the 3 viable retailers.**

**End-to-end M2 price aggregation latency:**

M2 currently dispatches all 11 containers in parallel (`m2_prices/container_client.py`), so total latency is gated by the slowest retailer. With 3 retailers dropped to sub-2s HTTP, **P50 stays at ~18 s** (slowest browser container still gates the pipeline). **Direct latency savings: ~0.** The latency win only materializes if the dispatcher short-circuits once the price ceiling is confirmed, which is not the current design.

**Resource footprint (per concurrent extraction batch):**

| Resource | Browser container | HTTP adapter | Savings per replaced retailer |
|---|---:|---:|---:|
| RAM | ~512 MB | ~20 MB | **~490 MB** |
| CPU | Chromium + Xvfb | negligible | ~1 vCPU peak |
| Docker image | ~900 MB (base) + 10 MB | 0 | ~910 MB disk |
| Container count | 1 | 0 | −1 |

For 3 retailers dropped: **~1.5 GB RAM, ~3 vCPU peak, ~2.7 GB disk, 3 fewer containers** on the host.

**Reliability & maintainability:**
- curl output is inspectable on failure; Chromium DOM eval is not
- No selector drift in the HTTP path (the parser binds to `__NEXT_DATA__` JSON keys or HTML anchors, not CSS paths that change weekly)
- No Watchdog self-healing needed for HTTP adapters (no selectors to drift)
- No Xvfb, no dbus errors, no "Chrome exited early" debugging
- ~400 LOC per retailer deleted, ~50 LOC added = **~1 050 LOC net deleted** across 3 retailers

**Production deployment implication:**

The current container fleet only works because the user runs it on a residential ISP. **Moving to Railway / AWS breaks the 5 tough retailers (walmart, sams_club, best_buy, backmarket, ebay_used) regardless of whether they use HTTP or browser containers** — the block is on the IP layer, which is identical between the two approaches. Both paths need the same solution: residential proxies or a scraping service for those retailers. The HTTP adapters for amazon, target, ebay_new will work from AWS without a proxy.

### A.7 Recommended next actions

1. **Write HTTP adapters for amazon, target, ebay_new** (Phase 2 optimization, not blocking). Located at `backend/modules/m2_prices/adapters/<retailer>_http.py`. Register in M2 dispatcher as an alternative to the container path. Wire via `RETAILER_ADAPTER_MODE={"amazon":"http","target":"http","ebay_new":"http", "...":"container"}` config. Retire containers once adapters pass integration tests for 1 week.
2. **Re-test home_depot and lowes** with alternate URL formats (`?keyword=`, `?searchTerm=`, etc.) from one EC2 instance. ~30 s test. Upgrade to HTTP adapters if clean, else keep containers.
3. **Production proxy decision for the 5 tough retailers.** Evaluate:
   - IPRoyal / Bright Data residential pools (~$5–15/GB, ~$0.0001 per search request at 50 KB)
   - ScrapingBee / ScraperAPI managed ($0.002 – $0.005 per request) — includes fingerprinting + rotation
   - Free-tier retailer APIs where available (Best Buy Products API, eBay Browse API) — zero bot risk
4. **Document in `docs/DEPLOYMENT.md`** that the Phase 1 local demo and production AWS deployment have **different retailer coverage** until the proxy story is resolved.
5. **Classifier fix:** add `"pardon our interruption"` to the challenge marker list in any future HTTP probe scripts.

### A.8 Artifacts

- EC2 user-data probe script: `.tmp/ec2-multi-probe.sh` (local, not committed)
- Raw console outputs (50 `PROBE_RESULT` lines + IP/ASN per instance): `.tmp/probe_results/i-*.txt`
- Aggregation script: `.tmp/aggregate.py`
- Earlier single-request probes (home IP, GH Actions, AWS single-instance): curl/urllib/curl_cffi variants documented inline in the session log, not archived

---

## Appendix B — Firecrawl Managed-Service Probe (2026-04-10)

> **STATUS UPDATE (2026-04-17):** Firecrawl is non-functional for Walmart as of this date — every call returns a PerimeterX challenge page (verified via 9 consecutive live calls). The `walmart_firecrawl` adapter is retained in the codebase (with symmetric 3-attempt CHALLENGE retry added 2026-04-17) and remains selectable via `WALMART_ADAPTER=firecrawl`, but the default has been flipped to `decodo_http` (Appendix C). Appendix B below is preserved as the original 2026-04-10 probe record; its conclusions no longer reflect current Firecrawl health on Walmart.

> Motivation: after confirming in Appendix A that 7 of 10 retailers reject direct HTTP requests from AWS datacenter IPs at the network layer, test whether a managed scraping service (Firecrawl) passes those same blocks and how it compares on latency, cost, and operational simplicity. Firecrawl is a SaaS scraper with its own proxy pool, browser rendering, and anti-bot handling; from the caller's perspective it's a single HTTP API: give it a URL, receive rendered HTML back.

### B.1 Methodology

**Test run:** 2026-04-10, 17:08:28Z → 17:09:00Z. Wall-clock **32 s for all 10 retailers scraped concurrently** via one `firecrawl scrape` CLI invocation. Plus one follow-up at 17:10:49Z for eBay-new (which had been clobbered by eBay-used in the batch — both saved to the same filename `ebay.com-sch-i.html.md`).

**Client configuration:**
- Firecrawl CLI v1.12.2, authenticated, credits 101,050 available at start
- `--format rawHtml` — returns unmodified server HTML including script tags (so `__NEXT_DATA__`, `__APOLLO_STATE__`, etc. are preserved)
- `--country US` — geo-targeted scrape via US-region proxy pool
- All retailers in a single batched CLI call → Firecrawl handles concurrency server-side

**Query:** `"Apple AirPods Pro"` — same as Appendix A for apples-to-apples comparison.

**Retailers tested:** same 10 as Appendix A. Facebook Marketplace excluded (auth-gated).

### B.2 Results — full success across all tough retailers

| Retailer | Verdict | Size | SSR marker | Title | Firecrawl duration |
|---|---|---:|---|---|---:|
| amazon | ✅ PASS | 1 026 KB | direct HTML | "Amazon.com : Apple AirPods Pro" | (concurrent) |
| best_buy | ✅ PASS | 1 501 KB | direct HTML | "Apple AirPods Pro - Best Buy" | **31.2 s** (slowest) |
| **walmart** | ✅ **PASS** | 1 281 KB | `__NEXT_DATA__`, `itemStacks` | "Apple AirPods Pro - Walmart.com" | ~7 s |
| target | ✅ PASS | 921 KB | `__NEXT_DATA__` | '"Apple AirPods Pro" : Target' | 18.4 s |
| home_depot | ✅ PASS | 850 KB | **`__APOLLO_STATE__`** | (empty title, 850 KB content present) | 14.3 s |
| lowes | ✅ PASS | 1 213 KB | **`__APOLLO_STATE__`**, **`__PRELOADED__`** | "Apple AirPods Pro at Lowes.com: Search Results" | 24.5 s |
| ebay_new | ✅ PASS | 2 644 KB | direct HTML | "Apple Airpods Pro for sale \| eBay" | 28.0 s / 1.0 s cached |
| ebay_used | ✅ PASS | 2 647 KB | direct HTML | "Apple Airpods Pro for sale \| eBay" | 21.7 s |
| sams_club | ✅ PASS | 763 KB | `__NEXT_DATA__`, `itemStacks` | "Apple+AirPods+Pro - Samsclub.com" | ~5 s |
| backmarket | ✅ PASS | 447 KB | direct HTML | "Apple AirPods Pro \| Back Market" | ~4 s |

**10 / 10 retailers pass — including all 5 that hit hard network-layer blocks from AWS in Appendix A, and the 2 that were "inconclusive" with small-response issues.**

Sample of Walmart products extracted directly from `__NEXT_DATA__` in the Firecrawl response:

```
$224     Apple AirPods Pro 3
$109.39  Restored Apple AirPods Pro White with Magsafe Charging Case
$118     Pre-Owned Apple AirPods Pro 2 White With USB-C Charging Case
$180     Pre-Owned Apple AirPods Pro (2nd Gen) Wireless Earbuds
$117.49  Pre-Owned Restored Apple AirPods Pro with Magsafe Charging
$139.95  Pre-Owned Restored Apple AirPods Pro with Wireless MagSafe
$145     Pre-Owned Apple AirPods Pro 3
$117.49  Pre-Owned Restored AirPod Pro 1st. generation
```

43 total products in the `itemStacks` array — identical shape to the home-IP direct scrape in Appendix A.

### B.3 Discoveries that invalidate prior "inconclusive" verdicts

**Home Depot and Lowe's are NOT URL-format issues.** When Firecrawl retrieves the full rendered pages, they contain:

- Home Depot: `__APOLLO_STATE__` — a GraphQL Apollo client state blob with the full product catalog embedded
- Lowe's: `__APOLLO_STATE__` **and** `__PRELOADED__` — dual SSR state markers

The 2.4 KB responses we got from direct AWS HTTP in Appendix A were the anti-bot interstitials / stub pages that HD and Lowe's serve to suspicious clients before escalating. Firecrawl's proxy + rendering pipeline bypassed that gate. Both retailers are actually **rich SSR sites with structured product data** — excellent candidates for JSON-based parsing.

### B.4 Cost and throughput

**Credit consumption:**
- Starting credits: 101,050
- Ending credits: 101,031
- **Total credits used: 19** across 13 total scrapes (1 smoke test + 1 raw-HTML test + 10-retailer batch + 1 eBay-new re-scrape)
- **Average: ~1.5 credits per scrape**
- Remaining: 101,031 ≈ **~6,700 full 10-retailer price comparisons available on free credits**

**Pricing at Firecrawl's published tiers:**

| Tier | Monthly cost | Credits | Cost per credit | Cost per 10-retailer comparison (15 credits) |
|---|---:|---:|---:|---:|
| Free (current) | $0 | 101 050* | — | $0 |
| Hobby | $16 | 3 000 | $0.00533 | $0.080 |
| Standard | $83 | 100 000 | $0.00083 | $0.0125 |
| Growth | $333 | 500 000 | $0.00067 | $0.010 |

*Current free tier is unusually high — may be a promotional / YC partnership tier. Verify before planning around it.

**Per-user monthly cost projection (Standard tier, $83/mo):**

| Scenario | Comparisons / user / day | Cost / user / month |
|---|---:|---:|
| Light user | 2 | $0.75 |
| Average user | 5 | $1.88 |
| Power user | 20 | $7.50 |
| Demo period (no users) | 0 | $0 — use free tier |

### B.5 Latency comparison — Firecrawl vs browser containers vs HTTP

| Path | P50 for full 10-retailer comparison | Hot-cache P50 | Works from AWS? |
|---|---:|---:|---|
| Current browser containers (home IP) | ~18 s | ~18 s | ❌ No |
| Direct HTTP adapters (AWS) | N/A — only 3 retailers viable | — | ⚠️ Partial (3/10) |
| **Firecrawl (all 10)** | **~31 s** (gated by slowest: Best Buy) | **~1-5 s** (Firecrawl caches) | ✅ Yes |
| Hybrid (3 HTTP + 7 Firecrawl) | ~31 s first call | ~1-5 s cached | ✅ Yes |

**Key observations:**

1. **Firecrawl is ~1.7× slower than local containers on a cold request**, because it routes through Firecrawl's infrastructure, runs its own browser, and returns HTML. For demo loops and fresh lookups this is worse latency.
2. **Firecrawl caches server-side by URL**, so the second hit within ~5 minutes returned eBay in 1.0 s vs 28 s on the first call. Our M2 Redis cache (6 hr TTL) would also absorb most cold hits in a real deployment — users rarely search the same product twice in 5 minutes, but across all users the cache hit rate on common products is high.
3. **Hybrid approach is the best of both worlds**: use direct HTTP for amazon/target/ebay_new (fast, free, zero credits), use Firecrawl for the other 7 (works from AWS, single integration, single bill). Same `31 s` P50 gated by the slowest Firecrawl call, but 3 of 10 cost $0 and are sub-second.

### B.6 Operational simplicity comparison

| Concern | Browser containers | Firecrawl |
|---|---|---|
| Docker images to build + maintain | 11 (~900 MB each) | 0 |
| Selector drift handling | Watchdog agent + Opus heal prompts (ongoing) | None — Firecrawl abstracts |
| Host RAM for full fleet | ~5.5 GB (11 × 512 MB) | ~20 MB (just the caller) |
| Host CPU for full fleet | 11 × Chromium | negligible |
| Fingerprint / TLS / JA3 maintenance | Ours to solve | Firecrawl's problem |
| IP reputation management | Ours to solve (proxies) | Firecrawl's problem |
| Works from any cloud | ❌ (IP-gated) | ✅ |
| Cost model | Fixed (infra) + high eng maintenance | Per-request, linear with usage |
| Dependency on third party | None (but you own the ops burden) | Firecrawl outage = your outage |
| Debuggability | curl/DOM eval inspectable | Black box (you see input + output only) |
| Data freshness (no caching) | real-time | Firecrawl may return server-cached HTML up to X minutes old — verify |

### B.7 Recommended production architecture

Supersedes Appendix A.7 with the Firecrawl data in hand.

**Demo period (now – Phase 2):**
- Use Firecrawl for ALL 10 retailers. Drop the 11 browser containers from production deployment (keep them in the repo as a fallback). ~19 credits for each full 10-retailer price comparison × free 101K credits = ~5,300 free comparisons available for dev/demo/early beta.
- Keep the local browser-container stack for offline development and as a cost-zero fallback when Firecrawl is rate-limited or down.

**Phase 3 — optimization:**
- Port amazon, target, ebay_new to direct `backend/modules/m2_prices/adapters/<retailer>_http.py`. These cost $0 per request and are sub-2-s. Register via `RETAILER_ADAPTER_MODE` config so Firecrawl is still the fallback if the HTTP path starts failing.
- After this change: 3 retailers at $0 + 7 at Firecrawl Standard → **~$0.0088 per full price comparison**, still gated at ~31 s P50 by slowest Firecrawl call.

**Phase 4 — scale optimization (only if cost pressure):**
- Evaluate Bright Data / IPRoyal residential pools for the 7 tough retailers. At $5–15/GB residential + ~60 KB per response, per-request cost drops to ~$0.000001 — **~1000× cheaper than Firecrawl** at volume. Cost: 7 per-retailer scrapers reintroduced (Docker or Python), each with its own fingerprint + retry logic. Worth it only at 10K+ comparisons/day.

**Retailers that should use free APIs instead (Phase 4, if ever):**
- Best Buy → Best Buy Products API (free, keyed) — zero bot risk, Firecrawl savings
- eBay new + eBay used → eBay Browse API (free, OAuth) — zero bot risk, handles both conditions

### B.8 Architectural implications — rewriting the scraping stack

With Firecrawl proven to work for all 10 retailers, the question flips: **do we even need the container-based scraping stack in production, or is the browser-container architecture in `containers/*` now a local-dev-only tool?**

**Arguments for collapsing `containers/` to local-only:**
- 11 Dockerfiles, ~4,400 LOC of bash/JS per container, Watchdog self-heal loop — all exist to solve a problem (bot detection + selector drift) that Firecrawl solves for us
- None of the containers work from production clouds anyway (Appendix A)
- Maintenance cost: every retailer UI redesign currently triggers a Watchdog escalation + Opus heal run. With Firecrawl, the adapter breaks only if the underlying JSON/HTML schema changes — far less frequent than CSS selector churn
- Phase 2 Watchdog supervisor (`workers/watchdog.py`) can be simplified to a lightweight "Firecrawl response shape validator" rather than a full-featured self-heal agent

**Arguments for keeping the containers:**
- Cost at scale (see B.4 — ~$2/user/month at 5 comparisons/day)
- Vendor independence — Firecrawl is a startup, SLA/outage risk
- Real-time data freshness (containers scrape live, Firecrawl may cache server-side)
- Control — we can tune retry, backoff, user-agent, etc. in our own containers

**Recommendation: collapse to Firecrawl for production, preserve containers as a local-dev + emergency-fallback stack.** Move container orchestration out of the M2 critical path entirely. Rewrite `backend/modules/m2_prices/service.py` to dispatch to an adapter interface:

```python
class RetailerAdapter(Protocol):
    async def fetch(self, query: str, max_listings: int) -> list[Listing]: ...

# Implementations:
class FirecrawlAdapter(RetailerAdapter): ...   # production default
class HttpAdapter(RetailerAdapter): ...        # amazon, target, ebay_new after Phase 3
class ContainerAdapter(RetailerAdapter): ...   # local-dev only, existing code path
```

Configuration-driven per-retailer selection, with sensible production defaults (`firecrawl` everywhere) and override for local dev (`container` everywhere).

### B.9 Risks to investigate before committing

Before ripping out the container stack, validate:

1. **Firecrawl server-side cache freshness.** How long does Firecrawl hold a URL's response? If it's >1 hour, we may serve stale prices even without our Redis cache. Test: scrape walmart for a product, wait varying intervals, scrape again, compare `price` vs the live walmart page. Set Firecrawl `--max-age` explicitly if needed.
2. **Rate limiting at the Firecrawl API level.** The 2 concurrent jobs limit shown in `firecrawl --status` would cap our M2 pipeline at 2 concurrent retailer calls — our current container dispatch does 10 in parallel. Would degrade total latency from ~31 s to ~2.5 minutes. Verify the actual concurrency ceiling on Standard/Growth tiers.
3. **SLA + outage history.** Check Firecrawl's status page history. If they have multi-hour outages, our entire price comparison goes down when they do.
4. **Response schema stability.** Firecrawl's `rawHtml` today returns source HTML. If they silently change to `html` (cleaned) our JSON extraction breaks. Pin the API format in a regression test.
5. **`country` targeting effectiveness.** `--country US` routes through US IPs — but does it also pass other regional signals (timezone, Accept-Language) that some retailers check? Walmart worked today with US; some other retailer may need more.
6. **Per-retailer Firecrawl stability.** Today we saw 10/10 on one batch. Run the same batch 10 times over 24 hours and measure stability. Target: ≥95% success rate per retailer. Flag any <95% for contingency.

### B.10 Artifacts

- Firecrawl probe directory: `.tmp/firecrawl_test/`
- Raw JSON-wrapped HTML responses (10 files, ~12 MB total): `.tmp/firecrawl_test/.firecrawl/`
- Plain raw eBay-new HTML: `.tmp/firecrawl_test/ebay_new_raw.html` (2.6 MB)
- Analysis script: `.tmp/firecrawl_test/analyze.py`
- Timestamps: `.tmp/firecrawl_test/fc_start.txt`, `.tmp/firecrawl_test/fc_end.txt`

---

## Appendix C — Decodo Residential-Proxy Probe and walmart_http Adapter (2026-04-10)

> Motivation: Firecrawl (Appendix B) solves all 10 retailers from any cloud but costs ~$0.00125 per Walmart scrape and has concurrency caps that punish bursty workloads. Decodo sells raw residential proxies as a separate SKU for bandwidth — if we already have a parser for Walmart's `__NEXT_DATA__` blob, we can bypass the managed-scraper markup and pay only for wire bytes. This appendix measures whether Decodo's pool beats Walmart's PerimeterX layer-1 check and computes the actual $/scrape at every tier.

### C.1 Methodology

**Test run:** 2026-04-10, ~16:52Z (sanity check) → ~17:11Z (probe). 5 sequential scrapes through a rotating residential proxy.

**Proxy configuration:**
- Endpoint: `gate.decodo.com:7000`
- Authentication: `--proxy-user user-<username>-country-us:<password>` (Decodo requires URL-encoding or `--proxy-user` form due to `=` chars in the password)
- Geo-targeting: **US only** (critical — the base pool landed a Movistar Peru IP in the sanity check; `country-us` suffix routed through Verizon Fios in Staten Island, NY)
- Session type: rotating (fresh IP per request, default)

**Client configuration:** same Chrome 132 header set as Appendix A.1 / A.2. Plain `curl` via `--proxy-user` + `-x`.

**Query:** `"Apple AirPods Pro"` (consistent with Appendix A/B for cross-comparison).

### C.2 Sanity check — geo-targeting matters

| Auth | Resolved IP / ASN | Location | Verdict |
|---|---|---|---|
| Base (`spviclvc9n`) | AS6147 Movistar Peru | Lima, Peru | ❌ wrong geography for Walmart |
| US-targeted (`user-spviclvc9n-country-us`) | AS701 Verizon Fios | Staten Island, NY | ✅ clean US residential |

Decodo's pool defaults to the global distribution — a Peru IP would be immediately suspicious to a US retailer's bot-detection feed. The `country-us` suffix is **required**, not optional.

### C.3 Walmart probe results — 5/5 PASS

| Run | HTTP | Wire body bytes | Wall-time | Title | `__NEXT_DATA__` | `itemStacks` | Challenge markers |
|---:|---:|---:|---:|---|---|---|---:|
| 1 | 200 | 115,529 | 2.73 s | "Apple AirPods Pro - Walmart.com" | ✅ | ✅ | 0 |
| 2 | 200 | 116,356 | 3.49 s | "Apple AirPods Pro - Walmart.com" | ✅ | ✅ | 0 |
| 3 | 200 | 115,913 | 3.10 s | "Apple AirPods Pro - Walmart.com" | ✅ | ✅ | 0 |
| 4 | 200 | 115,636 | 4.08 s | "Apple AirPods Pro - Walmart.com" | ✅ | ✅ | 0 |
| 5 | 200 | 114,970 | 3.63 s | "Apple AirPods Pro - Walmart.com" | ✅ | ✅ | 0 |

- **Success rate: 5/5 (100%)**, **zero retries needed** across rotating IPs
- **Avg wire body: 115,681 bytes ≈ 113 KB** — low std-dev (±0.6%)
- **Avg wall-time: 3.4 s** — faster than Firecrawl's ~7 s average, slower than home-IP's 2.3 s (proxy hop overhead)
- **Avg decompressed HTML: ~905 KB** — matches Appendix A home-IP scrape shape
- **All 5 responses contain full `__NEXT_DATA__` with 43 products** parseable from `props.pageProps.initialData.searchResult.itemStacks[0].items`

Sample products extracted from run 1:

```
$224.00  Apple AirPods Pro 3
$68.00   Restored Apple AirPods Pro White with Magsafe Charging Case
$118.00  Pre-Owned Apple AirPods Pro 2 White With USB-C Charging Case
$145.00  Pre-Owned Apple AirPods Pro 3
$99.95   Pre-Owned Apple AirPods Pro with Wireless MagSafe Charging Case
$159.00  Pre-Owned Apple AirPods Pro 3 White In Ear Headphones MFHP4L
$87.96   Pre-Owned Apple AirPods Pro with MagSafe Charging Case (1st gen)
$99.95   Pre-Owned Apple AirPods Pro with Wireless Charging Case
```

### C.4 Bandwidth per scrape and cost tables

**Per-scrape bandwidth calculation** (rotating IP = fresh TLS handshake per request, no session reuse):

```
measured body          115,681 bytes   (5-run avg)
TLS handshake          ~5,500 bytes
request headers        ~1,000 bytes
response headers       ~1,500 bytes
HTTP/2 framing / TCP   ~500 bytes
─────────────────────────────────────
total per scrape       ~124,181 bytes  ≈ 121 KB
scrapes per decimal GB  ~8,052
```

**Cost per Walmart scrape at every Decodo residential tier** (verified from `decodo.com/proxies/residential-proxies/pricing` on 2026-04-10):

| Tier | $/GB | $/scrape | Monthly $ | Walmart scrapes/mo |
|---|---:|---:|---:|---:|
| Pay-As-You-Go | $4.00 | $0.000497 | one-time | — |
| 3 GB | $3.75 | $0.000466 | **$11.25** | **24,158** |
| 10 GB | $3.50 | $0.000435 | $35.00 | 80,527 |
| 25 GB | $3.25 | $0.000404 | $81.25 | 201,319 |
| 50 GB | $3.00 | $0.000373 | $150.00 | 402,638 |
| 100 GB | $2.75 | $0.000341 | $275.00 | 805,277 |
| 250 GB | $2.50 | $0.000310 | $625.00 | 2,013,193 |
| 500 GB | $2.25 | $0.000279 | $1,125.00 | 4,026,387 |
| 1000 GB | $2.00 | $0.000248 | $2,000.00 | 8,052,774 |

**Comparison to Firecrawl for Walmart-only** (from Appendix B.4):

| Service | $/mo | Walmart scrapes | $/scrape | Relative to Decodo 3 GB |
|---|---:|---:|---:|---|
| Firecrawl Hobby | $16.00 | 2,000 | $0.008000 | **17× more expensive** |
| Firecrawl Standard | $83.00 | 66,666 | $0.001245 | **2.7× more expensive** |
| **Decodo 3 GB** | **$11.25** | **24,158** | **$0.000466** | — baseline |
| Decodo 10 GB | $35.00 | 80,527 | $0.000435 | 6% cheaper / request |
| Decodo 100 GB | $275.00 | 805,277 | $0.000341 | 27% cheaper / request |

At the $11–$35 tier range, Decodo gives 12–40× more Walmart scrapes than Firecrawl for less money.

### C.5 Firecrawl concurrency limits — why we care

Firecrawl's published tiers cap **concurrent in-flight requests**: Free/Hobby 2–5, Standard 50, Growth 100, Scale 150. At ~7 s per Walmart scrape and the bursty M2 query pattern (many users hit the pipeline concurrently), Firecrawl Standard caps effective throughput to ~7 req/s.

Decodo has no concurrency cap per-se; you rate-limit yourself by bandwidth budget and concurrent socket count on your side. For bursty workloads this is a significant operational win — the price-comparison pipeline doesn't queue users behind a managed-service cap.

### C.6 Production architecture — feature-flagged adapter pattern

Implemented in this session. The M2 dispatch layer (`backend/modules/m2_prices/container_client.py::ContainerClient._extract_one`) now routes `walmart` requests via a pluggable adapter selected by the `WALMART_ADAPTER` env var. All other retailers continue through the existing container dispatch.

**Adapter modes:**

| Mode | Code path | Use case |
|---|---|---|
| `container` (legacy) | `ContainerClient.extract("walmart", …)` | Local dev with walmart container. **Broken for production (PX fingerprints Chromium).** |
| `firecrawl` | `adapters/walmart_firecrawl.py::fetch_walmart` | **Demo default.** Managed scraping via Firecrawl API. Works from anywhere. ~$0.00125/scrape at Standard tier. |
| `decodo_http` | `adapters/walmart_http.py::fetch_walmart` | **Production default once launched.** Raw residential proxy via Decodo. ~2.7× cheaper than Firecrawl, no concurrency cap. |

**Shared HTML parser** (`adapters/_walmart_parser.py`):

- Single source of truth for `<script id="__NEXT_DATA__">` extraction + `itemStacks` → `ContainerListing` mapping
- Detects challenge markers (`robot or human`, `px-captcha`, `press & hold`, `access denied`)
- Filters sponsored placements (`isSponsoredFlag`)
- Maps `Restored/Pre-Owned/Refurbished` to `condition=used`
- Resolves relative `canonicalUrl` to absolute `https://www.walmart.com/…`
- Handles both flat `price` and nested `priceInfo.{linePrice,currentPrice,wasPrice}` shapes
- Extracts availability from `availabilityStatusV2.value` (`IN_STOCK`/`OUT_OF_STOCK`) or legacy bool field

**Switch mechanics:**

```bash
# Demo phase — Firecrawl handles walmart
WALMART_ADAPTER=firecrawl
FIRECRAWL_API_KEY=fc-xxxxx

# Production — Decodo residential proxy
WALMART_ADAPTER=decodo_http
DECODO_PROXY_USER=spviclvc9n                  # bare username, adapter adds "user-" + "-country-us"
DECODO_PROXY_PASS=zg6QwOaqbQah6Sg49=          # literal; adapter URL-encodes
DECODO_PROXY_HOST=gate.decodo.com:7000
```

Rollback from Decodo to Firecrawl = change one env var, redeploy. Code is identical.

### C.7 Implementation details

**Decodo adapter (`walmart_http.py`):**
- `httpx.AsyncClient(proxy=<url>, timeout=30, follow_redirects=True)`
- Chrome 132 header set (matches the successful probe)
- **Username munging**: accepts bare username from dashboard; adapter prefixes with `user-` and suffixes with `-country-us` if missing so operators don't have to remember the full syntax
- **Password URL-encoding** (`urllib.parse.quote_plus`) so special characters like `=`, `@`, `:` don't break URL parsing
- **Retry policy**: 1 retry (2 total attempts) on challenge / HTTP error / timeout / parse failure. Rotating IPs mean the retry lands on a fresh IP, which is the whole point of using a residential pool
- **No retry on empty results** — a clean 200 with zero parseable listings is a niche-query signal, not a bot-block
- Per-request bandwidth logged at INFO level (`walmart_http attempt=N status=200 wire_bytes=123456 elapsed_ms=3400`) for cost observability
- Fails fast with `ADAPTER_NOT_CONFIGURED` if creds are missing (rather than silently trying the pool without auth)

**Firecrawl adapter (`walmart_firecrawl.py`):**
- `POST https://api.firecrawl.dev/v1/scrape` with `formats=["rawHtml"]` and `country="US"`
- Bearer-token auth via `FIRECRAWL_API_KEY`
- 45 s timeout (Firecrawl is slower — 7–30 s typical on cold requests)
- Same parser, same error model as the Decodo adapter
- Distinct error codes so CloudWatch / log dashboards can tell Firecrawl-specific failures apart from proxy failures (`FIRECRAWL_HTTP_ERROR`, `FIRECRAWL_UNSUCCESSFUL`, `FIRECRAWL_EMPTY_BODY`)

**Router integration (`container_client.py::_extract_one`):**
- Routing check is scoped to `retailer_id == "walmart"` — every other retailer flows through the unmodified container path
- Imports deferred so unused adapters don't pay the httpx-client init cost at backend startup
- Adapter fn signature matches the container path's contract (returns `ContainerResponse`, never raises)
- `self._cfg` held by the client instance so adapters can read settings without a second import

### C.8 Test coverage

**24 new tests** covering both adapters and the shared parser:

**`test_walmart_http_adapter.py` (15 tests):**
- Proxy URL builder: prefix/suffix logic, double-prefix avoidance, password URL encoding, missing-creds exception
- Happy path: 200 → parsed listings with extraction_method, `max_listings` cap
- Challenge retry: 2 challenge pages → CHALLENGE error, 1 challenge + 1 success → success (retry semantics verified)
- Error surfaces: HTTP 500, missing `__NEXT_DATA__` (PARSE_ERROR), `httpx.ReadTimeout` → TIMEOUT, missing creds → ADAPTER_NOT_CONFIGURED
- Parser edge cases: sponsored filter, out-of-stock handling, absolute URL resolution, missing-next-data raise, challenge detector

**`test_walmart_firecrawl_adapter.py` (9 tests):**
- Happy path with 4 listings, correct extraction_method
- Request shape: Bearer auth header, `country: US` + `rawHtml` in JSON body
- Error surfaces: missing API key, HTTP 429 → FIRECRAWL_HTTP_ERROR, `success=false` → FIRECRAWL_UNSUCCESSFUL, challenge-in-response → CHALLENGE, empty body → FIRECRAWL_EMPTY_BODY

**Test results:** `pytest -q` → **128 passed** (104 existing + 24 new). `ruff check .` → **clean**. No regressions in the existing M1/M2/watchdog/integration/auth/migration test suites.

### C.9 Outstanding risks to validate before flipping to production

These are not probe blockers — they're operational unknowns worth monitoring after deployment.

1. **Pool burn rate over time.** The 5/5 success rate is a single snapshot. A fresh PR at C.8 should rerun the 5-scrape probe daily for a week and alert if success rate drops below 80%. If burn rate is real, budget 1.2–1.5× effective cost to cover retries.
2. **Query diversity.** We tested `"Apple AirPods Pro"` — a common, safe query. Niche or adult queries may trigger different PX risk scores. Run the probe with a handful of query categories (electronics, groceries, adult, niche) before broad rollout.
3. **Sustained throughput.** Our probe ran 5 sequential requests. The production M2 pipeline may fire bursts of dozens per minute during peak usage. Load-test at 2× expected peak before launch.
4. **Decodo SLA + billing alerts.** Set `DECODO_PROXY_*` bandwidth alerts at 50%/80%/100% of the committed tier in the Decodo dashboard to avoid surprise overage.
5. **Fallback chain.** Today the adapter retries once within Decodo. A more resilient design: on terminal failure, fall back to Firecrawl (`WALMART_ADAPTER=decodo_http_with_firecrawl_fallback`) for the remainder of the request. Cost vs reliability tradeoff — deferred.
6. **Observability.** Current per-request bandwidth is logged but not exported. Add a `walmart_http_wire_bytes_total` counter (Prometheus/OpenTelemetry) so you can chart Decodo consumption against the tier ceiling in real time.
7. **Schema drift on Walmart's `__NEXT_DATA__`**. Walmart is Next.js-based and has changed the `props.pageProps.initialData.*` shape in the past. The parser walks the tree looking for `itemStacks` wherever it appears, which is resilient to nesting changes, but a complete rename would break it. Consider adding a daily canary query that asserts `len(listings) > 0` for a known product UPC and alerts otherwise.

### C.10 Artifacts

**Probe artifacts:**
- Decodo probe script: `.tmp/decodo_probe.sh`
- Per-run raw HTML responses (5 files, ~4.5 MB total): `.tmp/decodo_results/walmart_{1..5}.html`

**Implementation files (committed):**
- `backend/modules/m2_prices/adapters/__init__.py` — subpackage marker
- `backend/modules/m2_prices/adapters/_walmart_parser.py` — shared `__NEXT_DATA__` → `ContainerResponse` logic
- `backend/modules/m2_prices/adapters/walmart_http.py` — Decodo residential proxy adapter
- `backend/modules/m2_prices/adapters/walmart_firecrawl.py` — Firecrawl managed API adapter
- `backend/modules/m2_prices/container_client.py` — added `_extract_one` router, `_resolve_walmart_adapter`, `walmart_adapter_mode` attr
- `backend/app/config.py` — added `WALMART_ADAPTER`, `FIRECRAWL_API_KEY`, `DECODO_PROXY_{USER,PASS,HOST}`
- `.env.example` — documented each new env var with a comment explaining when it's required
- `backend/tests/fixtures/walmart_next_data_sample.html` — realistic fixture with 4 real-shape products + 1 sponsored placement (for filter test)
- `backend/tests/fixtures/walmart_challenge_sample.html` — minimal "Robot or human?" challenge page
- `backend/tests/modules/test_walmart_http_adapter.py` — 15 tests
- `backend/tests/modules/test_walmart_firecrawl_adapter.py` — 9 tests
- `backend/tests/modules/test_container_client.py` — updated `_setup_client` fixture with `walmart_adapter_mode = "container"` default
- `backend/tests/modules/test_container_retailers.py` — same fixture update

### C.11 Proxy Scoping — Decodo Bandwidth Cost Leak Fix (2026-04-17)

**Motivation.** Decodo usage dashboard in the 2026-04-17 billing window showed ~85 MB consumed with only ~1.53 MB matching walmart.com. The noise:
- ~75 MB — `*.fbcdn.net` / `*.facebook.com`
- ~15 MB — Google/Chromium telemetry: `*.gvt1.com`, `*.googleapis.com`, `android.clients.google.com`, `accounts.google.com`, `mtalk.google.com`, `content-autofill.googleapis.com`, `optimizationguide-pa.googleapis.com`

**Diagnosis (source-confirmed).** The leak is NOT in the walmart adapters. It's `fb_marketplace`:

- `containers/fb_marketplace/proxy_relay.py` relays `127.0.0.1:18080 → gate.decodo.com:7000` with Decodo credentials injected.
- `containers/fb_marketplace/extract.sh` launches Chromium with a single `--proxy-server=http://127.0.0.1:$PROXY_RELAY_PORT` flag.
- Chromium routes **every** network request through that proxy — not just `facebook.com`. Every fbcdn image/script/Meta-Pixel beacon + every Chromium-internal background fetch (component updater, safe-browsing, sync, optimization guide, GCM) consumes paid Decodo bytes.
- `walmart_http.py` is clean: exactly one `httpx.AsyncClient.get` per call, no subresource fetching. Verified by `test_fetch_walmart_makes_exactly_one_request_per_call`.
- `walmart_firecrawl.py` is clean: does not overlay Decodo as BYOP proxy. Regression-guarded by `test_firecrawl_payload_has_no_decodo_overlay`.

**Fix — three-layer defense.**

1. **Chromium telemetry kill flags** in `containers/fb_marketplace/extract.sh`:
   ```
   --disable-background-networking --disable-background-timer-throttling
   --disable-backgrounding-occluded-windows --disable-breakpad
   --disable-client-side-phishing-detection --disable-component-update
   --disable-default-apps --disable-domain-reliability --disable-sync
   --disable-features=OptimizationHints,OptimizationGuideModelDownloading,Translate,MediaRouter,InterestFeedContentSuggestions,CalculateNativeWinOcclusion,AutofillServerCommunication
   --metrics-recording-only --no-pings --no-report-upload
   ```
   Collectively these silence the ~15 MB/hour Google slice.

2. **Proxy bypass list** — any background request Chromium still decides to make goes out the container's datacenter IP direct, NOT through Decodo:
   ```
   --proxy-bypass-list='<-loopback>;*.googleapis.com;*.gvt1.com;*.gstatic.com;
       *.google-analytics.com;*.googletagmanager.com;*.doubleclick.net;
       *.googleusercontent.com;clients*.google.com;accounts.google.com;
       mtalk.google.com;update.googleapis.com;optimizationguide-pa.googleapis.com;
       content-autofill.googleapis.com;*.chrome.google.com;edgedl.me.gvt1.com;
       redirector.gvt1.com'
   ```

3. **Image blocking** (default ON, opt-out via `FB_MARKETPLACE_DISABLE_IMAGES=0`). `extract.js` only reads `<img src>` as a string — it doesn't need the pixels. `--blink-settings=imagesEnabled=false` eliminates ~70% of fbcdn bytes per scrape with zero loss of DOM signal.

**Firecrawl hardening (defense in depth, even though it wasn't the leak).** `walmart_firecrawl.py` payload now includes `blockAds: true` (suppresses Meta Pixel/GA/GTM at Firecrawl's browser layer), `onlyMainContent: false` (we need the full `__NEXT_DATA__`), and `waitFor: 1500` (SSR hydration window). The payload still deliberately omits any `proxy`/`proxyServer`/Decodo reference — regression-guarded.

**Observability.** Both Walmart adapters emit a structured `adapter=walmart_{http,firecrawl} target=... attempt=... status=... wire_bytes=... elapsed_ms=...` log line per request. Grep + awk over `docker logs` / `journalctl` gives accurate per-adapter bytes-per-scrape accounting without a Prometheus exporter.

**Measured bandwidth (live EC2, 2026-04-17, query = "Apple AirPods Pro 2", 3 listings).**

| Target host | Pre-fix bytes | % pre-fix | Post-fix bytes | Category |
|---|--:|--:|--:|---|
| `r5---sn-ojqxo5-5j.gvt1.com` | 461,130 | 77.4% | **0** | Chromium component updater |
| `static.xx.fbcdn.net` | 49,813 | 8.4% | 12,808 | Facebook CDN (legit) |
| `android.clients.google.com` | 14,120 | 2.4% | **0** | Google telemetry |
| `redirector.gvt1.com` | 11,924 | 2.0% | **0** | Chromium update redirector |
| `accounts.google.com` | 11,122 | 1.9% | **0** | Google sign-in probe |
| `www.google.com` | 10,286 | 1.7% | **0** | Connectivity check |
| `optimizationguide-pa.googleapis.com` | 9,561 | 1.6% | **0** | Chromium AI-hints fetch |
| `scontent-*.xx.fbcdn.net` | 9,321 | 1.6% | 6,596 | Facebook CDN (legit) |
| `r4---sn-*.gvt1.com` (×2) | 16,425 | 2.8% | **0** | Chromium update |
| `clients2.google.com` | 1,568 | 0.3% | **0** | Google component probe |
| `mtalk.google.com` | 405 | 0.1% | **0** | GCM push channel |
| `www.facebook.com` | 0 | — | 0 | (appears in v2 only, ~6.5 KB) |
| **TOTAL per scrape** | **595,675** | 100% | **19,404** | |

**Net: 96.7% reduction — 596 KB → 19 KB per scrape. Listings returned unchanged (3/3). Extract time faster (34.8 s → 28.1 s) because Chromium is no longer blocking on update fetches during warmup.**

Extrapolated to the observed 85 MB/19 h billing window: 17 scrapes × 19 KB ≈ **0.3 MB** of legitimate Facebook traffic post-fix. One-time container-startup component pulls (which are the biggest single contributor to the historical number) are also now suppressed by `--disable-component-update`.

**Verification checklist (post-deploy).** After rsync'ing `containers/fb_marketplace/` to EC2, rebuilding the container, and running a handful of scrapes:
1. `docker logs fb_marketplace 2>&1 | grep "metrics\|component_update\|gvt1"` → should return empty or only pre-flag stale lines.
2. Decodo dashboard → Usage → filter the billing window post-deploy → confirm `*.gvt1.com`, `googleapis.com`, `accounts.google.com` slices are zero or near-zero.
3. Confirm `fb_marketplace/extract` still returns ≥3 listings for a common marketplace query (e.g. "iPhone"). If zero, set `FB_MARKETPLACE_DISABLE_IMAGES=0` in the container env and retry.
4. Rotate any Decodo/Firecrawl credentials exposed in-session (SP-decodo-scoping transcript leak).

**Implementation files (2026-04-17):**
- `containers/fb_marketplace/extract.sh` — Chromium flag/bypass block added.
- `backend/modules/m2_prices/adapters/walmart_http.py` — structured log line.
- `backend/modules/m2_prices/adapters/walmart_firecrawl.py` — `blockAds`/`onlyMainContent`/`waitFor` + structured log + explicit "no Decodo overlay" comment.
- `backend/tests/modules/test_walmart_firecrawl_adapter.py` — `test_firecrawl_request_includes_block_ads`, `test_firecrawl_payload_has_no_decodo_overlay`.
- `backend/tests/modules/test_walmart_http_adapter.py` — `test_fetch_walmart_makes_exactly_one_request_per_call`.
- `backend/tests/modules/test_fb_marketplace_extract_flags.py` — 26 parametrized asserts on the shell script.

### C.12 Sams Club — Same Decodo-Scoped Pattern (2026-04-18, SP-samsclub-decodo)

**Motivation.** After the timing-optimization work in PR #27 (trimmed warmup + scroll for 4 retailers), sams_club was timing out at 96–110 s with 0 listings and `EXTRACTION_FAILED`. Three consecutive runs confirmed it was deterministic, not flaky. Reading the full container stderr showed the retailer title changing from `Sam's Club - Wholesale Prices on Top Brands` (homepage OK) to `Let us know you're not a robot - Sam's Club` on `/s/...` navigation — i.e. an Akamai-style `/are-you-human?url=...&uuid=...&vid=...&g=b` gate fired by the AWS datacenter IP.

**Diagnosis.** Same class of failure as fb_marketplace before C.11: IP-reputation-based bot detection. The base-extract.sh comment `# Similar to Walmart patterns but without PerimeterX issues` was stale — Sam's Club *does* gate on IP reputation; it just wasn't tripping until the container host had been identified often enough.

**Fix.** Replicate the C.11 architecture for sams_club:

1. Copy `proxy_relay.py` verbatim from `fb_marketplace/` to `sams_club/` — same Decodo credentials injection, same per-connection `proxy_bytes` accounting to `/tmp/proxy_bytes.log`.
2. Rewrite `containers/sams_club/extract.sh` with:
   - The same 13 Chromium telemetry kill flags from C.11.
   - The same `PROXY_BYPASS_LIST` (fifteen `*.google*`/`*.doubleclick.net`/`*.gvt1.com` entries so Chromium-internal fetches egress the datacenter IP, not Decodo).
   - `SAMS_CLUB_DISABLE_IMAGES=1` default → `--blink-settings=imagesEnabled=false` (opt-out via env).
   - `"are you human"` added to the bot-detection title regex.
3. Keep the homepage warmup (`$SITE_HOMEPAGE` before `$SEARCH_URL`). Measured that even through Decodo, direct `/s/` navigation without homepage cookies still trips the gate intermittently.
4. Update `scripts/ec2_deploy.sh` to source Decodo creds from `/etc/barkain-scrapers.env` and `case retailer in fb_marketplace|sams_club` inject `-e DECODO_PROXY_USER -e DECODO_PROXY_PASS` at `docker run` time.

**Measured (live EC2, 3 consecutive POST /extract, query = "Apple AirPods Pro 2", max_listings=3).**

| Phase | listings/run | time_ms | error |
|---|---|---|---|
| Pre-fix | 0 / 0 / 0 | 97,966 / 109,752 / 109,160 | `EXTRACTION_FAILED` (trapped at `/are-you-human/`) |
| Post-fix | 3 / 3 / 3 | 76,372 / 109,373 / 107,270 | none |

**Bandwidth (post-fix, from `/tmp/proxy_bytes.log` across 3 successful runs, ~850 KB / run average).**

| Target host | Category | Bytes across 3 runs |
|---|---|--:|
| `i5.samsclubimages.com` | Image CDN | 2,156,436 |
| `www.samsclub.com` | Main site HTML/JS | 319,318 |
| `use.typekit.net` | Adobe Fonts | 47,026 |
| `i5.walmartimages.com` | Shared image CDN | 33,184 |
| `b.wal.co` | Beacon | 26,533 |
| `beacon.samsclub.com` | First-party telemetry | 17,174 |
| `b.px-cdn.net` | PerimeterX (must stay on-proxy) | 13,057 |
| `collector-pxslc3j22k.px-cloud.net` | PerimeterX | 10,664 |
| **Per-run total** | | **~850 KB** |

**Known follow-up:** `--blink-settings=imagesEnabled=false` is honored but Sam's Club's product-grid still causes ~700 KB/extract of `i5.samsclubimages.com` traffic (fetched via some non-blink path — possibly `fetch()` in their SPA bundle). Candidate mitigations: add `*.samsclubimages.com` + `*.walmartimages.com` to the bypass list (serve images direct over datacenter IP instead of through Decodo — safe because the image CDNs are not IP-gated). Deferred — current 850 KB/extract is acceptable given the retailer was at 100% failure before.

**Gotcha captured (DPS-equivalent learning).** When copying Decodo creds across containers via shell, use `cut -d= -f2-` (NOT `cut -d= -f2`). The Decodo password is base64-terminated with a trailing `=`, and `-f2` silently strips it. Symptom on first deploy: CONNECT tunnel failed response 407 from the upstream proxy; relay was up but auth was bad because the password was off by one char.

**Implementation files (2026-04-18):**
- `containers/sams_club/extract.sh` — full rewrite, Decodo-routed.
- `containers/sams_club/proxy_relay.py` — copy of fb_marketplace/proxy_relay.py (byte-identical).
- `containers/sams_club/Dockerfile` — adds `COPY proxy_relay.py .`.
- `scripts/ec2_deploy.sh` — sources `/etc/barkain-scrapers.env`, injects `DECODO_PROXY_{USER,PASS}` for `fb_marketplace|sams_club`.
- `backend/tests/modules/test_sams_club_extract_flags.py` — 26 parametrized asserts (telemetry flags, feature disables, bypass-list patterns, image-blocking opt-out, bot regex, warmup present).


## Appendix D — Required extract.sh conventions (2026-04-10, first live run)

> Motivation: the 2026-04-10 first-ever live 3-retailer run against real Amazon + Best Buy + Walmart uncovered three latent bugs that every retailer container had shipped with since Phase 1, because Phase 1's container tests all used respx mocks and never exercised the real subprocess → stdout boundary. These conventions are now load-bearing and every new retailer extract.sh must follow them.

### D.1 fd 3 stdout convention

**Problem:** `agent-browser` writes progress lines to **STDOUT**, not stderr:

```
✓ Amazon.com. Spend less. Smile more.
  https://www.amazon.com/
✓ Done
✓ Done
{...JSON here...}
✓ Browser closed
```

If extract.sh's python3 JSON dumper writes to stdout alongside all that chatter, `server.py`'s `stdout, stderr = await proc.communicate(); json.loads(stdout)` sees a leading `✓` and raises `Expecting value: line 1 column 1 (char 0)` → error code `PARSE_ERROR`.

**Convention (required for every retailer extract.sh):**

```bash
# Immediately after `trap cleanup EXIT`, before any other command:
# Reserve fd 3 as the real stdout and redirect fd 1 to stderr for all
# other commands. Only the final extraction JSON should land on fd 3.
exec 3>&1
exec 1>&2
```

Then every non-capturing `ab` call (`ab open`, `ab wait`, `ab scroll`, `ab close`) prints its progress lines through fd 1, which is now stderr, so they appear in `docker logs` for debugging but never pollute the HTTP response body.

Capturing calls via `$(...)` still work correctly because command substitution creates a subshell with its own pipe-backed fd 1 that overrides the parent's `exec 1>&2`:

```bash
# These STILL capture stdout correctly:
PAGE_TITLE=$(ab get title 2>/dev/null || echo "")
RAW_OUTPUT=$(ab eval --stdin < "$JS_FILE" 2>/dev/null || echo "")
```

The final JSON emit and the failure-path fallback both go through fd 3:

```bash
# Success path:
python3 -c "
import json, sys
raw = sys.stdin.read().strip()
if raw.startswith('\"'):
    raw = json.loads(raw)
data = json.loads(raw)
json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
" <<< "$RAW_OUTPUT" >&3

exit 0
done

# Failure fallback (after retry loop exhausts):
log "Failed after $RETRY_MAX attempts"
echo '{"listings":[],"metadata":{"url":"","extracted_at":"","bot_detected":true}}' >&3
exit 1
```

**Currently applied in:** `containers/amazon/extract.sh`, `containers/best_buy/extract.sh`.

**Latent in:** `containers/{target,home_depot,lowes,ebay_new,ebay_used,sams_club,backmarket,fb_marketplace,walmart}/extract.sh`. Backfill before any of those containers is used live. Long-term, move the convention into a shared `containers/base/extract_helpers.sh` that every retailer's extract.sh sources, so it can't rot per-retailer.

**Reference commit:** `8755802` on `phase-2/scan-to-prices-deploy`.

### D.2 Xvfb lock cleanup in entrypoint.sh

**Problem:** `Xvfb` creates `/tmp/.X99-lock` when it binds display :99. On a clean `docker run` from a fresh image, no lock exists → Xvfb starts. But on `docker restart <retailer>`, the container filesystem persists, the lock file stays behind, and the restarting Xvfb prints:

```
(EE) Server is already active for display 99
	If this server is no longer running, remove /tmp/.X99-lock
	and start again.
(EE)
```

then exits. `exec uvicorn` then starts the FastAPI server without an X backend, every `ab open` call dies with `Missing X server or $DISPLAY`, and the retry loop exhausts both attempts → `EXTRACTION_FAILED: Script exited with code 1`.

**Convention:** always remove stale locks + sockets before launching Xvfb in `containers/base/entrypoint.sh`:

```bash
# Remove any stale X lock files left behind by a previous container run.
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true

# Start Xvfb on display :99
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
sleep 2   # bumped from 1s to reduce a race observed on t3.xlarge
```

The guard is idempotent and costs nothing on first boot. `2 s` sleep is a minimum — bump further if Xvfb is slow to bind on smaller instance types.

**Reference commit:** `8755802`.

### D.3 Minimum EXTRACT_TIMEOUT

**Problem:** Phase 1 set `EXTRACT_TIMEOUT = 60` seconds in `containers/base/server.py` as a conservative default, but live Best Buy runs at ~90 s end-to-end on t3.xlarge (warmup + homepage jitter + scroll + search URL + scroll + DOM eval). A 60 s ceiling kills the subprocess mid-extraction and returns `TIMEOUT`.

**Convention:** `EXTRACT_TIMEOUT` defaults to **180 s** and is env-overridable:

```python
EXTRACT_TIMEOUT = int(os.environ.get("EXTRACT_TIMEOUT", "180"))  # seconds; live Best Buy + Walmart regularly exceed 60s
```

180 s is based on observed ~94 s worst case with ~2× headroom. Per-retailer overrides via the `EXTRACT_TIMEOUT` env var in each retailer's run command if a retailer consistently needs more.

The backend-side container client timeout (`CONTAINER_TIMEOUT_SECONDS` in `.env`) must be **at least as large** as the container's `EXTRACT_TIMEOUT` or the backend will disconnect before the container responds. 180 s is the current minimum for both.

**Reference commit:** `8755802`.

### D.4 Test gap — the respx trap

Phase 1's container tests (`test_container_client.py`, `test_container_retailers.py`) all use `respx` to mock the HTTP layer between backend and container, so the backend sees a pre-fabricated JSON response body and never invokes a real subprocess. Similarly, `test_walmart_firecrawl_adapter.py` uses respx to mock the Firecrawl API and never hits the real endpoint.

Consequences observed on the 2026-04-10 live run:
- **D.1, D.2, D.3** — all latent in every retailer container, never triggered because the mocks short-circuited the subprocess path entirely.
- **Firecrawl v2 API shape drift** (`country` → `location.country`) — never caught by `test_walmart_firecrawl_adapter.py` because respx doesn't validate the request body shape.

**Required countermeasure** (to be implemented as part of Step 2b or a dedicated testing mini-step): every vendor adapter (Firecrawl, Decodo, future Keepa) and every retailer container must have a companion real-API smoke test that runs nightly in CI against the real endpoint, produces a pass/fail health check, and alerts on failure. The smoke test does not replace the respx unit tests — it complements them. Unit tests stay fast; smoke tests catch schema drift before the next live demo.

See `Barkain Prompts/Error_Report_Scan_to_Prices_Deployment.md` § SP-4 for the Firecrawl v2 schema drift case study.

---

## Appendix E — Amazon `extract.js` Conventions (SP-9 + post-2b-val, 2026-04-12)

Amazon's `containers/amazon/extract.js` is the most battle-tested of the retailer extractors because Amazon's search page is the most adversarial (sponsored listings, installment pricing, refurb markings, split DOM). Every convention below was forced by a real bug caught on live runs.

### E.1 Title extraction — join all child spans, don't pick one

**Original bug (SP-9, Step 2b first fix).** Amazon's title chain used `[data-cy="title-recipe"] span` to grab the first span inside the title container. This worked against the Step 2b test fixtures, but against live Amazon in Step 2b-val the title came back as just `"Sony"` (the brand word). The reason: Amazon now splits brand and product into **sibling spans** inside the same `h2` / `[data-cy="title-recipe"]` container:

```html
<h2>
  <span>Sony</span>
  <span>WH-1000XM5 Premium Noise Canceling Headphones…</span>
</h2>
```

`querySelector('span')` returns the first span only.

**Fix (Step 2b-val).** The `extractTitle()` function now collects **all** span `innerText` values inside `[data-cy="title-recipe"]` and `h2`, deduplicates by exact text, and joins with spaces. The fallback ladder is:

1. Join all spans inside `[data-cy="title-recipe"]` (most reliable when present)
2. Full `[data-cy="title-recipe"]` `innerText` (handles the no-span layout)
3. Join all spans inside `h2`
4. Full `h2` `innerText`
5. `h2 a` `innerText`
6. `img.s-image` / `img[data-image-latency="s-product-image"]` `alt` text

A candidate is accepted immediately if it is ≥3 words OR >20 chars (substantive title). Shorter candidates are held as fallback and only returned if nothing else fires. Short candidates like `"Sony"` (1 word / 4 chars) still survive as a last-resort fallback so we never return an empty title.

### E.2 Sponsored-noise stripping — Unicode-aware apostrophe

**Bug.** Amazon sponsored listings prepend the title with phrases like `You're seeing this ad based on the product's relevance to your search query.`. The Step 2b regex used ASCII `'`, but Amazon emits the curly apostrophe `'` (U+2019), so the regex never matched.

**Fix.** Every apostrophe slot in the sponsored-noise patterns uses the character class `['\u2019]`:

```js
const SPONSORED_NOISE = [
  /Sponsored\s*/gi,
  /You['\u2019]re seeing this ad based on the product['\u2019]s relevance to your search query\.?\s*/gi,
  /Leave ad feedback\s*/gi,
  /You['\u2019]re seeing this ad\s*/gi,
];
```

All sponsored-noise patterns run against every title candidate before substance-checking.

### E.3 Condition detection — `detectCondition(title)`

**Bug.** `condition` was hardcoded to `"new"` for every Amazon listing, even when the title clearly said `(Renewed)` or `(Refurbished)`.

**Fix.** Title-regex-based classifier:

```js
function detectCondition(title) {
  const lower = title.toLowerCase();
  if (/\brenewed\b|\brefurbished\b|\brecertified\b|\bre-certified\b|\bcertified\s+pre-?owned\b|\bpre-?owned\b/.test(lower)) {
    return 'refurbished';
  }
  if (/\bused\b|\bopen\s*box\b/.test(lower)) {
    return 'used';
  }
  return 'new';
}
```

Word-boundary anchors prevent `"newly released"` → `"new"` from matching `"renewed"`. Best Buy's `extract.js` uses the same helper and also accepts `"Geek Squad Certified"` as refurbished.

### E.4 Installment price rejection — `extractPrice(el)`

**Bug.** Amazon shows `"$45/mo"` as a prominent non-strikethrough price on carrier-locked phones and Mint Mobile sponsored cards. The Step 2b selector `.a-price:not([data-a-strike]) .a-offscreen` picked up the monthly as the price, so an iPhone 16 came out as `$45`.

**Fix.** `extractPrice()` scans all `.a-price:not([data-a-strike])` elements on the card. For each, it walks up to `.a-row` / `.a-section` and checks the container's innerText against an installment regex:

```js
const INSTALLMENT_RE = /\$[\d,]+(?:\.\d{1,2})?\s*\/\s*mo\b|\/\s*month\b|\bper\s*month\b|\bmonthly\s+payment\b|\bfrom\s*\$[\d,]+\s*\/\s*mo\b/i;
```

Candidates whose surrounding row matches are dropped entirely. Surviving candidates are parsed to floats and the `max()` is returned (installment amounts are almost always smaller than outright prices, but `max` is a belt-and-suspenders safeguard). If **all** `.a-price` elements match the installment regex, the function falls through to a raw card-text scan with the installment fragment stripped first.

### E.5 Reference commits + currently-applied retailers

- Amazon `extract.js` has all of E.1–E.4 applied (hot-patched to the EC2 amazon container via `docker cp`; see 2b-val-L1 in CLAUDE.md known caveats for redeploy notes)
- Best Buy `extract.js` has E.3 (`detectCondition` incl. Geek Squad) and a carrier/installment filter documented in Appendix H
- Walmart `_walmart_parser.py` has the Python equivalents of E.3 + E.4 (Appendix H)
- All other retailers: E.1–E.4 are latent and need to be ported when those containers go live

---

## Appendix F — Relevance Scoring (`_score_listing_relevance`, post-2b-val state, 2026-04-12)

The first live demo (2026-04-10) revealed that each retailer's on-site search returns similar-but-not-identical products, and `_pick_best_listing` selected the cheapest listing regardless of relevance. Since then the scorer has gone through four rounds of hardening — each one forced by a real wrong match observed in a live run. This appendix describes the **current state** (not the history; see CLAUDE.md decisions log for the progression).

### F.1 Product-name cleanup (`_clean_product_name`)

Gemini and UPCitemdb occasionally bake supplier catalog codes into the resolved product name:

```
Apple iPhone 16 256GB Black (CBC998000002407)
Apple AirPods Pro with Wireless Charging Case (MWP22A...)
Logitech MX Master Wireless Mouse (910-005527)
JBL Flip 6 Portable Waterproof Bluetooth Speaker (Teal) (JBLFLIP6TEALAM)
```

These codes are **supplier-specific** — no retailer listing title contains them — so they poison both the search query (Amazon fuzz-matched `iPhone 16 … (CBC…)` to iPhone SE) and the relevance hard gate (the cleaned product otherwise had one strong identifier, which the `any()` rule could satisfy, but the CBC token alone could never match and under `all()` semantics would reject every listing).

The cleanup regex strips parentheticals whose content is all-uppercase-and-digits with at least 5 characters and no internal spaces:

```python
_PRODUCT_CODE_IN_PAREN = re.compile(r"\s*\(\s*[A-Z0-9][A-Z0-9.\-/]{4,}\s*\)")
```

Descriptive parentheticals like `(Teal)`, `(Black)`, `(1st gen)`, `(256 GB)` are kept because their content has a lowercase letter or an internal space. `_clean_product_name` is called at two sites:

- `_build_query(product)` — the search string sent to every retailer
- `_score_listing_relevance(title, product)` — the basis for identifier extraction and token overlap

The raw `product.name` is still what the DB stores and what the iOS app displays, so the visible product card is unaffected.

### F.2 Rules, in order

`_score_listing_relevance(listing_title, product)` returns 0.0 or a float in `[0.4, 1.0]`. Each rule is a hard gate — any failure returns 0.0.

**Rule 0 — Accessory filter.** Reject listings whose title contains accessory keywords, unless the resolved product itself is an accessory:

```python
_ACCESSORY_KEYWORDS = frozenset({
    "case", "cases", "cover", "covers", "protector", "protectors", "skin", "skins",
    "charger", "chargers", "cable", "cables", "adapter", "adapters", "dock", "docks",
    "stand", "stands", "mount", "mounts", "holder", "holders", "strap", "straps",
    "pouch", "bag", "sleeve", "sleeves",
    "compatible", "replacement", "accessory", "accessories",
})
_ACCESSORY_PHRASE_RE = re.compile(
    r"\b(?:for|fits|designed\s+for|compatible\s+with)\s+(?:apple|sony|samsung|jbl|bose|google|microsoft|the|your|new)?\s*(?:i?Phone|i?Pad|i?Mac|AirPods|Galaxy|Pixel|Surface|MacBook|Watch)\b",
    re.IGNORECASE,
)
```

Killed the `SUPFINE Compatible Protection Translucent Anti-Fingerprint` screen-protector that was slipping through at 2/5 = 0.4 token overlap for an iPhone 16 query.

**Rule 1 — Model-number hard gate.** Extract strong identifiers from the cleaned product name using the `_MODEL_PATTERNS` list. If any identifiers are extracted, **at least one** must appear in the listing title, matched with a word-boundary regex (not `in` substring) so `iPhone 16` does not match `iPhone 16e`:

```python
def _ident_to_regex(ident: str) -> re.Pattern:
    parts = [re.escape(p) for p in re.split(r'\s+', ident.strip()) if p]
    body = r'\s+'.join(parts)
    return re.compile(r'(?<!\w)' + body + r'(?!\w)', re.IGNORECASE)
```

The `(?<!\w)` and `(?!\w)` lookarounds are stricter than `\b` for the hyphenated model numbers — `\bWH-1000XM5\b` matches at positions where `\b` straddles a hyphen, but `(?<!\w)WH-1000XM5(?!\w)` only fires when the model is flanked by non-word characters on both sides.

**Rule 2 — Variant token equality.** Product and listing must contain **exactly** the same subset of known variant discriminator words:

```python
_VARIANT_TOKENS = frozenset({
    "pro", "plus", "max", "mini", "ultra", "lite", "slim", "air",
    "digital", "disc",
    "se", "xl",
    "cellular", "wifi", "gps",
    "oled",
})

product_variants = product_tokens & _VARIANT_TOKENS
listing_variants = listing_tokens & _VARIANT_TOKENS
if product_variants != listing_variants:
    return 0.0
```

Rejects iPhone 16 → iPhone 16 Pro/Plus/Pro Max, iPad Pro → iPad Air, PS5 Slim Disc → PS5 Slim Digital Edition, Nintendo Switch → Switch OLED → Switch Lite.

**Rule 3 — Brand match.** If `product.brand` is known and non-empty, the cleaned brand (trailing `Inc/Corp/LLC/Ltd/Co` stripped) must appear (lowercase substring) in the listing title. Skipped if brand is unknown — Gemini-only resolution does not always populate brand.

**Rule 4 — Token overlap tiebreaker.** Tokenize both cleaned product name and listing title into lowercase alphanumeric tokens with `_STOPWORDS` removed and `len > 1`. Score is `|intersection| / |product_tokens|`. Below **0.4** returns 0.0; otherwise return the raw score.

### F.3 Regex pattern set (`_MODEL_PATTERNS`)

| # | Pattern | Matches | Notes |
|---|---|---|---|
| 1 | `[A-Z]{1,3}-?\d{1,2}-?\d{3,5}[A-Z]*\d*(?:/[A-Z0-9]+)?` | `WH-1000XM5`, `WH1000XM5/B`, `SM-G998`, `MDR-1A` | IGNORECASE; optional hyphen between letters and digits + trailing alpha/digit for XM5 |
| 2 | `\b(?:M[1-9]\d?\|Gen\s*\d+\|Series\s*[A-Z0-9]+\|v\d+)\b` | `M4`, `Gen 3`, `Series X`, `v2` | IGNORECASE; Apple Silicon + generation + version markers |
| 3 | `\b[A-Z][a-z]{2,8}\s+\d+[A-Z]?\b` | `Flip 6`, `Clip 5`, `Charge 4`, `Stick 4K`, `Dot 5` | **No IGNORECASE** — Title-case only, avoids matching prose like "with 2 microphones" |
| 4 | `\b[a-z][A-Z][a-z]{2,8}\s+\d+[A-Z]?\b` | `iPhone 16`, `iPad 12`, `iMac 24`, `eReader 3` | **No IGNORECASE** — camelCase starting with a lowercase letter |
| 5 | `\b[A-Z][a-z]+[A-Z][a-z]+\s+\d+[A-Z]?\b` | `AirPods 2`, `PlayStation 5`, `MacBook 14`, `PowerBeats 4` | **No IGNORECASE** — brand camelCase (two title-case segments joined, then digit) |

**Dropped from the hard gate (now only contribute via token overlap):** `256GB`, `1TB`, `27"`, `65-inch`, `11-inch`. These spec patterns were allowing `256GB` alone to satisfy `any()` and cleared the gate for iPhone SE listings on an iPhone 16 query. Specs are too weak to act as a model discriminator.

### F.4 `_pick_best_listing` flow

1. Filter `price > 0` (parse-failure guard — SP-7)
2. Score each listing via `_score_listing_relevance`
3. Drop listings scoring below 0.4
4. Prefer `is_available == True` over `is_available == False`
5. Return the cheapest survivor (or `(None, 0.0)` if nothing survives)

Retailers with zero survivors yield a `no_match` status (Appendix G) rather than a misleadingly cheap wrong product.

### F.5 Known limitations

- **Generation-without-digit.** ~~"Samsung Galaxy Buds Pro" (1st gen) has no digit in its name and matches any later "Galaxy Buds N Pro" via token overlap. Requires Gemini to emit an explicit `(1st gen)` tag.~~ **(Resolved in Step 2b-final — 2026-04-13.)** The Gemini system instruction now emits a `model` field like `"Galaxy Buds Pro (1st Gen)"` that is stored in `products.source_raw.gemini_model` and union'd into the scorer's token set. A new `_ORDINAL_TOKENS` frozenset (`{"1st", "2nd", …, "10th"}`) is checked for set-equality between product and listing (Rule 2b), so a product carrying `{1st}` rejects a listing with `{}` ordinals.
- **GPU SKUs.** ~~`RTX 4090` vs `RTX 4080` — no current pattern matches `\b[A-Z]{2,5}\s+\d{3,5}\b` (letter group + space + digit group).~~ **(Resolved in Step 2b-final — 2026-04-13.)** `_MODEL_PATTERNS[5]` added (letter group + space + digit group, e.g. `RTX 4090`, `GTX 1080`, `RX 7900`). Combined with the Gemini `model` field emitting the clean model identifier, the hard gate fires at the word-boundary-anchored regex and rejects `RTX 4080` listings for an `RTX 4090` product.
- **Pro vs Pro Max within the variant set.** Currently both are recognised as variants, and `{pro} != {pro, max}` does reject Pro Max for a Pro query — but only because both are in `_VARIANT_TOKENS`. If a new variant word isn't in the set, it won't participate in the equality check. **(Still load-bearing — extend `_VARIANT_TOKENS` when new variant words surface in the wild.)**

---

## Appendix G — Per-Retailer Status System (post-2b-val, 2026-04-12)

> **Step 2c update (2026-04-13):** `retailer_results` now arrives in two flavors. The batch endpoint `GET /api/v1/prices/{id}` still returns the full list in a single JSON body. The streaming endpoint `GET /api/v1/prices/{id}/stream` yields one `retailer_result` SSE event per retailer the moment it finishes (via `asyncio.as_completed`), each event carrying the same `{retailer_id, retailer_name, status}` shape plus an embedded `price` object on success. The streaming variant bypasses the classification loop's batch-at-the-end step — status is emitted inline as each retailer resolves, followed by a terminal `done` event with the aggregate counts. The rendering rules in G.5 are unchanged because `PriceComparison.retailerResults` is mutated in place on iOS as each event arrives.

Before this system, the `prices` list in `PriceComparisonResponse` was success-only: retailers that returned an error, returned no listings, or had all listings filtered by relevance were simply absent from the response. The iOS app showed only the retailers with prices, and the user had no way to know whether a missing retailer was offline, blocked, or genuinely carried nothing relevant.

### G.1 `retailer_results` field

`PriceComparisonResponse` gained a new field alongside `prices`:

```python
class RetailerStatus(str, Enum):
    SUCCESS = "success"          # matched a listing with a price
    NO_MATCH = "no_match"        # searched, no matching product
    UNAVAILABLE = "unavailable"  # couldn't search or couldn't parse response

class RetailerResult(BaseModel):
    retailer_id: str
    retailer_name: str
    status: RetailerStatus

class PriceComparisonResponse(BaseModel):
    product_id: uuid.UUID
    product_name: str
    prices: list[PriceResponse]              # success-only, sorted by price
    retailer_results: list[RetailerResult] = []   # all 11 retailers, with status
    total_retailers: int
    retailers_succeeded: int
    retailers_failed: int
    cached: bool
    fetched_at: datetime
```

`retailer_results` is sorted with successes first (alpha by retailer name), then `no_match`, then `unavailable`. The iOS side uses it to render all 11 retailers in the comparison view; missing retailers that carry the product show as a grayed-out row labeled "Not found", while offline/blocked retailers show as a grayed-out row labeled "Unavailable".

### G.2 Error-code to status classification

The service converts container error codes to statuses via `_classify_error_status`:

```python
_UNAVAILABLE_ERROR_CODES = frozenset({
    "CONNECTION_FAILED",  # container offline / network refused
    "GATHER_ERROR",        # asyncio.gather raised
    "HTTP_ERROR",          # 4xx/5xx from container
    "CLIENT_ERROR",        # local adapter code raised
    "CHALLENGE",           # PerimeterX / Cloudflare / anti-bot page detected
    "PARSE_ERROR",         # response received but couldn't be parsed
    "BOT_DETECTED",        # explicit bot flag from extract.js
    "TIMEOUT",             # request timed out
})

def _classify_error_status(code: str) -> str:
    return "unavailable" if code in _UNAVAILABLE_ERROR_CODES else "no_match"
```

**The critical design principle:** any error code that means "we never got usable search results" maps to `unavailable`, not `no_match`. A PerimeterX block is not the same as "Walmart doesn't carry this product" — Walmart never even searched for it. Lumping them would lie to the user. Only an empty-but-successful response (container returned listings but none cleared relevance, OR container returned an empty listings array) is `no_match`.

### G.3 `get_prices` integration

```python
for retailer_id, response in responses.items():
    retailer_name = all_retailer_names.get(retailer_id, retailer_id)

    if response.error is not None:
        status = _classify_error_status(response.error.code)
        failed += 1
        retailer_results.append({"retailer_id": retailer_id, "retailer_name": retailer_name, "status": status})
        continue

    if not response.listings:
        failed += 1
        retailer_results.append({"retailer_id": retailer_id, "retailer_name": retailer_name, "status": "no_match"})
        continue

    best_listing, relevance = self._pick_best_listing(response, product)
    if best_listing is None:
        failed += 1
        retailer_results.append({"retailer_id": retailer_id, "retailer_name": retailer_name, "status": "no_match"})
        continue

    succeeded += 1
    retailer_results.append({"retailer_id": retailer_id, "retailer_name": retailer_name, "status": "success"})
    # ... upsert price, append history, add to prices_data ...
```

### G.4 DB cache path

`_check_db_prices` only persists the success rows (the `prices` table has no concept of "failed attempt"), so when the DB cache path is taken, `retailer_results` is populated only with the known-good rows. The iOS side treats an absent entry as "not shown" and the result is the pre-G.1 behavior (only successful retailers visible). Redis caching preserves the full `retailer_results` list across hits.

### G.5 iOS rendering

`PriceComparisonView.retailerList` iterates over `comparison.retailerResults` and switches on the status:

```swift
switch row {
case .success(let retailerPrice):
    Button { openRetailerURL(retailerPrice.url) } label: {
        PriceRow(retailerPrice: retailerPrice)
    }
case .noMatch(let result):
    inactiveRow(name: result.retailerName, label: "Not found")
case .unavailable(let result):
    inactiveRow(name: result.retailerName, label: "Unavailable")
}
```

`inactiveRow` is a 0.6-opacity gray row with the retailer name on the left and the status label on the right; it is not tappable. Success rows that are the first in the sorted list still get the BEST BARKAIN badge.

Old cached responses that predate `retailer_results` decode gracefully via `decodeIfPresent ?? []` — when the list is empty, the view falls back to iterating only successful `viewModel.sortedPrices` (pre-G.1 behavior).

**Progressive stream rendering (Step 2c → Step 2c-fix).** The `PriceComparisonView` is driven by an `@Observable` `ScannerViewModel.priceComparison` that mutates in place as each SSE `retailer_result` event lands. `fetchPrices()` consumes `APIClient.streamPrices(...)` — an `AsyncThrowingStream<RetailerStreamEvent, Error>` backed by `URLSession.bytes(for:)` — and calls the `apply(_:for:)` helpers which lazy-seed a fresh `PriceComparison` on the first event and then splice each subsequent retailer result into the existing `prices` and `retailerResults` arrays. Each mutation invalidates the view, so the comparison list grows row-by-row as retailers complete: walmart (~12s) → amazon (~30s) → best_buy (~91s) under EC2 container workloads.

**Step 2c-fix note (2026-04-13):** the parser path changed from `URLSession.AsyncBytes.lines` to a manual byte-level splitter that iterates raw `UInt8`s from the underlying `AsyncSequence` and yields complete `\n`-terminated lines on the fly (CRLF tolerated). The `.lines` accessor was buffering aggressively for our ~200-byte-per-event SSE payloads — events that should have arrived seconds apart were instead held back until the connection closed, so `sawDone` in `ScannerViewModel.fetchPrices()` never flipped and every call fell through to `fallbackToBatch()`. The parser state machine (`SSEParser.feed(line:)` / `flush()`) is unchanged; only the byte-to-line layer was rewritten. The new `SSEParser.parse(bytes:)` static takes any `AsyncSequence<UInt8>` so unit tests can drive the splitter without a real URLSession, and the `com.barkain.app`/`SSE` os_log category emits a log line for every raw byte line, parsed event, decoded event, and fallback trigger — any future SSE regression is observable via `xcrun simctl spawn booted log stream --predicate 'subsystem == "com.barkain.app" AND category == "SSE"'`. See `docs/CHANGELOG.md` §Step 2c-fix for the full root-cause write-up and live verification traces.

---

## Appendix H — Carrier / Installment Filter (post-2b-val, 2026-04-12)

Walmart Wireless, Best Buy, and Amazon phone listings often show a monthly installment (e.g. `$45/mo`, `$20/mo with AT&T activation`) as the prominent price when the phone is carrier-locked. The listing title and URL identify the carrier. Rendering these as full-price comparisons is misleading — the user sees a $20 iPhone 16 and clicks through to find it's really $800+ over 36 months.

### H.1 Shared taxonomy

Carrier keywords (case-insensitive, match in title OR URL path):

```
AT&T, AT and T, Verizon, T-Mobile, Sprint, Cricket, Metro by, Boost Mobile,
Straight Talk, Tracfone, Xfinity Mobile, Visible, US Cellular,
Spectrum Mobile, Simple Mobile
```

Installment markers (match in listing title OR in the context text around a price):

```
$N/mo, $N / mo, /month, per month, monthly payment, monthly plan,
monthly cost, from $N/mo
```

A listing is rejected if **any** of those patterns match.

### H.2 Walmart — `_walmart_parser._is_carrier_listing`

`_walmart_parser.py` defines three regexes:

```python
_CARRIER_TITLE_MARKERS = re.compile(
    r"\b(?:AT\s*&\s*T|AT&T|Verizon|T-?Mobile|Sprint|Cricket|Metro\s*by|Boost\s*Mobile"
    r"|Straight\s*Talk|Tracfone|Xfinity\s*Mobile|Visible|US\s*Cellular|Spectrum\s*Mobile"
    r"|Simple\s*Mobile)\b",
    re.IGNORECASE,
)
_CARRIER_URL_MARKERS = re.compile(
    r"/(?:AT-?T|Verizon|T-?Mobile|Sprint|Cricket|Metro-?by|Boost-?Mobile|Straight-?Talk"
    r"|Tracfone|Xfinity-?Mobile|Visible|US-?Cellular|Spectrum-?Mobile|Simple-?Mobile)-",
    re.IGNORECASE,
)
_MONTHLY_PRICE_MARKERS = re.compile(
    r"\$[\d.,]+\s*/\s*mo\b|/\s*month\b|\bper\s*month\b|\bmonthly\s*payment\b",
    re.IGNORECASE,
)

def _is_carrier_listing(title: str, url: str) -> bool:
    if title and (_CARRIER_TITLE_MARKERS.search(title) or _MONTHLY_PRICE_MARKERS.search(title)):
        return True
    if url and _CARRIER_URL_MARKERS.search(url):
        return True
    return False
```

`extract_listings` calls `_is_carrier_listing(listing.title, listing.url)` in its per-item loop and skips matched items before the first-party filter runs.

### H.3 Best Buy — `extract.js` `isCarrierListing`

`containers/best_buy/extract.js` mirrors the Walmart logic in JS. The difference is that Best Buy has access to the full card innerText at extraction time, so the installment check can look at the rendered card body, not just the title:

```js
const CARRIER_TITLE_RE = /\b(?:AT\s*&\s*T|AT&T|Verizon|T-?Mobile|Sprint|Cricket|Metro\s*by|Boost\s*Mobile|Straight\s*Talk|Tracfone|Xfinity\s*Mobile|Visible|US\s*Cellular|Spectrum\s*Mobile|Simple\s*Mobile)\b/i;
const CARRIER_URL_RE = /\/(?:att|at-?t|verizon|t-?mobile|sprint|cricket|metro-?by|boost-?mobile|straight-?talk|tracfone|xfinity-?mobile|visible|us-?cellular|spectrum-?mobile|simple-?mobile)(?:-|\/)/i;
const MONTHLY_RE = /\$[\d,.]+\s*\/\s*mo\b|\/\s*month\b|\bper\s*month\b|\bmonthly\s+(?:payment|plan|cost)\b/i;

function isCarrierListing(title, url, cardText) {
  if (title && CARRIER_TITLE_RE.test(title)) return true;
  if (url && CARRIER_URL_RE.test(url)) return true;
  if (cardText && MONTHLY_RE.test(cardText)) return true;
  return false;
}
```

Cards that pass the filter then go through price extraction, which **also** strips `$X/mo` fragments from the card text before looking for dollar amounts:

```js
const priceSearchText = cardText.replace(/\$[\d,.]+\s*\/\s*mo\b[^\n]*/gi, ' ');
const priceMatch = priceSearchText.match(/\$[\d,]+\.\d{2}/);
```

This belt-and-suspenders approach handles the case where a non-carrier Best Buy listing happens to show a financing option as a secondary price.

### H.4 Amazon — `extract.js` `extractPrice` (Appendix E.4)

Amazon doesn't get a carrier-keyword filter because Amazon itself rarely brands carrier listings with AT&T / Verizon in the title — instead, they show the monthly as a prominent `.a-price` element with a `/mo` sibling in the same row. Appendix E.4's row-context installment check is sufficient.

### H.5 Test coverage

- `backend/tests/modules/test_walmart_firecrawl_adapter.py` — currently has fixtures for first-party vs third-party and challenge detection. **Does not yet have a carrier-filter fixture.** Add before the next major Walmart change.
- Best Buy `extract.js` changes are not covered by unit tests (the Best Buy container tests use respx mocks that don't exercise the JS evaluation path).
- Amazon `extract.js` installment handling is not covered by unit tests for the same reason.

All three are **live-validated** on real searches during the 2026-04-12 sim testing of the iPhone 16 and PS5 UPCs. Per Appendix D.4, adding real-API smoke tests to CI is the right long-term fix.
