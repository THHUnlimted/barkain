# Barkain — Data Model Reference

> Source: Architecture sessions + SCRAPING_AGENT_ARCHITECTURE.md schema + CARD_REWARDS.md, March–April 2026
> Scope: Full PostgreSQL schema, migration conventions, cache strategy, data flow
> Last updated: April 2026 (v2 — complete schema from all source docs, nurse/healthcare flags, is_preferred card, extraction_method column, receipt_items junction table)

---

## Persistence Strategy

**Primary database:** PostgreSQL 16 + TimescaleDB extension (AWS RDS in production, Docker locally)
**Cache:** Redis 7 (AWS ElastiCache in production, Docker locally)
**ORM:** SQLAlchemy 2.0 async
**Migrations:** Alembic (path: `infrastructure/migrations/`)
**Auth store:** Clerk (external — user_id is a TEXT reference, not a local auth table)

---

## Migration Conventions

- **Backward-compatible only** — no column drops, no table renames in production
- **Path:** `infrastructure/migrations/` (alembic.ini `script_location` points here)
- **TimescaleDB hypertables** created via raw SQL in migrations: `SELECT create_hypertable(...)`
- **Generated columns** (e.g., `is_elevated`, `confidence_score`) require PostgreSQL 12+ — safe with PG 16
- **Test database:** Docker PostgreSQL+TimescaleDB — NOT SQLite (TimescaleDB features require PostgreSQL)
- **retailer_id is TEXT (slug):** `'best_buy'`, `'amazon'`, `'ebay'` — human-readable foreign keys, not UUIDs

---

## Migration History

| # | Migration | Tables | Step |
|---|-----------|--------|------|
| — | Not started | — | — |

---

## Entity Relationship Overview

```
┌──────────┐     1:N     ┌──────────────┐     N:1     ┌───────────┐
│  users   │────────────▶│   receipts   │────────────▶│ retailers │
└──────────┘             └──────────────┘             └───────────┘
      │                        │ 1:N                       │
      │ 1:1                    ▼                           │ 1:N
      ▼                  ┌──────────────┐            ┌─────┴──────┐
┌─────────────────┐      │ receipt_items │            │   prices   │
│ user_discount   │      └──────────────┘            └────────────┘
│ _profiles       │            │ N:1                       │ N:1
└─────────────────┘            ▼                           ▼
      │                  ┌──────────────┐            ┌────────────┐
      │ 1:N              │   products   │◀───────────│price_history│
      ▼                  └──────────────┘            └────────────┘
┌──────────────┐               │ 1:N                 (TimescaleDB)
│  user_cards  │               ▼
└──────────────┘         ┌──────────────┐
      │ N:1              │   listings   │
      ▼                  └──────────────┘
┌─────────────────┐
│ card_reward     │◀──── rotating_categories (1:N)
│ _programs       │◀──── user_category_selections (N:M via user)
└─────────────────┘

┌───────────┐──── retailer_health (1:1)
│ retailers │──── discount_programs (1:N)
└───────────┘──── portal_bonuses (1:N)
      │           coupon_cache (1:N)
      │           watchdog_events (1:N)
      └────────── affiliate_clicks (1:N)
```

---

## Schema Definition

### Core Tables

