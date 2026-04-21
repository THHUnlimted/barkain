# Barkain — Identity Discount Catalog Reference

> Source: Market research, April 2026
> Scope: Identity groups, retailer/brand discount programs, verification platforms, catalog maintenance strategy
> Last updated: April 2, 2026 (initial research)

---

## Purpose

This document is the seed data reference for Barkain's `discount_programs`, `discount_catalog`, and identity-matching infrastructure. It maps which identity groups unlock discounts at which retailers/brands, the discount amount, verification method, and known restrictions. This data populates the M5 (Identity Profile) module and feeds into the zero-LLM query-time matching system.

**Key insight:** No competitor combines identity discount discovery with price comparison. Honey finds coupon codes. Rakuten finds cashback. CardPointers finds card rewards. Barkain is the only tool that knows a user is a veteran AND a student AND holds a Chase Sapphire — and can synthesize all three against real-time pricing.

---

## Identity Groups (Onboarding Capture Priority)

Ordered by breadth of available discounts and savings potential. These are the groups Barkain asks about during user onboarding.

### Tier 1 — High Coverage, High Savings

| Group | Est. US Population | Avg. Discount Range | Top Categories |
|-------|-------------------|---------------------|----------------|
| Military (active duty) | ~1.3M | 10–30% | Electronics, home improvement, apparel, travel |
| Veterans | ~18M | 10–30% | Electronics, home improvement, apparel, travel |
| Military spouses/family | ~2M+ | 10–30% | Same as military (most programs extend to household) |
| Students (college) | ~20M | 10–40% | Electronics, software, apparel, streaming |
| Teachers/Educators | ~3.7M | 10–40% | Electronics, software, apparel, office supplies |

### Tier 2 — Moderate Coverage, Strong Savings in Select Categories

| Group | Est. US Population | Avg. Discount Range | Top Categories |
|-------|-------------------|---------------------|----------------|
| First responders (fire/EMS/police) | ~3.5M | 10–20% | Electronics, apparel, home improvement |
| Nurses | ~4.7M | 10–20% | Electronics, apparel, wellness |
| Healthcare workers (non-nurse) | ~10M+ | 10–20% | Electronics, apparel |
| Government employees | ~22M (fed+state+local) | 5–30% | Electronics, software, travel |
| Seniors (50+ / 55+ / 62+) | ~110M (50+) | 5–15% | Electronics, travel, groceries, telecom |

### Tier 3 — Niche but Valuable

| Group | Avg. Discount Range | Notes |
|-------|---------------------|-------|
| AAA members | 5–20% | Travel, auto, select retail |
| AARP members | 5–25% | Travel, telecom, insurance, retail |
| Union members | Varies | Employer-specific programs |
| Alumni (specific schools) | Varies | Limited, school-dependent |
| Costco / Sam's / BJ's members | Member pricing | Warehouse-specific pricing |
| Amazon Prime members | Prime pricing | Exclusive deals + free shipping |

---

## Student & Young Adult Tech — US Item-Focused Programs

Barkain's student and young-adult audience skews heavily toward tech purchases (laptops, phones, tablets, peripherals). This table catalogs **US-available, item-focused brand programs** verifiable via ID.me, SheerID, UNiDAYS, or direct-brand `.edu` check. Streaming and SaaS programs (Spotify, Apple Music, YouTube Premium, Adobe CC, Microsoft 365 Edu, Autodesk Education) are deliberately excluded — Barkain's scope is physical items. Recent grads within 3–5 years of graduation should toggle `is_student=true`: UNiDAYS GRADLiFE (3 yr post-grad) and Student Beans GradBeans (5 yr post-grad) both operate as extended-student programs, and the catalog treats them under the existing `is_student` axis. A dedicated `is_recent_grad` flag is reserved for a future migration if demand surfaces.

### Student Tech Programs (US)

