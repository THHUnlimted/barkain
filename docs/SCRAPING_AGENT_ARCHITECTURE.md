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
# Method: agent-browser scripts (deterministic, no LLM)
# Updates: portal_bonuses table
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
# Method: Mix of agent-browser (for known pages) + probe agents (for dynamic ones)
# Updates: discount_programs.last_verified
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