```sql
-- ================================================================
-- USERS: Base user table (Clerk provides auth, this stores app data)
-- ================================================================
CREATE TABLE users (
    id                      TEXT PRIMARY KEY,             -- Clerk user_id (string)
    email                   TEXT,
    display_name            TEXT,
    subscription_tier       TEXT NOT NULL DEFAULT 'free',  -- 'free', 'pro'
    subscription_expires_at TIMESTAMPTZ,                  -- NULL = no active sub or free tier
    onboarding_completed    BOOLEAN DEFAULT false,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

-- ================================================================
-- RETAILERS: Master retailer registry
-- ================================================================
CREATE TABLE retailers (
    id                  TEXT PRIMARY KEY,          -- 'best_buy', 'amazon', 'ebay'
    display_name        TEXT NOT NULL,
    base_url            TEXT NOT NULL,
    logo_url            TEXT,
    extraction_method   TEXT NOT NULL,             -- 'api', 'keepa', 'agent_browser'
    supports_coupons    BOOLEAN DEFAULT false,
    supports_identity   BOOLEAN DEFAULT false,
    supports_portals    BOOLEAN DEFAULT false,
    is_active           BOOLEAN DEFAULT true,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ================================================================
-- PRODUCTS: Canonical product records resolved from UPC/ASIN
-- ================================================================
CREATE TABLE products (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    upc             TEXT UNIQUE,                  -- Universal Product Code (barcode)
    asin            TEXT,                          -- Amazon Standard Identification Number
    name            TEXT NOT NULL,
    brand           TEXT,
    category        TEXT,                          -- internal canonical category
    description     TEXT,
    image_url       TEXT,
    source          TEXT NOT NULL,                 -- 'gemini_upc', 'upcitemdb', 'manual', 'vision_ai'
    source_raw      JSONB,                         -- raw response from resolution source
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_products_upc ON products (upc) WHERE upc IS NOT NULL;
CREATE INDEX idx_products_asin ON products (asin) WHERE asin IS NOT NULL;
CREATE INDEX idx_products_category ON products (category) WHERE category IS NOT NULL;

-- ================================================================
-- PRICES: Current price per product per retailer (upserted on fetch)
-- ================================================================
CREATE TABLE prices (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      UUID NOT NULL REFERENCES products(id),
    retailer_id     TEXT NOT NULL REFERENCES retailers(id),
    price           NUMERIC NOT NULL,              -- current price in USD
    original_price  NUMERIC,                       -- list/MSRP price (if available)
    currency        TEXT NOT NULL DEFAULT 'USD',
    url             TEXT,                           -- direct product URL at retailer
    affiliate_url   TEXT,                           -- affiliate-tagged URL
    condition       TEXT NOT NULL DEFAULT 'new',    -- 'new', 'used', 'refurbished', 'open_box'
    is_available    BOOLEAN DEFAULT true,
    is_on_sale      BOOLEAN DEFAULT false,
    last_checked    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (product_id, retailer_id, condition)
);

CREATE INDEX idx_prices_product ON prices (product_id);
CREATE INDEX idx_prices_retailer ON prices (retailer_id);
CREATE INDEX idx_prices_last_checked ON prices (last_checked);

-- ================================================================
-- PRICE_HISTORY: Append-only historical prices (TimescaleDB hypertable)
-- ================================================================
CREATE TABLE price_history (
    time            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    product_id      UUID NOT NULL,                 -- no FK (hypertable performance)
    retailer_id     TEXT NOT NULL,                  -- no FK (hypertable performance)
    price           NUMERIC NOT NULL,
    original_price  NUMERIC,
    condition       TEXT NOT NULL DEFAULT 'new',
    is_available    BOOLEAN DEFAULT true,
    source          TEXT NOT NULL DEFAULT 'api'    -- 'api', 'agent_browser', 'keepa'
);

-- Convert to TimescaleDB hypertable (run as raw SQL in Alembic migration)
-- SELECT create_hypertable('price_history', 'time');
-- Note: FKs intentionally omitted — hypertables perform better without them at scale.
-- Application-level integrity enforced in the price ingestion service.

CREATE INDEX idx_price_history_product_time
    ON price_history (product_id, time DESC);
CREATE INDEX idx_price_history_retailer_time
    ON price_history (retailer_id, time DESC);
```

### Identity & Rewards Tables

