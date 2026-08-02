# Wholesale Sourcing Scanner — SUPERSEDED

> # ⛔ THIS COPY IS A FORK POINT, NOT THE SOURCE OF TRUTH.
>
> M15 was extracted on 2026-07-30 into its own repository and product:
> **Sourcely** — `github.com/THHUnlimted/sourcely`, local checkout at
> **`~/Sourcely`**.
>
> **Edit Sourcely. Never edit this copy.** It is frozen at the fork point and
> kept only so Barkain's history stays readable. Anything you change here is
> invisible to the running product.
>
> Sourcely has since moved well past this snapshot — it has a live FastAPI app,
> an iOS scan-to-verdict surface, an EC2 deployment behind Caddy, a scheduled
> snapshot worker, landed-cost wiring, and a forecast/recon calibration loop.
> Its test suite is **464 tests, ~0.4 s, no DB and no network**. The "4-step
> activation" this document describes was overtaken by the extraction and no
> longer applies.
>
> The rest of this file is the original capability canvas and build plan, which
> remains the best explanation of *why* the module is shaped the way it is.
> `~/Sourcely/README.md` is its living successor.

---

> **Status:** M15 core complete, unwired. Rev E — fee engine validated against
> real settlements across 4 SKUs / 3 categories / both fulfillment types.
> **Last updated:** 2026-07-26 (frozen — superseded 2026-07-30)

---

## 1. The reframe

This is **not** a "scan one product" app. Retail arbitrage scans items one at a
time in a store aisle. Wholesale sourcing works the other way around: a
distributor emails you a price list — 3,000 rows of UPC / cost / MOQ / case pack
— and your job is to find the 5 winners hiding in it.

So the input surface is a **file upload**, not a camera. Everything else follows
from that:

| Retail arbitrage (Barkain today) | Wholesale sourcing (M15) |
|---|---|
| One barcode → best price to **buy** | 3,000 UPCs → best items to **resell** |
| Optimize consumer out-of-pocket | Optimize seller net profit / unit |
| Latency budget: sub-3 s, one product | Throughput budget: 3,000 rows, minutes |
| Answer = "buy here with this card" | Answer = "these 12 rows, ranked" |
| Real-time, cache-hostile | Batch, cache-*hungry* |

The unit of work changes from **product** to **list**, and the unit of output
changes from **price** to **verdict**.

---

## 2. Capability canvas — what Barkain already gives us

The point of building this inside Barkain is that roughly 60% of the hard parts
already exist and are battle-tested against live retailers.

### 2.1 Reuse as-is (zero new code)

