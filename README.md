# Barkain

Native iOS app + Python backend that finds the absolute lowest total cost of any product. It combines price comparison, identity-based discounts (student / military / employee programs), credit card reward optimization, coupons, secondary-market listings, shopping-portal bonuses, and price prediction into a single AI-powered recommendation.

## What it does

Scan a barcode or search by name. Barkain checks every retailer it knows about, looks at every discount you're personally eligible for, picks the best card from your wallet, and tells you the cheapest path to actually buying the thing — including which portal to click through and how to stack the coupons.

It's the difference between *"$249 at Best Buy"* and *"$219 at Best Buy through Rakuten with the Amex Gold and the BBY 10% appliance promo, total savings $30."*

## How it works

- **iOS** — native SwiftUI (iOS 17+), MVVM with the new `@Observable` macro. SSE for live price streams, byte-level URLSession parser for low-latency retailer rows.
- **Backend** — FastAPI + Pydantic v2 + SQLAlchemy 2.0 async, modular monolith. Postgres + TimescaleDB for price history, Redis for caching + inflight coalescing, SQS (LocalStack in dev) for background workers.
- **Scrapers** — per-retailer Chromium containers (FastAPI + agent-browser) deployed on a single EC2 host. API-first where possible (eBay Browse, Best Buy Products, Decodo Scraper for Amazon, Walmart HTTP via Decodo) with selector-based fallbacks for retailers that don't expose APIs.
- **AI** — Gemini for product resolution (Serper SERP synthesis primary, grounded fallback) and a deterministic, no-LLM recommendation engine that ranks options in <150ms p95.

## Status

In active development. Not yet on the App Store.

- Phase 1 — Foundation: shipped (`v0.1.0`)
- Phase 2 — Intelligence Layer: shipped (`v0.2.0`)
- Phase 3 — Recommendation Intelligence: in progress
- Phase 4 — Production Optimization: planned
- Phase 5 — Growth (Android, web, push): planned

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
```

## License

This is a personal project; no license is granted for redistribution or commercial use. Code is published for visibility, not reuse.