```sql
-- ================================================================
-- USER DISCOUNT PROFILES: Boolean flags per identity group
-- ================================================================
CREATE TABLE user_discount_profiles (
    user_id             TEXT PRIMARY KEY REFERENCES users(id),
    -- Identity attributes
    is_military         BOOLEAN DEFAULT false,
    is_veteran          BOOLEAN DEFAULT false,
    is_student          BOOLEAN DEFAULT false,
    is_teacher          BOOLEAN DEFAULT false,
    is_first_responder  BOOLEAN DEFAULT false,
    is_nurse            BOOLEAN DEFAULT false,
    is_healthcare_worker BOOLEAN DEFAULT false,
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

-- ================================================================
-- DISCOUNT PROGRAMS: What discounts each retailer offers
-- ================================================================
CREATE TABLE discount_programs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    retailer_id         TEXT NOT NULL REFERENCES retailers(id),
    program_name        TEXT NOT NULL,           -- 'Military Discount', 'Student Deals'
    program_type        TEXT NOT NULL,
        -- 'identity', 'membership', 'portal', 'card_offer',
        -- 'category', 'coupon', 'loyalty', 'bundle', 'trade_in'

    eligibility_type    TEXT,
        -- 'military', 'veteran', 'student', 'teacher', 'first_responder',
        -- 'nurse', 'healthcare_worker', 'senior', 'aaa', 'aarp',
        -- 'employee_[company]', 'alumni_[school]', 'union_[name]',
        -- 'costco_member', 'prime_member', 'sams_member',
        -- 'card_[network]_[product]'

    -- Discount structure
    discount_type       TEXT NOT NULL,            -- 'percentage', 'fixed_amount', 'cashback_percentage',
                                                  -- 'points_multiplier', 'free_shipping', 'bogo', 'tiered'
    discount_value      NUMERIC,                  -- 10 = 10% or $10 depending on type
    discount_max_value  NUMERIC,                  -- cap (e.g., "up to $500 off")
    discount_details    TEXT,                      -- human-readable description

    -- Applicability
    applies_to_categories   TEXT[],               -- internal category IDs, NULL = all
    excluded_categories     TEXT[],
    excluded_brands         TEXT[],
    minimum_purchase        NUMERIC,
    stackable               BOOLEAN DEFAULT false,
    stacks_with             TEXT[],               -- program_types it stacks with

    -- Verification
    verification_method TEXT,
        -- 'id_me', 'sheer_id', 'wesalute', 'unidays', 'student_beans',
        -- 'manual_upload', 'email_domain', 'self_attestation',
        -- 'card_linked', 'membership_number', 'none'
    verification_url    TEXT,

    -- Metadata
    url                 TEXT,
    is_active           BOOLEAN DEFAULT true,
    last_verified       TIMESTAMPTZ,
    last_verified_by    TEXT,                     -- 'watchdog_batch', 'manual', 'probe_agent'
    effective_from      DATE,
    effective_until     DATE,                     -- NULL = ongoing
    notes               TEXT,

    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (retailer_id, program_name, eligibility_type)
);

CREATE INDEX idx_discount_programs_lookup
    ON discount_programs (retailer_id, program_type, is_active)
    WHERE is_active = true;

CREATE INDEX idx_discount_programs_eligibility
    ON discount_programs (eligibility_type, is_active)
    WHERE is_active = true;

-- ================================================================
-- CARD REWARD PROGRAMS: Static card catalog
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
    point_value_cents   NUMERIC,                  -- estimated cpp (1.25 for CSP, 2.0 for CSR)

    -- Category bonuses (static, non-rotating)
    category_bonuses    JSONB NOT NULL DEFAULT '[]',
    -- Example: [{"category": "dining", "rate": 3.0, "description": "3x on dining"}]

    -- Shopping portal
    has_shopping_portal     BOOLEAN DEFAULT false,
    portal_url              TEXT,
    portal_base_rate        NUMERIC,

    -- Annual fee (for ROI calculations)
    annual_fee              NUMERIC DEFAULT 0,

    is_active               BOOLEAN DEFAULT true,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

-- ================================================================
-- ROTATING CATEGORIES: Quarterly bonus categories
-- ================================================================
CREATE TABLE rotating_categories (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    card_program_id     UUID NOT NULL REFERENCES card_reward_programs(id),
    quarter             TEXT NOT NULL,            -- '2026-Q2', '2026-03' for monthly
    categories          TEXT[] NOT NULL,          -- ['groceries', 'gas_stations', 'amazon']
    bonus_rate          NUMERIC NOT NULL,         -- 5.0 = 5x/5%
    activation_required BOOLEAN DEFAULT true,
    activation_url      TEXT,
    cap_amount          NUMERIC,                  -- quarterly spend cap
    effective_from      DATE NOT NULL,
    effective_until     DATE NOT NULL,
    last_verified       TIMESTAMPTZ,

    UNIQUE (card_program_id, quarter)
);

-- ================================================================
-- USER CARDS: User's card portfolio
-- ================================================================
CREATE TABLE user_cards (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             TEXT NOT NULL REFERENCES users(id),
    card_program_id     UUID NOT NULL REFERENCES card_reward_programs(id),
    nickname            TEXT,                      -- user-friendly label
    is_preferred        BOOLEAN DEFAULT false,     -- user-set preferred card for comparisons
    is_active           BOOLEAN DEFAULT true,
    added_at            TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (user_id, card_program_id)
);

CREATE INDEX idx_user_cards_user ON user_cards (user_id) WHERE is_active = true;

-- ================================================================
-- USER CATEGORY SELECTIONS: For cards where user picks own categories
-- ================================================================
CREATE TABLE user_category_selections (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             TEXT NOT NULL REFERENCES users(id),
    card_program_id     UUID NOT NULL REFERENCES card_reward_programs(id),
    selected_categories TEXT[] NOT NULL,           -- ['amazon', 'best_buy'] or ['gas', 'online_shopping']
    effective_from      DATE NOT NULL,
    effective_until     DATE NOT NULL,
    created_at          TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (user_id, card_program_id, effective_from)
);

-- ================================================================
-- PORTAL BONUSES: Shopping portal cashback rates
-- ================================================================
CREATE TABLE portal_bonuses (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portal_source       TEXT NOT NULL,
        -- 'rakuten', 'topcashback', 'befrugal', 'chase_shop_through_chase',
        -- 'amex_rakuten', 'capital_one_shopping', 'mr_rebates'
    retailer_id         TEXT NOT NULL REFERENCES retailers(id),
    bonus_type          TEXT NOT NULL,             -- 'cashback_percentage', 'points_multiplier'
    bonus_value         NUMERIC NOT NULL,          -- e.g., 8.0 = 8% cashback
    normal_value        NUMERIC,                   -- baseline for spike detection
    is_elevated         BOOLEAN GENERATED ALWAYS AS (
        bonus_value > COALESCE(normal_value, 0) * 1.5
    ) STORED,
    effective_from      TIMESTAMPTZ NOT NULL,
    effective_until     TIMESTAMPTZ,
    last_verified       TIMESTAMPTZ,
    verified_by         TEXT,                      -- 'nightly_batch', 'probe_agent'

    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_portal_bonuses_active
    ON portal_bonuses (retailer_id, effective_until)
    WHERE effective_until IS NULL OR effective_until > NOW();
```