| Brand | Program | Discount | Verification | URL | Item Category | Stacking |
|-------|---------|----------|--------------|-----|---------------|----------|
| Apple | Apple Education (Student) | Flat $50–$100 off Mac/iPad; free AirPods with Mac during Back-to-School | UNiDAYS or Apple .edu check | apple.com/us-hed/shop | Macs, iPads, accessories | Cannot stack with Apple military or other Apple promos |
| Samsung | Samsung Student | Up to 30 % off Galaxy phones, tablets, laptops | UNiDAYS | samsung.com/us/shop/offer-program/students/ | Phones, tablets, laptops | Per-product sale-price rules apply; TOS restricts external price sharing |
| HP | HP Education | Up to 35 % off laptops, desktops, accessories | ID.me | hp.com/us-en/shop/cv/hp-education | Laptops, desktops, printers, accessories | Cannot stack with HP Frontline Heroes (healthcare) |
| Dell | Dell University | 10 % off laptops + accessories (student tier) | Dell Advantage .edu | dell.com/en-us/lp/student | Laptops, monitors, peripherals | Stacks with some sale pricing, check per-SKU |
| Lenovo | Lenovo Student | Up to 5 % off (stacks with select sale SKUs) | Direct .edu | lenovo.com/us/en/d/deals/student/ | Laptops, ThinkPads, accessories | Stackable with select sales |
| Microsoft | Microsoft Education (Surface) | 10 % off Surface devices | Direct .edu / ID.me | microsoft.com/en-us/store/b/education | Surface laptops, tablets, accessories | Cannot stack with Microsoft military |
| Acer | Acer Education Store | 10 % off laptops | Direct .edu | store.acer.com/en-us/education | Laptops, Chromebooks | Per-SKU exclusions |
| ASUS | ASUS Education | Up to 10 % off laptops, ROG gear | Direct .edu | store.asus.com/us/b2b/education | Laptops, ROG gaming gear | — |
| Razer | Razer Educate | Up to 15 % off peripherals, laptops | Direct .edu | razer.com/landingpg/education | Peripherals, gaming laptops, headsets | Cannot stack with Razer sale pricing |
| Logitech | Logitech Education | Varies by SKU (typically 10–20 %) | Direct .edu | logitech.com/en-us/promotions/education.html | Peripherals, webcams, headsets | — |

### Young Adult (18–24) Programs

| Brand | Program | Discount | Verification | URL | Notes |
|-------|---------|----------|--------------|-----|-------|
| Amazon | Prime Young Adult | 6-mo free trial, then 50 % off Prime ($7.49/mo) | Age verification (not student) | amazon.com/amazon-prime-young-adult | Distinct from Prime Student. Does NOT require .edu. Does NOT stack with Prime Student — user picks one. **Membership-fee scope** (`discount_programs.scope = 'membership_fee'`), so Barkain surfaces the program but never claims a per-product dollar savings figure — mirrors the 3f-hotfix treatment of Prime Student. |

### Aggregator notes

- **UNiDAYS US** (`myunidays.com/US/en-US`) and **Student Beans US** (`studentbeans.com/us`) are the US regional subdomains. Scrape only these paths for US-specific brand percentages.
- **GRADLiFE** (UNiDAYS, 3 yr post-grad) and **GradBeans** (Student Beans, 5 yr post-grad) extend student discount access. Barkain policy: `is_student=true` covers both current students and eligible recent grads; a dedicated `is_recent_grad` flag is reserved for a future migration.
- **Employer-perks platforms** (PerkSpot, BenefitHub, Abenity, Perks at Work, Fond, LifeMart, Love My Credit Union Rewards) are OUT OF SCOPE for this expansion — they require a dedicated scraper step with up-front auth-gate percentage analysis.

---

## Phase 1 Retailers — Identity Discount Matrix

### Best Buy

