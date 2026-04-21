# Barkain — Card Reward Optimization Reference

> Source: Competitive analysis (CardPointers, MaxRewards) + market research, April 2026
> Scope: Card catalog data model, rotating category calendars, portal rate tracking, user card matching, data sourcing strategy
> Last updated: April 3, 2026 (initial research)

---

## Purpose

This document defines how Barkain maintains an up-to-date card reward database and matches users to the optimal payment card at purchase time. It covers the data tiers, sourcing strategy, update cadences, the query-time matching algorithm, and the UX interstitial that surfaces the recommendation.

**Key insight:** CardPointers and MaxRewards answer *only* "which card?" — Barkain answers "which card + which retailer + which coupon + which identity discount + should you even buy now or wait?" The card recommendation is one layer in the nine-layer discount stack, not the whole product.

**Competitive landscape (as of April 2026):**
- **CardPointers** — 5,000+ cards from 900+ banks, auto-adds card-linked offers (Amex, Chase, BoA, Citi, Wells Fargo, US Bank), Safari/Chrome extension with Shopping Pointers bar, location-aware AutoPilot via Live Activities, recently added MCP integration for AI assistants. Apple-ecosystem focused, subscription model.
- **MaxRewards** — Links bank accounts via Plaid, auto-activates offers and quarterly bonuses, tracks spending/utilization/credit scores, "Best Card" feature per merchant/category. Cross-platform (iOS + Android), Gold tier ~$60/year.

Barkain does NOT need to replicate the auto-activation features of either app (logging into issuer accounts to click "add offer"). That requires maintaining auth flows with every issuer and handling 2FA — a massive engineering surface for a solo dev. Barkain's value is in the *recommendation synthesis*, not card portfolio management.

---

## Data Tiers

### Tier 1 — Static Card Catalog (changes quarterly or less)

Base earn rates, annual fees, card network, reward currency, point valuations. This is the foundation — every other tier builds on it.

**What to capture per card:**

| Field | Example (Chase Sapphire Preferred) | Update Frequency |
|-------|-------------------------------------|------------------|
| Card issuer | Chase | Never changes |
| Card product | Sapphire Preferred | Never changes |
| Card network | Visa | Never changes |
| Annual fee | $95 | Yearly (if ever) |
| Base reward rate | 1x | Rarely changes |
| Reward currency | Ultimate Rewards | Never changes |
| Point valuation (cents) | 1.25 cpp (portal), ~2.0 cpp (transfer) | Subjective, update quarterly |
| Static category bonuses | 3x dining, 3x online grocery, 2x travel, 5x Lyft | Product refresh (~yearly) |
| Has shopping portal | Yes (Shop Through Chase) | Rarely changes |

**Initial scope:** Seed the top ~30 cards that cover 80%+ of US cardholders. Only maintain cards that exist in your user base — track which cards users add during onboarding and prioritize those.

**Priority card list (seed data):**

Chase: Sapphire Preferred, Sapphire Reserve, Freedom Flex, Freedom Unlimited, Ink Business Preferred, Ink Business Cash, Ink Business Unlimited
Amex: Gold, Platinum, Blue Cash Preferred, Blue Cash Everyday, Green
Capital One: Venture X, Venture, SavorOne, Quicksilver
Citi: Double Cash, Custom Cash, Premier, Strata Premier
Discover: it Cash Back, it Miles
Bank of America: Customized Cash Rewards, Premium Rewards, Unlimited Cash Rewards
Wells Fargo: Autograph, Active Cash
US Bank: Altitude Go, Cash+, Shopper Cash Rewards

**Schema:** `card_reward_programs` table (already defined in SCRAPING_AGENT_ARCHITECTURE.md)

**Sourcing:** Manual entry from issuer websites for initial seed. This is a one-time effort (~2-3 hours for 30 cards). Updates are event-driven — monitor card product refreshes via The Points Guy, Doctor of Credit RSS feeds.

---

### Tier 2 — Rotating Bonus Categories (changes quarterly)