### Secondary Market & Coupons

```sql
-- ================================================================
-- LISTINGS: Secondary market listings (eBay used/refurb, BackMarket)
-- ================================================================
CREATE TABLE listings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      UUID NOT NULL REFERENCES products(id),
    retailer_id     TEXT NOT NULL REFERENCES retailers(id),
    external_id     TEXT,                          -- eBay listing ID, BackMarket ID
    title           TEXT NOT NULL,
    price           NUMERIC NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'USD',
    condition       TEXT NOT NULL,                  -- 'used_like_new', 'used_good', 'used_fair', 'refurbished', 'certified_refurbished'
    seller_name     TEXT,
    seller_rating   NUMERIC,                       -- 0-100 or 0-5 depending on platform
    seller_reviews  INTEGER,
    url             TEXT NOT NULL,
    image_url       TEXT,
    shipping_cost   NUMERIC,
    returns_accepted BOOLEAN,
    warranty_info   TEXT,
    listing_age_days INTEGER,                      -- how long the listing has been active
    quality_score   NUMERIC,                       -- AI-computed quality score (Phase 4)
    is_active       BOOLEAN DEFAULT true,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,                   -- cache expiry

    UNIQUE (retailer_id, external_id)
);

CREATE INDEX idx_listings_product ON listings (product_id, is_active)
    WHERE is_active = true;

-- ================================================================
-- COUPON CACHE: Known promo codes with validation status
-- ================================================================
CREATE TABLE coupon_cache (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    retailer_id         TEXT NOT NULL REFERENCES retailers(id),
    code                TEXT NOT NULL,
    description         TEXT,
    discount_type       TEXT NOT NULL,             -- 'percentage', 'fixed', 'free_shipping'
    discount_value      NUMERIC,
    minimum_purchase    NUMERIC,
    applies_to          TEXT[],                    -- category restrictions
    source              TEXT NOT NULL,             -- 'crawl_retailmenot', 'crawl_honey', 'user_submitted'

    validation_status   TEXT NOT NULL DEFAULT 'unvalidated',
        -- 'unvalidated', 'valid', 'invalid', 'expired', 'conditional'
    last_validated      TIMESTAMPTZ,
    validated_by        TEXT,                      -- 'coupon_agent', 'user_report'
    validation_notes    TEXT,
    success_count       INTEGER DEFAULT 0,
    failure_count       INTEGER DEFAULT 0,
    confidence_score    NUMERIC GENERATED ALWAYS AS (
        CASE WHEN (success_count + failure_count) = 0 THEN 0.5
        ELSE success_count::numeric / (success_count + failure_count)
        END
    ) STORED,

    discovered_at       TIMESTAMPTZ DEFAULT NOW(),
    expires_at          TIMESTAMPTZ,
    is_active           BOOLEAN DEFAULT true,

    UNIQUE (retailer_id, code)
);
```

