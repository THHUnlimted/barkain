# Wholesale Sourcing Scanner — Capability Canvas + Build Plan

> **Status:** M15 module scaffolded (Weekend 1 + Weekend 2 core + Week 3 schema).
> **Last updated:** 2026-07-26

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
- **Demand estimation** (`demand.py`) — the hard part. See §5.
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

## 5. Demand estimation — the hard part

Walmart doesn't publish sales figures, so everything here is a proxy. In
descending order of signal quality:

| Tier | Signal | How | Confidence |
|---|---|---|---|
| 1 | **eBay sold count (90 d)** | Marketplace Insights API — direct demand data, no estimation. Requires approval; Terapeak in Seller Hub is the free manual equivalent. | `direct` |
| 2 | **Review velocity** | `Δreview_count ÷ Δdays × 30 ÷ REVIEW_RATE`. Industry rule of thumb is ~2% of buyers leave a review, so 6 new reviews in 30 days ≈ 300 units/month. Needs **≥2 snapshots ≥7 days apart**. | `velocity` |
| 3 | **"X+ bought since yesterday" badge** | Scraped from the Walmart product page (the affiliate API doesn't expose it). Coarse buckets — 50+, 100+, 1000+ — but it's a floor, not an estimate. | `badge` |
| 4 | **Rating-count heuristic** | Single snapshot only: `review_count ÷ listing_age_months ÷ REVIEW_RATE`. Wildly noisy on old listings. Used to rank, never to decide. | `heuristic` |
| — | Nothing | No listing, or listing with zero reviews and no badge | `unknown` |

Tier 2 is why the snapshot database exists, and why **the app has to run for a
few weeks before it's smarter than a spreadsheet**. That's not a flaw in the
plan — it *is* the plan. Review velocity requires longitudinal data nobody can
buy, which means the dataset compounds and can't be cloned by a competitor who
launches later.

**Unit share** is what converts demand into your demand:

```
unit_share = est_monthly_sales ÷ (seller_count + 1)
```

The `+1` is you. Five sellers all holding stock on a 300 unit/month item means
50 units each — which is a real business. Five sellers on a 40 unit/month item
means everyone's racing to the bottom.

---

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

```
backend/modules/m15_sourcing/
├── upc.py        # normalization — pure, no I/O, fully unit-tested
├── ingest.py     # CSV/TSV/XLSX → SourcingRow drafts, header auto-detect
├── fees.py       # Walmart + eBay fee engines, versioned rate tables
├── demand.py     # snapshot → estimated monthly sales + confidence tier
├── scoring.py    # thresholds → verdict + projected monthly profit
├── models.py     # sourcing_lists, sourcing_rows, listing_snapshots, brand_access
├── schemas.py    # Pydantic wire contracts
├── service.py    # orchestration + Redis match cache + concurrency bounds
├── router.py     # /api/v1/sourcing
├── inquiry.py    # distributor inquiry email draft
└── adapters/
    ├── walmart_io.py      # signed Walmart.io affiliate/search client
    └── ebay_sourcing.py   # Browse gtin= search + competition count
```

`upc.py`, `ingest.py`, `fees.py`, `demand.py`, `scoring.py`, `inquiry.py` are
**pure** — no DB, no network, no settings reads at import time. They're the
parts worth the most tests and the parts most likely to be reused if this ever
splits into its own service.