| Group | Discount | Verified? | Notes |
|-------|----------|-----------|-------|
| Military/Veterans | **None** (discontinued) | — | Was 10%, removed ~2023. Store manager discretion only, inconsistent. |
| Students | Student Deals hub | No formal verification | Weekly rotating deals via Best Buy Student Hub signup. Not a flat %. Savings of $10–$200 on select items. |
| First Responders | **None** confirmed | — | No official corporate program as of March 2026. |
| Seniors | **None** | — | Replaced identity discounts with My Best Buy membership tiers. |
| My Best Buy Plus ($49.99/yr) | Exclusive pricing, 60-day returns | Membership | Best Buy's replacement for identity discounts. |
| My Best Buy Total ($179.99/yr) | Plus benefits + Geek Squad | Membership | Premium tier. |

**Barkain opportunity:** Best Buy's lack of identity discounts makes it the perfect "redirect" retailer — show Best Buy's price, then highlight that the same product is cheaper at Samsung.com (30% military) or Apple.com (10% military).

### Amazon (via Keepa)

| Group | Discount | Verified? | Notes |
|-------|----------|-----------|-------|
| Students | Prime Student: 6-mo free trial, then $7.49/mo (50% off Prime) | .edu email | Also includes GrubHub+, other perks. |
| Military/Veterans | **None** standard | — | No year-round military pricing. Occasional Veterans Day deals. |
| EBT/Medicaid holders | Prime Access: $6.99/mo | Government ID verification | Reduced-price Prime membership. |
| All users | Subscribe & Save: 5–15% off | — | Not identity-based but worth flagging. |

**Barkain opportunity:** Amazon's identity discount surface area is small. Value-add here is price comparison + card reward optimization + portal bonus stacking.

### eBay

| Group | Discount | Notes |
|-------|----------|-------|
| All groups | **None** | eBay doesn't offer identity-based discounts. Secondary market — value is in price comparison against retail. |

**Barkain opportunity:** eBay listings provide the "used/refurbished" price floor that Barkain compares against retail identity-discounted prices.

---

## Priority Brands — Direct-to-Consumer Identity Discounts

These are brands where Barkain can redirect users from a retailer (like Best Buy) to the brand's own store for a better identity-discounted price.

### Apple

| Group | Discount | Verification | URL | Restrictions |
|-------|----------|-------------|-----|-------------|
| Military/Veterans | 10% off most products + accessories | ID.me | apple.com/shop/browse/home/veterans_military | Annual purchase limits per category. Cannot combine with education pricing. Household family eligible. |
| First Responders | 10% off | ID.me | Same portal | Same restrictions as military. |
| Students/Educators | Education pricing (varies, ~5–10%) | UNiDAYS or .edu | apple.com/us-hed/shop | Separate store. Back-to-school seasonal promo adds gift card bonus. |
| Government | Education-equivalent pricing | Employer verification | — | Through institutional purchasing. |

**Key nuance:** Military and education discounts cannot be stacked. User should compare which gives the better price on the specific product. Barkain can automate this comparison.

### Samsung

| Group | Discount | Verification | URL | Restrictions |
|-------|----------|-------------|-----|-------------|
| Military/Veterans | Up to 30% off | WeSalute or ID.me or .mil email | samsung.com/us/shop/offer-program/military | 2 products per category per calendar year. |
| First Responders | Up to 30% off | ID.me | samsung.com/us/shop/offer-program | Same purchase limits. |
| Students | Up to 30% off | ID.me or .edu email | samsung.com/us/shop/offer-program | Same purchase limits. |
| Teachers | Up to 30% off | ID.me | samsung.com/us/shop/offer-program | Same purchase limits. |
| Government | Up to 30% off | ID.me or .gov email | samsung.com/us/shop/offer-program | Same purchase limits. |
| Nurses/Medical | Up to 30% off | ID.me | samsung.com/us/shop/offer-program | Same purchase limits. |
| Employees (partner companies) | Up to 30% off | Company email | samsung.com/us/shop/offer-program | Company must be enrolled. |

**Key nuance:** Samsung's program is the most aggressive in electronics — up to 30% across almost ALL identity groups. This is the single highest-value redirect Barkain can offer. A $1,500 Samsung TV at Best Buy (no identity discount) → $1,050 at Samsung.com with military verification = $450 saved.

### HP