### Receipts & Savings

```sql
-- ================================================================
-- RECEIPTS: Scanned receipt records
-- ================================================================
CREATE TABLE receipts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT NOT NULL REFERENCES users(id),
    retailer_id     TEXT REFERENCES retailers(id), -- NULL if unrecognized retailer
    store_name      TEXT,                          -- raw store name from OCR
    receipt_date    DATE,                          -- purchase date from receipt
    subtotal        NUMERIC,
    tax             NUMERIC,
    total           NUMERIC,
    currency        TEXT NOT NULL DEFAULT 'USD',
    ocr_text        TEXT,                          -- full OCR text (structured, not raw image)
    savings_amount  NUMERIC,                       -- calculated total savings vs. best alternatives
    scanned_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_receipts_user ON receipts (user_id, scanned_at DESC);

-- ================================================================
-- RECEIPT ITEMS: Line items from a receipt, linked to products
-- ================================================================
CREATE TABLE receipt_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    receipt_id      UUID NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    product_id      UUID REFERENCES products(id),  -- NULL if product unresolved
    item_name       TEXT NOT NULL,                  -- raw item name from OCR
    quantity        INTEGER DEFAULT 1,
    unit_price      NUMERIC NOT NULL,
    total_price     NUMERIC NOT NULL,
    best_alt_price  NUMERIC,                       -- best alternative price found
    best_alt_retailer TEXT,                         -- where the alternative was found
    savings         NUMERIC,                        -- unit_price - best_alt_price (per unit)
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_receipt_items_receipt ON receipt_items (receipt_id);
CREATE INDEX idx_receipt_items_product ON receipt_items (product_id)
    WHERE product_id IS NOT NULL;
```

### Tracking & Analytics

```sql
-- ================================================================
-- WATCHED ITEMS: Products user is tracking for price drops (Phase 4)
-- ================================================================
CREATE TABLE watched_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT NOT NULL REFERENCES users(id),
    product_id      UUID NOT NULL REFERENCES products(id),
    target_price    NUMERIC,                       -- alert when price drops below this
    watch_until     DATE,                          -- auto-expire tracking
    is_active       BOOLEAN DEFAULT true,
    last_notified   TIMESTAMPTZ,                   -- prevent notification spam
    created_at      TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (user_id, product_id)
);

CREATE INDEX idx_watched_items_active
    ON watched_items (product_id, is_active)
    WHERE is_active = true;

-- ================================================================
-- AFFILIATE CLICKS: Affiliate link tracking
-- ================================================================
CREATE TABLE affiliate_clicks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT NOT NULL REFERENCES users(id),
    product_id      UUID REFERENCES products(id),
    retailer_id     TEXT NOT NULL REFERENCES retailers(id),
    affiliate_network TEXT NOT NULL,               -- 'amazon_associates', 'ebay_partner', 'cj_affiliate'
    click_url       TEXT NOT NULL,
    clicked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    converted       BOOLEAN,                       -- NULL = unknown, true = sale, false = no sale
    commission      NUMERIC,                       -- commission earned (if known)
    conversion_at   TIMESTAMPTZ
);

CREATE INDEX idx_affiliate_clicks_user ON affiliate_clicks (user_id, clicked_at DESC);
CREATE INDEX idx_affiliate_clicks_retailer ON affiliate_clicks (retailer_id, clicked_at DESC);

-- ================================================================
-- PREDICTION CACHE: Cached price prediction results (Phase 4)
-- ================================================================
CREATE TABLE prediction_cache (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      UUID NOT NULL REFERENCES products(id),
    prediction_type TEXT NOT NULL,                  -- 'buy_wait', 'price_forecast'
    result          JSONB NOT NULL,                 -- prediction output
        -- Example: {"recommendation": "wait", "confidence": 0.78,
        --           "predicted_low": 399.99, "predicted_date": "2026-07-15",
        --           "reasoning": "Historical Prime Day pattern"}
    model_version   TEXT NOT NULL,                  -- Prophet model version
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,           -- when to recompute

    UNIQUE (product_id, prediction_type)
);

CREATE INDEX idx_prediction_cache_expiry
    ON prediction_cache (expires_at)
    WHERE expires_at > NOW();
```