| Barkain component | Where | What it does for M15 |
|---|---|---|
| **eBay Browse API adapter** | `m2_prices/adapters/ebay_browse_api.py` | OAuth `client_credentials` token cache w/ 2 h TTL + refresh buffer, condition-ID buckets, normalized `ContainerListing` mapping, partial-listing denylist. M15 adds a `gtin=` search path on top of the same token. |
| **UPCitemdb client** | `m1_product/upcitemdb.py` | Fallback product identity: title, brand, category, **weight + dimensions** (needed by the fee engine when the retailer APIs don't return them). |
| **Walmart HTTP adapter** | `m2_prices/adapters/walmart_http.py` | Decodo US-residential proxy + `__NEXT_DATA__` parser + PerimeterX CHALLENGE retry budget. This is the *hybrid* leg — Walmart.io's affiliate API is the primary, this is how you get review counts and "X+ bought since yesterday" badges the API doesn't expose. |
| **Serper web search** | `ai/web_search.py` | Brand research: is this brand gated on Walmart, who are its authorized distributors. |
| **Error envelope** | `app/errors.py` | `{"detail": {"error": {code, message, details}}}` — one client-side decoder for the whole API. |
| **Auth + rate limiting** | `app/dependencies.py` | Clerk JWT, per-tier Redis rate buckets, `DEMO_MODE` bypass. M15 adds a dedicated `sourcing_crunch` bucket. |
| **SSE plumbing** | `m2_prices/sse.py` | `sse_event()` + `SSE_HEADERS`, and an iOS byte-level splitter that already works. A 3,000-row crunch is exactly the shape SSE was built for. |
| **SQS workers** | `workers/queue_client.py`, `scripts/run_worker.py` | The snapshot cron (Week 3) is a worker subcommand, not new infrastructure. |
| **TimescaleDB** | `price_history` hypertable | The snapshot table is the same pattern. Timescale is already in `docker-compose.yml` and the test bootstrap. |
| **Deterministic scoring precedent** | `m6_recommend/service.py` | M6 is zero-LLM, `asyncio.gather` + pure Python math, p95 < 150 ms. The verdict scorer is the same shape — a fee/profit calculator is *Traditional* per `docs/FEATURES.md`, never an LLM call. |

### 2.2 Reuse with adaptation

| Component | Adaptation needed |
|---|---|
| **Relevance gates** (`_resolved_matches_query`, brand-bleed, token-overlap) | Sourcing matches by **UPC**, which is exact — the gates mostly stop mattering. They come back for the *fallback* title-search path when a UPC has no listing. |
| **Inflight Redis cache** (`prices:inflight:{pid}`) | Becomes the per-UPC match cache. Different TTL posture: a consumer price is stale in minutes, a wholesale match is fine for 12 h. Cache aggressively — it's also the rate-limit defense. |
| **`ContainerListing` schema** | Already carries `price / seller / condition / url / is_available`. M15 needs `review_count`, `seller_count`, `item_id` — added on the M15-side match DTO rather than polluting M2's wire contract. |
| **`Product` / products table** | Sourcing rows deliberately do **not** write to `products`. A distributor list is 3,000 speculative UPCs; most are never resolved. Polluting the consumer cache with them would wreck `Recently Sniffed` and the trigram search. M15 owns its own tables. |

### 2.3 Genuinely new

- **UPC normalization** (`m15_sourcing/upc.py`) — distributor lists are *dirty* in
  ways a barcode scanner never is. See §4.
- **Spreadsheet ingest** (`ingest.py`) — CSV/TSV/XLSX with header auto-detection.
- **Fee engine** (`fees.py`) — Walmart referral by category + WFS by weight/dims
  + storage; eBay FVF + per-order + shipping estimate.
- **Verdict scoring** (`scoring.py`) — thresholds → PASS / WATCH / FAIL + rank.
- **Popularity engine** (`demand.py`) — the hard part, and 99% of the battle.
  Seven confidence tiers topped by observed inventory depletion. See §5.
- **Snapshot store** (`listing_snapshots`) — the proprietary dataset. See §6.
- **Brand access ledger** (`brand_access`) — the part software can't fully
  automate. See §7.

---

## 3. Pipeline: UPC in → verdict out

```
distributor.csv
     │
     ▼
┌──────────────┐   header auto-detect, money parsing, case-pack math
│ 1. INGEST    │   → SourcingList + N × SourcingRow
└──────┬───────┘
       ▼
┌──────────────┐   scientific notation, stripped zeros, missing check digit,
│ 2. NORMALIZE │   UPC-E expansion, EAN-13/GTIN-14 → UPC-A
└──────┬───────┘   → gtin14 (canonical) + upc12 + method + warnings
       ▼
┌──────────────┐   asyncio.gather, bounded by semaphore + Redis cache
│ 3. MATCH     ├── Walmart  (Walmart.io items?upc= → price, itemId, reviews, stock)
└──────┬───────┴── eBay     (Browse gtin= → active price band + competition count)
       ▼
┌──────────────┐   review-velocity Δ, sold-count-90d, badge parse, seller count
│ 4. DEMAND    │   → est_monthly_sales + confidence tier
└──────┬───────┘
       ▼
┌──────────────┐   referral % by category, WFS by weight/dims, storage,
│ 5. FEES      │   eBay FVF + $0.40 + shipping-by-weight
└──────┬───────┘
       ▼
┌──────────────┐   net $/unit, margin %, ROI %, unit share, price stability
│ 6. VERDICT   │   → PASS / WATCH / FAIL + projected monthly profit
└──────┬───────┘
       ▼
  ranked candidates  →  distributor inquiry email draft
```

Both channels are scored independently and the row keeps **both** — some items
are Walmart winners, some are eBay winners, and the whole point of running both
legs is that you can't tell which from the cost column.

---

## 4. UPC normalization — why it needs its own module

Distributor lists arrive dirty in predictable ways. Every one of these is
handled in `m15_sourcing/upc.py`:

| Symptom | Cause | Handling |
|---|---|---|
| `1.9594903632E+11` | Excel coerced a long number to a float and rendered it in scientific notation | Expand via `Decimal`, then re-pad |
| `195949036323.0` | Same, but under 15 significant digits | Strip the `.0` tail |
| `12345678901` (11 digits) | Either a stripped leading zero **or** a body with no check digit — genuinely ambiguous | Try both; prefer the interpretation whose check digit validates; flag `AMBIGUOUS_11_DIGIT` when both do |
| `04963406` (8 digits) | UPC-E compressed form | Expand to UPC-A per the standard's 6 cases |
| `0195949036323` (13) | EAN-13 with a US `0` prefix | Strip to the 12-digit UPC-A |
| `00195949036323` (14) | GTIN-14 case code | Strip leading zeros; a **non-zero** indicator digit means it's a *case*, not an each — flagged, not silently unwrapped |
| `8 12345 67890 1` | Human-readable spacing from a PDF paste | Strip non-digits |
| Check digit fails | Typo or truncation | Kept with `INVALID_CHECK_DIGIT`; still searchable, never silently "corrected" |

Canonical storage is **GTIN-14** (zero-padded), because it's the only form that
round-trips every input without loss. `upc12` / `ean13` are derived views.

---

## 5. Popularity — the part that actually decides

Margins are arithmetic. Whether the thing *sells* is the real question, and
every marketplace is deliberately unhelpful about it. Signals are ranked by how
close each one is to counting units, and that ranking is carried all the way to
the interface — a verdict built on observed stock movement and one built on a
lifetime review total must not look the same on screen.

| Tier | Signal | Source | How close to truth |
|---|---|---|---|
| `observed` | **Inventory depletion** | Walmart · Amazon · eBay | **Counts units.** ~87% of actual on items with visible stock. Measures *one seller's* movement, not the listing's. |
| `direct` | Exact sold count | eBay Terapeak / Product Research | **Is the number.** Not an estimate. |
| `rank` | Best Sellers Rank | Amazon | 20–40% of actual under rank 50k, per-category curves, degrades on the long tail. |
| `velocity` | Review delta | All three | Rests entirely on the ~2% review-rate constant — the softest number in the system. |
| `badge` | "500+ bought yesterday" | Walmart, intermittently | A floor, not an estimate. But it's same-day truth. |
| `heuristic` | Lifetime reviews ÷ age | All three | 4,000 reviews over six years says nothing about this month. Ranks; never decides. |
| `unknown` | Nothing | — | Can never be `PASS`. |

### 5.1 Inventory depletion — the definitive method

Poll a listing's purchasable quantity, walk the observations in time order, sum
the **decreases**. An increase is a restock — reset the baseline, count nothing.
That sum is units sold: not modelled, observed.

Two properties make it the best signal available:

- **It measures a specific seller, not the listing.** Every other signal
  describes the whole listing and then has to be divided by a guessed seller
  count. Depletion already *is* the per-offer number, so `unit_share()` skips
  the division entirely for it — dividing again would understate a good row by
  a factor of five.
- **It works on all three channels**, with no API approval, no subscription,
  and no dependence on buyer behavior.

**The guard that makes it usable:** a listing reporting 400 units on Monday and
0 on Tuesday almost certainly went out of stock or had a feed error — it did not
sell 400 units in a day. Any single-interval drop exceeding 75% of the running
baseline is discarded as a correction. Without that guard one bad observation
produces a phantom top-ranked row, which on a velocity-first ranking is the
worst failure the system can have.

**The cost:** one probe per SKU per day, and cart-level probing is heavier than
a page read. Run it against the **shortlist** — rows that already cleared the
fee gates — not against all 3,000 rows of every list. Roughly 50–200 SKUs
polled daily.

### 5.2 What changed on eBay

The original plan routed exact sold-counts through eBay's Marketplace Insights
API. As of mid-2026 that is a Limited Release effectively closed to anyone who
isn't a major partner. **Terapeak / Product Research inside Seller Hub is the
real path:** free with a seller account, exact units sold over a window, and an
authenticated page rather than an API — so it's an import or session-scrape.
`sold_count_window_days` is carried explicitly on the snapshot so a 30-day
Product Research export isn't silently divided by three like a 90-day one.

### 5.3 Amazon BSR

Per-category power-law curves, `monthly_units ≈ a × rank^-b`, with 14 category
keys plus a default. Treat the coefficients exactly like the fee tables:
configuration to re-verify against real data, not constants.

### 5.5 Projected vs. actual

Every demand tier has a known error profile, and right now those errors are
unmeasured. `forecast.py` closes the loop: record the prediction, compare to
what actually sold, learn the bias.

Actuals come from first-party seller APIs — your own data, no approval needed:

| Channel | API | Gives |
|---|---|---|
| Walmart | Orders API | Shipped units per SKU per window |
| Walmart | Reports API (reconciliation) | Realized revenue + every fee (already parsed by `recon.py`) |
| Walmart | Insights API | Listing performance and quality |
| eBay | Sell Fulfillment `getOrders` | Actual units sold |
| eBay | Sell Finances `getTransactions` | Exact realized fees |
| eBay | Sell Analytics `getTrafficReport` | Impressions, views, **sales conversion rate** |

Note the contrast with §5.2: eBay's *Marketplace Insights* API (competitor sold
data) is effectively closed, but the *Sell* APIs covering your own account are
open to any seller with a dev key. Other people's data is hard to get; yours
isn't.