Cards like Chase Freedom Flex, Discover it Cash Back, Citi Dividend, and US Bank Cash+ offer elevated earn rates (typically 5-6%) on categories that change every quarter. This is the highest-impact data tier for Barkain because it directly affects which card wins at any given retailer.

**Known rotating category cards (Q2 2026 current data):**

| Card | Q2 2026 Categories | Cap | Activation |
|------|-------------------|-----|------------|
| Chase Freedom Flex | Amazon, Chase Travel, Feeding America | $1,500/quarter | Required |
| Discover it Cash Back | Restaurants, home improvement stores | $1,500/quarter | Required |
| Citi Dividend | (announced per quarter) | $1,500/quarter | Required |
| US Bank Cash+ | Choose 2 from: Amazon, Apple, Best Buy, Home Depot, Lowe's, Walmart, Target, etc. | $1,500/quarter (6%) | Required (user selects) |
| US Bank Shopper Cash Rewards | Choose 2 retailers (same list as Cash+) | $1,500/quarter (6%) | Required, $95 annual fee |
| Bank of America Customized Cash | Choose 1 category (gas, online shopping, dining, travel, drugstores, home improvement) | $2,500/quarter (3%) | User selects monthly |

**User-selected categories require special handling.** US Bank Cash+, US Bank Shopper Cash Rewards, and BofA Customized Cash let the user pick their own categories. Barkain must ask users with these cards what categories they selected:
- Store as a user-level override in `rotating_categories` or a `user_category_selections` junction table
- Prompt users at the start of each quarter: "What categories did you pick for your US Bank Cash+?"
- Default to showing "check your app" if the user hasn't reported their selection

**Data sources (primary → fallback):**