### Scraper Infrastructure

```sql
-- ================================================================
-- RETAILER HEALTH: Denormalized health status for fast reads
-- ================================================================
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
    script_version          TEXT NOT NULL DEFAULT '0.0.0',
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ================================================================
-- WATCHDOG EVENTS: Audit log of every watchdog intervention
-- ================================================================
CREATE TABLE watchdog_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    retailer_id     TEXT NOT NULL REFERENCES retailers(id),
    event_type      TEXT NOT NULL,                  -- 'health_check', 'failure_alert', 'manual'
    diagnosis       TEXT NOT NULL,                  -- 'transient', 'selector_drift', 'layout_redesign', 'blocked'
    action_taken    TEXT NOT NULL,                  -- 'retry', 'rediscover', 'escalate', 'disable'
    success         BOOLEAN NOT NULL,
    old_selectors   JSONB,
    new_selectors   JSONB,
    llm_model       TEXT,                          -- 'claude_opus', etc.
    llm_tokens_used INTEGER,
    error_details   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_watchdog_retailer_time
    ON watchdog_events (retailer_id, created_at DESC);
```

---

## Table Inventory

| Table | Purpose | Phase | Rows at Scale |
|-------|---------|-------|---------------|
| users | App user accounts (Clerk user_id) | 1 | 10K+ |
| retailers | Master retailer registry | 1 | 15 |
| products | Canonical product records | 1 | 100K+ |
| prices | Current price per product per retailer | 1 | 500K+ |
| price_history | Historical prices (TimescaleDB hypertable) | 1 | Millions |
| user_discount_profiles | User identity flags | 2 | = users |
| discount_programs | Retailer discount programs | 2 | ~200 |
| card_reward_programs | Credit card catalog | 2 | ~30 (seed), ~100+ |
| rotating_categories | Quarterly bonus categories | 2 | ~20/quarter |
| user_cards | User's card portfolio | 2 | ~3-8 per user |
| user_category_selections | User-picked card categories | 2 | Small |
| portal_bonuses | Shopping portal cashback rates | 3 | ~200 |
| coupon_cache | Promo codes with validation | 3 | ~5K |
| listings | Secondary market listings | 2 | 50K+ |
| receipts | Scanned receipt records | 3 | ~10 per user |
| receipt_items | Receipt line items → products | 3 | ~50 per user |
| watched_items | Products user is tracking | 4 | ~5 per user |
| affiliate_clicks | Affiliate link tracking | 2 | High volume |
| prediction_cache | Cached price predictions | 4 | = products |
| retailer_health | Scraper health status | 2 | = retailers |
| watchdog_events | Watchdog audit log | 2 | ~100/month |

---

## Cache Strategy

| Data | Cache Layer | TTL | Eviction |
|------|------------|-----|----------|
| Product resolution (UPC → product) | Redis | 24 hours | LRU |
| Retail prices (per product per retailer) | Redis | 6 hours | LRU |
| Secondary market listings | Redis | 30 minutes | LRU |
| Card matching results | None (< 50ms SQL) | — | — |
| Portal bonuses | PostgreSQL only | Updated every 6hr by worker | — |
| Discount programs | PostgreSQL only | Verified weekly by worker | — |

---

## Data Rules

- All `TIMESTAMPTZ` fields stored in UTC
- UUIDs generated server-side via `gen_random_uuid()` (PostgreSQL native)
- `user_id` is always Clerk's string ID — never internally generated
- `retailer_id` is TEXT slug — human-readable, not UUID
- Soft delete via `is_active` flag where data should be retained
- `updated_at` set on every mutation
- No optional fields unless the data genuinely can be absent
- JSONB used sparingly — only for `category_bonuses` (variable structure) and `prediction_cache.result`