The traffic report is the sleeper. Conversion rate is the missing term in every
demand estimate — it separates "nobody wants this" from "nobody saw this", and
those call for opposite responses.

**Three guards** keep the loop from learning the wrong lesson: corrections are
reported below 5 paired samples but not applied; factors are clamped to
0.25×–4× (anything outside almost always means a mis-paired SKU); and medians
rather than means, so one viral week can't reset the model.

`net_per_unit` bias is tracked separately on purpose — running below 1.0 means
the *fee and cost* model is optimistic, which is a `recon.py` problem rather
than a demand problem.

### 5.4 Unit share

Where a channel gives nothing better, listing-wide demand still converts to
your demand:

```
unit_share = est_monthly_sales ÷ (seller_count + 1)
```

The `+1` is you. Five sellers on a 300 unit/month item is 50 each and a real
business; five on a 40 unit/month item is a price war with extra steps.

## 6. The snapshot database — the moat

`listing_snapshots` is a TimescaleDB hypertable keyed
`(channel, listing_key, captured_at)` storing price, review count, rating,
seller count, stock state, and sold-count when available.

- Written by the worker (`workers/sourcing_snapshots.py`) on a cron over every
  listing referenced by any active sourcing list.
- Read by `demand.py` for velocity, and by `scoring.py` for **price stability**
  (coefficient of variation over the window — a buy box that swings 30% is a
  price war you're walking into).
- Retention: Timescale compression after 90 days; never dropped. The whole
  value is in the tail.

This is the step that turns the product from a calculator into an intelligence
tool, and it's the reason to start snapshotting on day one even before the
demand math is wired up — you cannot backfill time.

---

## 6b. Landed cost and selling plans

### Landed cost

The price-list number is the *invoice* cost. A sellable unit has also absorbed
freight, prep, packaging, duty, payment fees, and a share of the units that
arrived broken or came back. Scoring on invoice cost overstates margin
**unevenly** — a 14 lb air purifier absorbs far more freight per unit than a
4 oz phone case at the same invoice price — which means it doesn't shift rows,
it *reorders* them.

Measured on the sample list, the uplift ranges from **+11.4% to +31.0%** across
four rows. A flat "add 20% for costs" rule would be wrong in both directions.

**Reserves divide, they don't add.** You don't pay shrink and returns per unit —
you lose that fraction of units, and the survivors carry the cost of all of
them. The rates also *compound* rather than sum: shrink removes units in
transit, and the return rate then applies to whatever actually sold. 3% shrink
+ 5% returns leaves a survival rate of `0.97 × 0.95 = 0.9215`, so the sellable
units carry `1 / 0.9215` — an **8.52%** cost increase, not the 8% an additive
fee model implies.

Every component defaults to zero with an `assumptions` flag recording what was
left unspecified. An invented freight number that happens to be wrong is worse
than a visible gap, because it looks like it was measured.

### Selling plans

A monthly subscription is a **fixed** cost, and amortizing it into per-unit
margin is wrong in both directions: if you already pay it, it's sunk for the
next SKU decision; if you don't, it's a threshold question with a volume answer.

So `plans.py` does two things and never mixes them:

1. **Marginal rates** — an eBay Store's FVF cut, Amazon Individual's $0.99/item.
   Genuinely per-unit; flows into the fee engine.
2. **Breakeven volume** — the fixed fee reported once per channel as the volume
   at which the plan pays for itself.

The Amazon Individual→Professional crossover comes out at ~40 units/month, which
is the well-known number — but it's *derived* from the two fee structures rather
than written down, so it moves on its own when Amazon changes either.

---

## 6c. Ranking: velocity beats margin

Rows sort by **annualized ROI**, not margin and not raw monthly profit:

```
annualized_roi = roi_pct × 365 ÷ (days_to_sell_through + reorder_lead_time)
```

For a capital-constrained buyer the scarce resource is cash, and what matters is
how many times a year it comes back with a profit attached. A 60% margin turning
over twice a year is a worse purchase order than 22% turning over eleven times.

**Lead time in the denominator is not a detail.** Capital redeploys when the next
case lands, not when the last unit ships. An item clearing in six days on a
three-week reorder cycle turns over ~14×/year, not 60×. Building the metric
without lead time produced four-figure percentages on every fast mover in
testing and reordered the whole list on an artifact of the formula.

Two hard gates enforce the preference rather than leaving it to sort order:
`max_days_to_sell_through` (default 90) and `min_annualized_roi_pct`
(default 150%). `RankingPolicy` keeps `monthly_profit` and `margin` available,
but `velocity` is the default and the thresholds are tuned for it.

---

## 7. What software can't automate

"Available" in the wholesale sense means **can you legally source it**: is there
an authorized distributor who will sell to you, and is the brand ungated on your
Walmart seller account. That's relationships and paperwork.

What *is* automatable is everything adjacent, and it lives in `brand_access`:

- A per-brand ledger: `authorized` (you have a distributor) / `restricted`
  (known gated on the channel) / `pending` (inquiry sent) / `unknown`.
- Rows whose brand is `restricted` are **demoted, not hidden** — a restricted
  brand with a $9/unit spread is worth knowing about when you're deciding which
  gating application to file.
- Candidates that pass the thresholds and sit on an `unknown` brand
  auto-generate a distributor inquiry email draft (`POST /rows/{id}/inquiry`)
  pre-filled with the item, the case quantity you'd commit to, and your
  reseller-certificate boilerplate. Turning 12 candidates into 12 sent emails
  should be one click, not an afternoon.

---

## 8. API surface

All under `/api/v1/sourcing`, Clerk-authed, `sourcing` rate bucket.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/lists` | Multipart upload. Returns the list + detected column mapping + normalization stats **before** any API spend. |
| `GET` | `/lists` | Your lists, newest first. |
| `GET` | `/lists/{id}` | List detail + verdict counts. |
| `POST` | `/lists/{id}/crunch` | Run the pipeline. Batch-shaped. |
| `GET` | `/lists/{id}/crunch/stream` | Same, SSE — `progress` / `row` / `done` events. |
| `GET` | `/lists/{id}/candidates` | Ranked output. `?verdict=pass&channel=walmart&limit=50`. |
| `GET` | `/lists/{id}/export.csv` | The ranked table, for the people who will always want a spreadsheet back. |
| `GET`/`PUT` | `/brands` | The brand-access ledger. |
| `POST` | `/rows/{id}/inquiry` | Generate the distributor inquiry draft. |

---

## 9. Rate limits, caching, and terms

The Walmart affiliate API is nominally for driving affiliate traffic. A
3,000-row crunch that returns 12 candidates and drives zero clicks is not what
the program is designed for. Concretely, M15:

- Caches every UPC match in Redis (`sourcing:match:{channel}:{gtin}`) with a
  **12 h** TTL for Walmart / **6 h** for eBay, so a re-crunch of the same list
  costs nothing.
- Bounds outbound concurrency with a semaphore (`SOURCING_MATCH_CONCURRENCY`,
  default 6) and a per-channel minimum inter-request interval.
- Persists the match on the row, so the second run of a 3,000-row list only
  fetches what expired.
- Keeps the affiliate tag on outbound product URLs, so the traffic the app
  *does* drive is attributed.

If the affiliate API is unavailable or unapproved, `WALMART_SOURCING_ADAPTER`
falls back to the existing `walmart_http` residential-proxy path — the same
adapter-swap pattern as `WALMART_ADAPTER` / `MISC_RETAILER_ADAPTER`.

**Fee schedules change.** `fees.py` carries a `FEE_SCHEDULE_VERSION` and every
rate table cites its source and effective date. Treat them as configuration to
verify quarterly, not as constants.

---

## 10. Build order

| Stage | Scope | State |
|---|---|---|
| **Weekend 1** | CSV upload → UPC normalize → Walmart match → fee calc → profit/ROI table | ✅ shipped in this branch |
| **Weekend 2** | eBay Browse layer, both channels side by side, per-channel verdicts | ✅ shipped in this branch |
| **Week 3+** | Snapshot table + cron worker + review-velocity demand | ⬜ schema + demand math shipped; worker cadence + Timescale retention policy pending |
| **Week 4+** | Brand-access ledger UI, inquiry-email send, Marketplace Insights approval | ⬜ ledger + draft generation shipped; send path pending |
| **Later** | iOS surface (list picker + candidate table), Keepa/Amazon third channel | ⬜ |

---

## 11. Configuration

```bash
# Walmart.io (developer.walmart.com) — affiliate/search API
WALMART_IO_CONSUMER_ID=""          # UUID from the Walmart.io dashboard
WALMART_IO_PRIVATE_KEY=""          # PEM RSA private key (\n-escaped or base64)
WALMART_IO_KEY_VERSION="1"
WALMART_SOURCING_ADAPTER="walmart_io"   # walmart_io | walmart_http | disabled

# eBay — reuses the existing Browse credentials
EBAY_APP_ID=""
EBAY_CERT_ID=""
EBAY_MARKETPLACE_INSIGHTS_ENABLED=false  # requires eBay approval

# Pipeline tuning
SOURCING_MATCH_CONCURRENCY=6
SOURCING_MATCH_CACHE_TTL_WALMART=43200   # 12 h
SOURCING_MATCH_CACHE_TTL_EBAY=21600      # 6 h
SOURCING_MAX_ROWS=10000
SOURCING_REVIEW_RATE=0.02                # share of buyers who leave a review
```

---

## 12. Module map

The module lives at the repo root under `sourcing/`, not inside `backend/`.
That's what keeps it inert: nothing in `backend/` imports it, no router is
registered, and migration `0013` is staged under `sourcing/migrations/` rather
than `infrastructure/migrations/versions/`. Activation moves it; until then the
separation is the safety property.

```
sourcing/
├── demo_crunch.py          # offline end-to-end run — no network, no database
├── sample_price_list.csv   # the fixture demo_crunch and the tests both use
├── migrations/
│   └── 0013_sourcing_tables.py   # staged OUTSIDE alembic until activation
├── tests/                  # pure-module unit suite
└── m15_sourcing/
    ├── upc.py          # normalization — pure, no I/O
    ├── ingest.py       # CSV/TSV/XLSX → SourcingRow drafts, header auto-detect
    ├── fees.py         # Walmart + eBay fee engines, versioned rate tables
    ├── landed_cost.py  # freight, prep, duty, and reserves that divide
    ├── plans.py        # selling plans as marginal rates + breakeven volume
    ├── demand.py       # snapshot → estimated monthly sales + confidence tier
    ├── scoring.py      # thresholds → verdict + projected monthly profit
    ├── forecast.py     # projected-vs-actual calibration loop
    ├── inquiry.py      # distributor inquiry email draft
    ├── recon.py        # settlement / inventory / orders import
    ├── models.py       # sourcing_lists, sourcing_rows, listing_snapshots, brand_access
    ├── config.py       # self-contained settings object
    ├── service.py      # orchestration + Redis match cache + concurrency bounds
    ├── ebay_token.py   # OAuth client_credentials cache
    └── adapters/
        ├── walmart_io.py      # signed Walmart.io affiliate/search client
        └── ebay_sourcing.py   # Browse gtin= search + competition count
```

**Not yet written:** `schemas.py` (Pydantic wire contracts) and `router.py`
(`/api/v1/sourcing`). The API surface in §8 is the design for those, not a
description of shipped code.

`upc.py`, `ingest.py`, `fees.py`, `landed_cost.py`, `plans.py`, `demand.py`,
`scoring.py`, `forecast.py` and `inquiry.py` are **pure** — no DB, no network,
no settings reads at import time. They're the parts worth the most tests and the
parts most likely to be reused if this ever splits into its own service.
`models.py` is the one exception in the package: it imports
`app.database.Base`, so it needs `backend/` on the path.

### Running the tests

```bash
cd sourcing && pytest              # 291 tests, no DB or network needed
python demo_crunch.py              # end-to-end smoke over the sample list
```

Both run in CI on any change under `sourcing/**` — see
`.github/workflows/backend-tests.yml`.