| Group | Discount | Verification | URL | Restrictions |
|-------|----------|-------------|-----|-------------|
| Military/Veterans + Family | Up to 40% off select products | ID.me | hp.com/us-en/shop/cv/hp-frontline-heroes | Via "Frontline Heroes" store. Not a flat percentage — varies by product. Free shipping included. |
| First Responders | Up to 40% off | ID.me | Same as above | Same program. |
| Nurses/Doctors/Hospital staff | Up to 55% off (per ID.me listing) | ID.me | Same as above | Highest discount tier in this program. |
| Healthcare workers | Up to 55% off | ID.me | Same as above | Same as nurses. |
| Students/Teachers | Up to 40% off | .edu email | hp.com/us-en/shop/cv/hp-education | Separate "Education Store" portal. |

**Key nuance:** HP's discounts are the highest percentage in electronics (up to 55% for healthcare workers), but they're product-specific, not a flat rate. The actual savings vary significantly by SKU — some products are barely discounted while others are deeply cut.

### Dell

| Group | Discount | Verification | URL | Restrictions |
|-------|----------|-------------|-----|-------------|
| Military/Veterans + Family | Extra 5% off | WeSalute+ subscription | dell.com military store | Requires WeSalute+ membership (was free, may now be paid). |
| Students | Varies (education pricing) | .edu email or StudentBeans | dell.com/en-us/lp/student | Dell University program. |
| Government | Member Purchase Program (MPP) pricing | Employer email | — | Up to 30% on select products via institutional program. |

**Key nuance:** Dell's identity discount (5% military) is lower than competitors, but their Member Purchase Program for government employees can be up to 30%. Worth checking for government users.

### Lenovo

| Group | Discount | Verification | URL | Restrictions |
|-------|----------|-------------|-----|-------------|
| Military/Veterans + Family | Sitewide discounts (varies) | ID.me | lenovo.com discount programs | Not a published flat %. |
| First Responders | Extra 5% off sitewide | ID.me | lenovo.com/us/en/landingpage/first-responder-discount | Published as 5% extra. |
| Students | Varies | ID.me or .edu | lenovo.com education store | |
| Teachers | Varies | ID.me | Same as students | |
| Seniors (50+) | Additional savings on ThinkPad | ID.me | lenovo.com discount programs | Targeted at fixed-budget buyers. |

### Microsoft

| Group | Discount | Verification | URL | Restrictions |
|-------|----------|-------------|-----|-------------|
| Military/Veterans + Family | 10% off select products | ID.me | microsoft.com/en-us/store/b/military | Cannot combine with education or seasonal discounts. |
| Students/Parents/Faculty (K-12 + Higher Ed) | 10% off select products | SheerID or .edu | microsoft.com/en-us/store/b/education | Cannot combine with military discount. |
| Active Duty (via Exchange) | 30% off Microsoft 365 Family | Military Exchange | shopMyExchange.com | Exchange-specific deal, not available to veterans. |

**Key nuance:** Microsoft discounts don't stack. Military and student discounts are 10% each, so users should compare which program offers a better final price on their specific product.

### Sony

| Group | Discount | Verification | URL | Restrictions |
|-------|----------|-------------|-----|-------------|
| Military | 10% off electronics (TVs, headphones, cameras, consoles) | ID.me | sony.com (via cart verification) | Applied at cart/checkout after ID.me verification. |
| Students/Educators | Up to 10% off | ID.me | Same as above | Same program, same verification flow. |
| First Responders/Nurses/Medical | 10% off | ID.me | Same as above | Same program. |

### LG

| Group | Discount | Verification | URL | Restrictions |
|-------|----------|-------------|-----|-------------|
| Military/Veterans | Up to 40% off select appliances; minimum 10% additional savings from sale prices | ID.me | lg.com/us/appreciation-program | "LG Appreciation Program" — one program for all groups. |
| First Responders | Same | ID.me | Same | |
| Students | Same | ID.me | Same | |
| Teachers | Same | ID.me | Same | |
| Nurses/Healthcare | Same | ID.me | Same | |
| Government | Same | ID.me | Same | |

