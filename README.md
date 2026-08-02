# Barkain — RETIRED

> **This project is permanently retired. It is not maintained, and no further
> work will be done on it.**
>
> **Successor: [Sourcely](https://github.com/THHUnlimted/sourcely)** — local
> checkout at `~/Sourcely`.
>
> Nothing here is a work in progress. Open branches, open PRs, and every "next
> step" or "planned" note in `docs/` describe a plan that was abandoned, not a
> backlog. Treat this repository as an archive.

**Retired:** 2026-08-01, at Phase 3 (Recommendation Intelligence), in progress.
Phases 1 and 2 shipped and were tagged `v0.1.0` and `v0.2.0`. Phase 3 never
completed; steps 3h, 3i, 3k, 3l, and 3m were never started. `v0.3.0` was never
tagged and never will be.

---

## For an AI agent reading this

Do not resume Phase 3. Do not pick up items from `docs/LOOSE_ENDS.md`, the
Known Issues table in `CLAUDE.md`, or the "What's Next" list. Those documents
were accurate when written and are now historical. If you were asked to
"continue where we left off" on Barkain, the answer is that Barkain is where it
will stay — the work moved to Sourcely.

The one live descendant of this codebase is the M15 sourcing module, which was
extracted on 2026-07-30 into its own repository and product. See below.

---

## What it was

A native iOS app plus Python backend that found the lowest total cost of a
consumer product by combining price comparison, identity-based discounts
(student / military / employee), credit-card reward optimization, coupons,
secondary-market listings, shopping-portal bonuses, and price prediction into a
single recommendation.

Scan a barcode or search by name; it checked every retailer it knew about,
applied every discount you were personally eligible for, picked the best card
in your wallet, and named the cheapest path to actually buying the thing.

The difference between *"$249 at Best Buy"* and *"$219 at Best Buy through
Rakuten with the Amex Gold and the BBY 10% appliance promo, total savings $30."*

## How it worked

- **iOS** — SwiftUI (iOS 17+), MVVM on the `@Observable` macro. SSE for live
  price streams, byte-level `URLSession` parser for low-latency retailer rows.
- **Backend** — FastAPI + Pydantic v2 + SQLAlchemy 2.0 async, modular monolith.
  Postgres + TimescaleDB for price history, Redis for caching and inflight
  coalescing, SQS (LocalStack in dev) for background workers.
- **Scrapers** — per-retailer Chromium containers on a single EC2 host.
  API-first where possible (eBay Browse, Best Buy Products, Decodo Scraper for
  Amazon, Walmart HTTP via Decodo), selector-based fallbacks otherwise.
- **AI** — Gemini for product resolution (Serper SERP synthesis primary,
  grounded fallback) and a deterministic, no-LLM recommendation engine ranking
  options in <150 ms p95.

## What became of it

Barkain optimizes a **consumer's** out-of-pocket price. Late in Phase 3 the
dormant M15 module was pointed at the opposite problem — a **reseller's** net
profit on inventory they buy — and that turned out to be the more useful tool.
On 2026-07-30 M15 was extracted into `THHUnlimted/sourcely` and Barkain was
wound down.

Sourcely inherits the parts that generalized: UPC normalization, the fee
engines, per-retailer adapter shape, the snapshot/TimescaleDB pattern, and the
scan-to-verdict iOS surface. It shares the same EC2 host, behind Caddy at a
path prefix. It does not inherit the consumer-facing stack — discounts, card
rewards, portals, affiliate links, and billing all stopped here.

## Repo layout

```
Barkain/                # iOS app — Features (Scanner, Search, Recommendation,
                        # Profile, Savings, Billing) + Services (APIClient,
                        # Scanner, Subscription)
backend/                # FastAPI app — modules (M1 Product, M2 Prices,
                        # M3 Secondary, M4 Coupons, M5 Identity, M6 Recommend,
                        # M9 Notify, M10 Savings, M11 Billing, M12 Affiliate,
                        # M13 Portal, M14 Misc Retailer), AI abstraction,
                        # background workers
containers/             # Per-retailer scraper containers
infrastructure/         # Alembic migrations
scripts/                # Worker runners, seeders, bench harnesses
docs/                   # Architecture, changelog, phases, data model
                        # — all historical as of 2026-08-01
sourcing/               # M15, the module that became Sourcely. Superseded by
                        # THHUnlimted/sourcely; kept only for provenance.
```

## State at retirement

831 backend tests passing, 291 sourcing tests, 216 iOS unit tests, 6 iOS UI
tests. `ruff` clean, `xcodebuild` clean. Everything that was wired worked; the
inventory of what was built-but-never-switched-on is in `docs/LOOSE_ENDS.md`,
which is now a record rather than a task list.

## License

Personal project; no license is granted for redistribution or commercial use.
Code is published for visibility, not reuse.