1. **Doctor of Credit quarterly roundup** (https://www.doctorofcredit.com) — Single consolidated post every quarter covering ALL rotating category cards with activation links and strategies. This is the single best source.
2. **Bankrate Discover/Chase calendar pages** — Dedicated per-card pages, updated reliably.
3. **Issuer websites directly** — Discover's cashback calendar page, Chase's category activation page. Note: Discover's own calendar page was returning errors as of April 2026 — use blog sources as primary.
4. **AwardWallet, Upgraded Points, FinanceBuzz** — Secondary confirmation sources.

**Scraping strategy:**

Categories are announced ~1 month before each quarter starts and do not change mid-quarter. This means:
- Run extraction **4 times per year** (March 1, June 1, September 1, December 1)
- Single Playwright script targeting Doctor of Credit's quarterly post
- Cross-validate against one additional source (Bankrate or issuer page)
- Store in `rotating_categories` table with `effective_from` / `effective_until` dates
- Slack alert to developer for manual review before data goes live

This is NOT a watchdog pattern — it's a simple quarterly cron job. The data is too infrequent and too critical to automate without human review.

**Category taxonomy normalization:**

Different issuers use different names for the same spending category. Barkain needs a canonical category list that maps issuer-specific terms:

| Barkain Canonical | Chase Terms | Discover Terms | Citi Terms |
|-------------------|-------------|----------------|------------|
| `restaurants` | Restaurants | Restaurants, full-service restaurants, cafes, cafeterias, fast-food, caterers | Restaurants |
| `groceries` | Grocery stores | Grocery stores, supermarkets, bakeries, meat lockers | Grocery stores |
| `gas_stations` | Gas stations | Gas stations, EV charging | Gas stations |
| `home_improvement` | Home improvement stores | Home improvement retail, building supply, hardware, paint, lumber, lawn/garden, floor covering, home furnishing, home appliance | Home improvement |
| `streaming` | Select streaming | Select streaming services (Netflix, Spotify, Apple TV, etc.) | Streaming |
| `amazon` | Amazon.com, Whole Foods | Amazon.com | Amazon |
| `wholesale_clubs` | Wholesale clubs | Wholesale clubs | Wholesale clubs |
| `drugstores` | Drugstores | Drugstores | Drugstores |
| `online_shopping` | Online shopping | PayPal | Online shopping |
| `travel` | Chase Travel | — | — |

Store as a `category_aliases` lookup table or JSONB mapping in the card program record.

**Schema:** `rotating_categories` table (already defined in SCRAPING_AGENT_ARCHITECTURE.md)

---

### Tier 3 — Shopping Portal Rates (changes daily to weekly)

Shopping portals (Rakuten, TopCashBack, Chase Shop Through Chase, Amex Rakuten, Capital One Shopping, BeFrugal, Mr. Rebates) offer additional cashback percentages when users click through to retailers via their portal before purchasing. These rates fluctuate frequently and spikes represent high-value alert opportunities.

**Priority portals for Phase 1:**

| Portal | Type | Rate Volatility | Scraping Difficulty |
|--------|------|-----------------|-------------------|
| Rakuten | Universal (any card) | Medium — rates change weekly, spikes during sales events | Low — static HTML rate pages |
| TopCashBack | Universal | Medium | Low |
| Chase Shop Through Chase | Card-specific (Chase cards only) | Low — rates fairly stable | Medium — may require auth |
| Capital One Shopping | Card-specific (Cap One cards only) | Low | Medium — browser extension data |
| BeFrugal | Universal | Medium | Low |

**Scraping strategy:**

Portal rate pages are mostly static HTML tables listing retailers and their current cashback percentages. This is a Playwright deterministic script pattern (no LLM needed):

- Run every 6 hours (aligns with standard cache TTL)
- For each portal, scrape the retailer rate listing page
- Diff against stored `portal_bonuses` table
- Flag spikes (current rate > 1.5x normal rate) via the `is_elevated` computed column
- Elevated rates feed into M9 (Notification Service) for push alerts

**Portal stacking rules:**

- Portal cashback stacks with card category bonuses (this is where the value compounds)
- Portal cashback stacks with identity discounts
- Portal cashback generally stacks with coupon codes
- User can only use ONE portal per purchase — Barkain recommends the highest-value one
- Card-specific portals (Chase, Amex) only work with that issuer's cards

**Example stacking scenario:**
> User buys a $500 TV at Samsung.com
> - Samsung military discount: 10% off → $450 base price
> - Rakuten cashback: 4% → $18 back
> - Chase Freedom Flex: 5% (if electronics is quarterly category) → $22.50 back
> - Total effective price: $409.50 (18.1% total savings)
>
> Without Barkain, user probably pays $500 with their default 1% card → $495 effective

**Schema:** `portal_bonuses` table (already defined in SCRAPING_AGENT_ARCHITECTURE.md)

---

### Tier 4 — Card-Linked Offers (DEFERRED — Phase 5+)

Card-linked offers (Amex Offers, Chase Offers, Citi Offers, BofA Deals) are personalized per cardholder. These are the offers that CardPointers and MaxRewards auto-activate.

**Why deferred:**
- Requires logging into user's issuer accounts (OAuth where available, screen scraping otherwise)
- Each issuer has different auth flows, 2FA requirements, and anti-bot measures
- Offers are personalized — what one user sees differs from another
- Maintaining these auth flows as a solo dev is unsustainable
- MaxRewards users report frequent sync failures and 2FA re-prompts even with their dedicated engineering team

**Phase 1-4 approach:** When the recommendation engine (M6) generates a card recommendation, append a note: "Check your [issuer] app for additional card-linked offers at [retailer]." This acknowledges the feature gap without promising automation.

**Phase 5+ approach options:**
1. **MCP integration** — CardPointers now exposes an MCP server. Explore partnership or data-sharing agreement.
2. **Browser extension** — Build a Barkain Safari extension that can detect and surface offers when users visit their issuer's offer page.
3. **User-reported offers** — Let users manually add offers they see, building a crowd-sourced offer database.

---

## Query-Time Card Matching Algorithm

This runs at purchase time when the user taps a product. Zero LLM cost — pure database queries.

```
INPUT: user_id, retailer_id, product_category, purchase_amount, current_date

FOR each card IN user's card portfolio:
    1. base_rate = card.base_reward_rate

    2. category_rate = MAX of:
       - card.static category bonus for product_category (if any)
       - card.rotating category bonus for product_category where
         effective_from <= current_date <= effective_until (if any)
       - If user-selected category card: check user_category_selections

    3. effective_earn_rate = MAX(base_rate, category_rate)

    4. Check spend cap:
       - If rotating category, check quarterly spend against cap_amount
       - If over cap, fall back to base_rate

    5. portal_bonus = best available portal bonus for retailer where:
       - Portal is universal OR portal matches card issuer
       - Rate is current (effective_from <= now <= effective_until)

    6. dollar_value = (purchase_amount * effective_earn_rate / 100)
                    + (purchase_amount * portal_bonus / 100)
       - Normalize points cards: multiply by point_value_cents / 100

    7. If activation_required AND user hasn't confirmed activation:
       - Flag in recommendation: "Make sure you've activated [category] on [card]"

RETURN card with highest dollar_value, with breakdown:
  - card_name, earn_rate, earn_amount, portal_name, portal_rate, portal_amount
  - total_cashback_value
  - activation_reminder (if applicable)
  - portal_instruction (if applicable): "Shop through [portal] first, then buy at [retailer]"
```

**Performance target:** < 50ms for the full card match query. This is achievable because:
- User's card portfolio is small (typically 3-8 cards)
- Rotating categories and portal bonuses are pre-cached in DB
- No external API calls at query time
- Simple SQL joins with indexed lookups

---

## UX: Purchase Interstitial Card Recommendation

**Status:** ✅ Shipped Step 3f (2026-04-21) — card block + activation reminder + Continue.  **Portal guidance row** (*"Open Rakuten first (3%)"* etc.) in the mock below is deferred to Step 3g alongside live portal-worker data; 3f's Continue button goes directly to the retailer's tagged affiliate URL.

When a user finds a product and taps to purchase, Barkain shows a card recommendation overlay before redirecting to the affiliate link.

**Screen flow:**

```
[Product Detail Screen]
  User taps "Buy at Best Buy — $499"
       ↓
[Card Recommendation Interstitial]
  ┌──────────────────────────────────────────┐
  │  💳 Use your Chase Freedom Flex           │
  │                                           │
  │  5% back this quarter (electronics)       │
  │  = $24.95 cashback                        │
  │                                           │
  │  + Shop through Rakuten first (3%)        │
  │  = $14.97 additional cashback             │
  │                                           │
  │  ─────────────────────────────────        │
  │  Total rewards: $39.92                    │
  │  vs. $4.99 with your default card (1%)    │
  │                                           │
  │  ⚠️ Make sure you activated Q2 categories │
  │                                           │
  │  [Open Rakuten →]  [Buy Direct →]         │
  └──────────────────────────────────────────┘
       ↓
[Redirect to affiliate link OR portal]
```

**Key UX decisions:**
- Show the dollar amount saved, not just the percentage — "$39.92 back" is more motivating than "7.98%"
- Compare against their worst card option to show the delta
- Portal instructions are passive guidance ("open Rakuten first") — Barkain cannot auto-route through third-party portals
- Activation reminder only shows if the winning card uses a rotating category with `activation_required = true`
- The interstitial resolves in milliseconds (SQL lookup, no LLM) — no loading spinner needed

**Integration with M12 (Affiliate Router):**
- The "Buy Direct" button routes through Barkain's affiliate link
- The "Open Rakuten" button opens the portal in Safari — Barkain doesn't get affiliate commission on portal purchases, but the user gets higher total value, which builds trust and retention
- Track whether users choose the portal or direct route for analytics

---

## Data Maintenance Cadence

| Data Tier | Source | Update Frequency | Method | Human Review |
|-----------|--------|-----------------|--------|-------------|
| Card catalog (Tier 1) | Issuer websites, TPG, DoC | Event-driven (product refreshes) | Manual entry | Always |
| Rotating categories (Tier 2) | Doctor of Credit quarterly roundup | 4x/year (1st of month before quarter) | Playwright cron + Slack alert | Always before publish |
| Portal rates (Tier 3) | Portal rate pages | Every 6 hours | Playwright batch job (deterministic) | Only on anomalies |
| Card-linked offers (Tier 4) | DEFERRED | — | — | — |

**Estimated maintenance burden:**
- Tier 1: ~1 hour/quarter (only when cards in your user base get product refreshes)
- Tier 2: ~30 min/quarter (review scraped data, approve, manually handle user-selected cards)
- Tier 3: Zero ongoing — fully automated with watchdog monitoring for script breakage
- Total: ~1.5 hours/quarter for a solo dev. Scales to ~4 hours/quarter at 100+ cards.

---

## Phase Mapping

| Phase | Card Rewards Deliverables |
|-------|--------------------------|
| Phase 2 | User card portfolio onboarding (M5): user selects cards from catalog, stores in `user_cards`. Seed `card_reward_programs` with top 30 cards. Seed `rotating_categories` with current + next quarter data. |
| Phase 3 | Card matching algorithm integrated into recommendation engine (M6). Purchase interstitial UI. Portal rate scraping pipeline (Tier 3) operational. Activation reminders in recommendations. |
| Phase 4 | Incentive spike detection from portal rate diffs → push notifications (M9). Quarterly category auto-refresh pipeline (Tier 2). User-selected category capture UI for US Bank Cash+, BofA Customized Cash. |
| Phase 5+ | Evaluate card-linked offer options (Tier 4). Expand card catalog based on user base composition. Explore CardPointers MCP partnership. |

---

## Schema Cross-Reference

All tables referenced in this document are defined in SCRAPING_AGENT_ARCHITECTURE.md:

- **`card_reward_programs`** — Static card catalog (Tier 1)
- **`rotating_categories`** — Quarterly bonus categories (Tier 2)
- **`portal_bonuses`** — Shopping portal rates (Tier 3)
- **`user_cards`** — User's card portfolio (links user to card_reward_programs)
- **`user_discount_profiles`** — User identity attributes (feeds into stacking with card rewards)

**Additional table needed (not yet in schema):**

```sql
-- USER CATEGORY SELECTIONS: For cards where user picks their own categories
CREATE TABLE user_category_selections (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             TEXT NOT NULL,
    card_program_id     UUID NOT NULL REFERENCES card_reward_programs(id),
    selected_categories TEXT[] NOT NULL,          -- ['amazon', 'best_buy'] or ['gas', 'online_shopping']
    effective_from      DATE NOT NULL,            -- quarter start
    effective_until     DATE NOT NULL,            -- quarter end
    created_at          TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (user_id, card_program_id, effective_from)
);
```

---

## Open Questions

1. **Point valuation philosophy:** Should Barkain use conservative cpp estimates (Chase UR = 1.25 cpp) or optimistic transfer partner valuations (Chase UR = 2.0 cpp)? Suggestion: let user set their own valuation preference (conservative/moderate/optimistic) and default to conservative.

2. **Welcome bonus tracking:** CardPointers and MaxRewards both track progress toward minimum spend for welcome bonuses. This is high-value for users but requires transaction data (Plaid integration or manual entry). Defer to Phase 5+ alongside Tier 4?

3. **Annual fee ROI:** Both competitors show whether a card's rewards justify its annual fee. This is a natural extension of the card catalog — calculate annual earned value vs. fee. Low effort, high perceived value. Consider for Phase 4.

4. **Card recommendation accuracy:** When a rotating category like "restaurants" matches but the specific merchant's MCC code doesn't qualify (e.g., a bakery inside a hotel), the recommendation could be wrong. Add a confidence indicator or disclaimer? "This category match is based on the retailer type — individual merchants may vary."