---

## Home Improvement Brands (High-Value Category)

### Home Depot

| Group | Discount | Verification | URL | Restrictions |
|-------|----------|-------------|-----|-------------|
| Military/Veterans + Spouses | 10% off eligible items | SheerID (via Home Depot app) | homedepot.com/c/military | **$400 annual discount cap.** Must register digitally — DD-214 or physical ID at register no longer accepted. Expanded May 2025 to include tax-free shopping via military exchanges on 2M+ products. |
| Students | **None** | — | — | |
| First Responders | **None** standard | — | — | |

### Lowe's

| Group | Discount | Verification | URL | Restrictions |
|-------|----------|-------------|-----|-------------|
| Military/Veterans + Spouses | 10% off eligible full-price items | ID.me (via MyLowe's account) | lowes.com/l/about/honor-our-military | **$400 annual cap.** Applies to most full-price products. Cannot combine with sale pricing, Lowe's credit 5% discount, or other promos. Free Silver Key status upgrade included. In-store only (online discount discontinued). |
| Students | **None** | — | — | |
| First Responders | **None** standard | — | — | |

---

## Verification Platform Registry

These are the platforms retailers use to verify identity. Barkain maps each retailer to its verification platform to inform the user what they need.

### ID.me (Most Common)

| Attribute | Value |
|-----------|-------|
| Coverage | 5,000+ brands, 600+ direct store partnerships |
| Groups verified | Military, veterans, first responders, nurses, medical providers, students, teachers, government, seniors |
| User experience | One-time verification, then sign-in. Browser extension available. |
| Cost to consumer | Free |
| Data source for Barkain | shop.id.me directory pages are scrapeable (brand pages list discount % and eligible groups) |
| Brands using ID.me | Apple, Samsung, HP, Lenovo, Sony, LG, Under Armour, Nike, Lowe's, T-Mobile, Verizon |

### SheerID

| Attribute | Value |
|-----------|-------|
| Coverage | Hundreds of brands |
| Groups verified | Military, students, teachers, first responders, healthcare, seniors |
| User experience | Instant verification embedded in retailer checkout flow. No consumer account needed. |
| Cost to consumer | Free |
| Data source for Barkain | Partner brands listed in press releases and directory; consumer-facing offers page. Trusted by Amazon, Home Depot, Spotify, T-Mobile. |
| Brands using SheerID | Home Depot, Amazon (select programs), Spotify, Microsoft, Dickies, Ariat |

### WeSalute (formerly Veterans Advantage)

| Attribute | Value |
|-----------|-------|
| Coverage | Focused on military/veteran community |
| Groups verified | Active duty, veterans, retirees, Guard/Reserve, family |
| User experience | WeSalute+ membership (may have free/paid tiers). |
| Data source for Barkain | wesalute.com partner directory |
| Brands using WeSalute | Samsung, Dell, Acer |

### GovX

| Attribute | Value |
|-----------|-------|
| Coverage | 1,000+ brands, 7M+ verified members |
| Groups verified | Military, government, law enforcement, firefighters, first responders |
| User experience | GovX is a standalone ecommerce marketplace — users buy through GovX.com, not through the brand's site. |
| Discount range | Up to 50–65% off retail |
| Category strength | Outdoor recreation (avg 35% off), tactical gear (avg 30% off), event tickets (avg 25% off) |
| Data source for Barkain | govx.com/brands/all directory; individual brand pages |
| Key brands | Oakley, Under Armour, Garmin, Ray-Ban |

### UNiDAYS

| Attribute | Value |
|-----------|-------|
| Coverage | Student-focused |
| Groups verified | Students only |
| Data source for Barkain | myunidays.com brand directory |
| Brands using UNiDAYS | Apple (education store), ASOS, Samsung, Nike, Adidas |

### StudentBeans

| Attribute | Value |
|-----------|-------|
| Coverage | Student-focused |
| Groups verified | Students only |
| Data source for Barkain | studentbeans.com brand directory |
| Brands using StudentBeans | Dell, ASOS, Boohoo, various apparel |

---

## Identity Group × Category Savings Matrix

Quick reference: which identity group saves the most in which product category.

| Category | Best Group | Best Brand(s) | Max Discount | Notes |
|----------|-----------|---------------|-------------|-------|
| Smartphones | Military/Veteran | Samsung | Up to 30% | Apple 10%, Samsung up to 30% |
| Laptops | Healthcare workers | HP | Up to 55% | HP Frontline Heroes. Samsung up to 30%. |
| TVs | Military | Samsung, LG | 30–46% off | Samsung up to 30%. LG up to 46% off OLEDs. |
| Desktops | Healthcare workers | HP | Up to 55% | Dell 5% (weaker). Lenovo varies. |
| Tablets | Military/Veteran | Samsung, Apple | 10–30% | Samsung up to 30%, Apple 10% |
| Headphones/Audio | Military | Sony | 10% | Sony 10% across groups |
| Gaming Consoles | Military | Sony | 10% | Sony 10% on consoles + accessories |
| Home Appliances | Military | LG, Samsung | 30–46% off | LG up to 40-46%. Samsung up to 30%. Home Depot/Lowe's 10% (capped at $400/yr). |
| Home Improvement | Military/Veteran | Home Depot, Lowe's | 10% | $400/yr cap at both. Tax-free via exchange at HD. |
| Software | Students | Microsoft | 10% (or free Office 365 Edu) | Microsoft 10% or free Office for .edu. Adobe 60%+ off Creative Cloud for students. |

---

## Catalog Maintenance Strategy

### Initial Seeding (Phase 1)

1. **Manual entry** from this document for Phase 1 retailers (Best Buy, Amazon/Keepa, eBay) and priority DTC brands (Apple, Samsung, HP, Dell, Lenovo, Microsoft, Sony, LG)
2. **Scrape verification platform directories** for structured data:
   - `shop.id.me/military` → all military-eligible brands with discount %
   - `shop.id.me/students` → all student-eligible brands
   - `shop.id.me/first-responders` → all first responder brands
   - `govx.com/brands/all` → all GovX partner brands
   - `wesalute.com` partner directory
   - `myunidays.com` brand directory
   - `studentbeans.com` brand directory
3. **Populate `discount_programs` table** with structured records per SCRAPING_AGENT_ARCHITECTURE.md schema

### Ongoing Maintenance (Nightly/Weekly Batch)

| Job | Frequency | Method | Cost |
|-----|-----------|--------|------|
| Scrape ID.me brand directory pages | Weekly | Playwright (deterministic) | $0 |
| Scrape GovX brand directory | Weekly | Playwright (deterministic) | $0 |
| Verify specific discount program pages still active | Weekly | Playwright + simple text match | $0 |
| Probe stale discount programs (no stable URL) | Weekly | Browser Use agent | ~$0.02/run |
| Update rotating seasonal programs (back-to-school, Veterans Day) | Monthly | Manual + crawl | $0 |

### Scraping Priority URLs

| Platform | URL Pattern | Data Available |
|----------|------------|----------------|
| ID.me Shop | `shop.id.me/stores/{store_id}-{brand}` | Discount %, eligible groups, cashback rate |
| ID.me Military | `shop.id.me/military` | All military-eligible brands in one listing |
| ID.me Students | `shop.id.me/students` | All student-eligible brands |
| GovX Brands | `govx.com/brands/all` | Full brand list with categories |
| Home Depot Military | `homedepot.com/c/military` | Program terms, exclusions |
| Lowe's Military | `lowes.com/l/about/honor-our-military` | Program terms, exclusions |
| Samsung Offers | `samsung.com/us/shop/offer-program/` | All eligible groups listed |
| Apple Military Store | `apple.com/shop/browse/home/veterans_military` | Product pricing visible after verification |
| HP Frontline Heroes | `hp.com/us-en/shop/cv/hp-frontline-heroes` | Program terms |
| HP Education | `hp.com/us-en/shop/cv/hp-education` | Program terms |
| LG Appreciation | `lg.com/us/appreciation-program` | Eligible groups, verification flow |
| Lenovo Discounts | `lenovo.com/rf/ref/en/discount-programs/` | All groups listed |
| Microsoft Military | `microsoft.com/en-us/store/b/military` | Terms, product eligibility |
| Microsoft Education | `microsoft.com/en-us/store/b/education` | Terms, product eligibility |

---

## Stacking Rules (Critical for Recommendation Engine)

Most identity discounts **cannot be stacked** with each other or with other promotions. Barkain must know these rules to avoid recommending invalid combinations.

| Brand | Can Stack With | Cannot Stack With |
|-------|---------------|-------------------|
| Apple | Nothing — military and education are mutually exclusive | Other Apple promos, education pricing |
| Samsung | Check per-product — some sale prices apply before identity discount | Sharing pricing externally (TOS violation risk) |
| HP | Free shipping included with Frontline Heroes | Other HP promos (generally) |
| Microsoft | Sometimes seasonal + identity (rare, requires manual check) | Military cannot stack with education |
| Home Depot | 10% military applies to full-price items | Sale items, Lowe's price match, volume pricing |
| Lowe's | 10% military on full-price only | Sale items, Lowe's credit 5% discount, other promos |
| Best Buy | N/A (no identity discounts) | — |
| Acer | Varies by SKU | Per-SKU exclusions listed on the Acer Education storefront |
| ASUS | Varies by SKU | — |
| Razer | — | Razer sale pricing (student discount applies to full-price SKUs only) |
| Logitech | Varies by SKU | — |
| Amazon (Prime Young Adult) | N/A — membership-fee discount only | Prime Student (users pick one) |

**Portal bonuses are generally stackable** — a user can shop Samsung.com through Rakuten (cashback) AND use their military discount. This is where Barkain's multi-layer stacking creates the most value.

**Per-retailer scope dedup (BE-L2).** When two identity programs at the same
retailer would both surface for the same user (e.g. Apple Military 10% + Apple
Education 5% for a military-and-student user; or HP "Education Store" 40% + HP
"HP Education" 35% for a student), `IdentityService._dedup_best_per_retailer_scope`
keeps the highest-savings program per `(retailer_id, scope)` pair. Matches the
real-world terms listed in the table above — Apple's terms explicitly say
military and education are mutually exclusive. Different scopes survive the
dedup, so a Prime Student (`scope='membership_fee'`) card coexists with any
product-scope Amazon program.

---

## Expansion Roadmap

### Phase 2 (add retailers)
- Target (10% military during Veterans Day / Memorial Day)
- Walmart (military family support programs, exchange partnership)
- Costco (member pricing, executive membership comparison)

### Phase 3 (add categories)
- Apparel: Adidas (30% military), Nike (10%), Under Armour (20%), Converse (15%)
- Telecom: T-Mobile (military plan discounts), Verizon (military plans from $25/line)
- Travel: Hotels, rental cars, airlines (extensive military/government rates)
- Streaming: Spotify (student 50% off), YouTube TV, Peacock ($6.99 military), Disney+ (25% off via Exchange)

### Phase 4 (add groups)
- Employer-specific discount programs (corporate perks portals)
- Credit union member discounts
- Professional association discounts (IEEE, ACM, etc.)

---

## Data Model Alignment

This document feeds into the following tables defined in SCRAPING_AGENT_ARCHITECTURE.md:

- **`discount_programs`** — One row per retailer × program. This doc provides the seed data.
- **`user_discount_profiles`** — Boolean flags per identity group. Onboarding captures these.
- **`card_reward_programs`** — Separate from identity discounts but stacks on top.
- **`portal_bonuses`** — Cashback portals that stack with identity discounts.
- **`coupon_cache`** — Coupon codes that may or may not stack with identity discounts.

The query-time discount matching function (`find_applicable_discounts`) in SCRAPING_AGENT_ARCHITECTURE.md uses all of these tables to produce zero-LLM-cost discount matches.
