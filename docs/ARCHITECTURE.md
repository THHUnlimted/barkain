# Barkain — Architecture Reference

> Source: Project Planning + Architecture Sessions, March–April 2026
> Scope: Stack decisions, project structure, backend conventions, AI abstraction layer, scraper architecture
> Last updated: April 2026 (v3 — Opus for Watchdog self-healing, Browser Use removed, Haiku dropped, LocalStack deferred to Phase 2)

---

## Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| iOS Frontend | Swift 5.9+ / SwiftUI | Advanced proficiency; native camera/barcode APIs; best App Store perf |
| Web Frontend | Next.js 14 / TypeScript | Vercel Pro already paid; SSR for dashboard; Phase 5+ |
| Backend | Python 3.12+ / FastAPI | Async-native; best AI/ML ecosystem; advanced proficiency |
| Database | PostgreSQL 16 (AWS RDS) + TimescaleDB | $10K AWS credits; relational + time-series in one engine |
| Cache | Redis 7 (AWS ElastiCache) | Query caching, rate limiting, session data; covered by AWS credits |
| Queue | AWS SQS | Background job dispatch for scrapers, notifications; managed, no ops |
| AI Primary | Claude API (Sonnet for tasks, Opus for self-healing) | YC credits; vision capabilities for scanning; structured outputs |
| AI Fallback | OpenAI GPT-4o / GPT-4o-mini | YC credits; fallback if Claude fails |
| AI Cheap (extraction) | Qwen Flash / ERNIE | Parsing scraped content into structured data. Cheap, good at structured output |
| Auth | Clerk | Existing Pro sub ($25/mo); handles users, API keys, session mgmt |
| Hosting (MVP) | Railway (backend) + Vercel (web) | Existing subs; minimal ops |
| Hosting (Scale) | AWS ECS + RDS + ElastiCache + S3 | $10K credits; migrate from Railway when scale demands |
| Scraping | agent-browser (CLI, Chrome via CDP) | DOM eval pattern; shell-scriptable; anti-detection built in |
| Scraping (last resort) | Firecrawl (YC credits) | Only when agent-browser + Watchdog heal all fail |
| Subscriptions | StoreKit 2 via RevenueCat | Simplifies IAP for solo dev; free tier covers MVP |
| Package Manager | SPM (iOS), pip (Python), npm (web) | Native tools, no extra dependencies |

**Version constraints:** Python ≥3.12, Swift ≥5.9, Node ≥20 LTS.

---

## Local Development Topology

```
┌─────────────────────────────────────────────────────────────┐
│  docker-compose.yml                                         │
│                                                             │
│  ┌──────────────────┐  ┌────────────┐                          │
│  │ PostgreSQL 16     │  │ Redis 7    │    LocalStack deferred   │
│  │ + TimescaleDB     │  │ Alpine     │    to Phase 2            │
│  │ Port: 5432        │  │ Port: 6379 │                          │
│  │ DB: barkain      │  │            │                          │
│  │ User: app         │  │            │                          │
│  └──────────────────┘  └────────────┘                          │
│         ▲ MCP                ▲ MCP                              │
└─────────────────────────────────────────────────────────────┘
          │                    │
   ┌──────┴────────────────────┴────────────────────────┐
   │  Claude Code (coding agent)                          │
   │  + Context7 MCP (library docs)                       │
   │  + Clerk MCP (auth inspection)                       │
   │  + XcodeBuildMCP (iOS build/test)                    │
   └──────────────────────────────────────────────────────┘
```

---

## Version Control

**Repo:** `github.com/[org]/barkain`
**Branch strategy:** `phase-N/step-Na` branches → PR to `main`
**Protection rules:** CI must pass before merge; no direct pushes to `main`

---

## iOS Frontend Architecture

**Navigation:** TabView with 4 tabs — Scan, Search, Savings, Profile. Each tab has its own NavigationStack.

**State management:** `@Observable` ViewModels per feature screen. `@State` for view-local ephemeral state only.

**Data fetching:** All network calls go through `APIClient.swift` (typed, async/await). No direct URLSession calls in views or ViewModels.

**Camera/Scanning:**
- AVFoundation for barcode scanning (native, iOS 7+, no dependency)
- Vision framework `VNRecognizeTextRequest` for on-device OCR (iOS 13+)
- VisionKit `VNDocumentCameraViewController` for receipt capture (iOS 13+)
- VisionKit `DataScannerViewController` for live scanning (iOS 16+, A12+ required)
- Claude Vision API (via backend) for image-based product identification

**Subscription:** StoreKit 2 via RevenueCat SDK.

---

## Backend Architecture

### Module System

12 modules, each self-contained with: `router.py` (FastAPI endpoints), `service.py` (business logic), `models.py` (SQLAlchemy ORM), `schemas.py` (Pydantic request/response).

Modules communicate via direct Python imports (modular monolith). No message bus between modules at MVP scale.

### Middleware Stack (outermost → innermost)

1. **CORS** — Allow iOS app + web dashboard origins
2. **Request logging** — Structured JSON logs, request ID propagation
3. **Rate limiting** — Redis-backed, per-user limits (60/min default, 10/min for AI-heavy endpoints)
4. **Auth (Clerk)** — JWT validation via Clerk SDK; extracts user_id for downstream modules
5. **Error handling** — Catches all exceptions, returns structured error responses

### API Versioning

All endpoints under `/api/v1/`. Version bump only on breaking changes.

### Scraper Container Architecture (Phase 1)

Each retailer runs in its own Docker container (11 containers for demo):

```
┌─────────────────────────────────────┐
│  Container: walmart-scraper          │
│  ├── chromium (headed mode)          │
│  ├── agent-browser CLI               │
│  ├── walmart-extract.sh (9-step)     │
│  ├── extract.js (DOM eval script)    │
│  ├── config.json (selectors, health) │
│  ├── test_fixtures.json              │
│  └── AI health agent (Watchdog)      │
│       └── Claude Opus (YC credits)    │
└─────────────────────────────────────┘
```

Backend sends `POST /extract` to container → container runs extraction → returns structured JSON → backend caches in TimescaleDB (6hr TTL).

#### Batch 1 Containers (Step 1d)

| Retailer | Port | Directory | Key Deviations |
|----------|------|-----------|----------------|
| Amazon | 8081 | `containers/amazon/` | Title fallback chain (3 selectors), sponsored noise stripping |
| Walmart | 8083 | `containers/walmart/` | **PerimeterX:** Chrome launches directly with search URL; never `agent-browser open` |
| Target | 8084 | `containers/target/` | **Wait strategy:** `load` not `networkidle` (analytics pixels hang); wait for `[data-test='product-grid']` |
| Sam's Club | 8089 | `containers/sams_club/` | Best-guess selectors; needs live validation |
| Facebook Marketplace | 8091 | `containers/fb_marketplace/` | Login modal hidden with CSS `display:none` (never `.remove()`); all items condition "used" |

#### Batch 2 Containers (Step 1e)

| Retailer | Port | Directory | Key Notes |
|----------|------|-----------|-----------|
| Best Buy | 8082 | `containers/best_buy/` | `.sku-item` anchor, standard networkidle flow |
| Home Depot | 8085 | `containers/home_depot/` | `[data-testid="product-pod"]` anchor, needs live validation |
| Lowe's | 8086 | `containers/lowes/` | Multi-fallback selectors, needs live validation |
| eBay (new) | 8087 | `containers/ebay_new/` | `.s-item` anchor, URL filter `LH_ItemCondition=1000` for new only |
| eBay (used/refurb) | 8088 | `containers/ebay_used/` | `.s-item` anchor, URL filter for used+refurb, extracts condition from `.SECONDARY_INFO` |
| BackMarket | 8090 | `containers/backmarket/` | All items condition "refurbished", seller extraction |

### Background Workers

Standalone Python scripts that poll SQS queues. Not Celery.

| Worker | Queue | Schedule | Purpose |
|---|---|---|---|
| price_ingestion | price-ingest-queue | Every 6h by category | Fetches prices from retailer APIs/containers |
| portal_rates | portal-rate-queue | Every 6h | Scrapes portal cashback rates (Rakuten, TopCashBack, etc.) |
| discount_verification | discount-verify-queue | Weekly | Verifies identity discount programs still active |
| coupon_validator | coupon-validate-queue | Daily | Tests coupon codes for validity |
| prediction_trainer | predict-train-queue | Nightly | Retrains Prophet model on price history |

### Error Handling Format

```json
{
  "error": {
    "code": "PRODUCT_NOT_FOUND",
    "message": "No product found for UPC 012345678901",
    "details": {}
  }
}
```

---

## AI Abstraction Layer

**Location:** `backend/ai/`

All LLM interactions go through `abstraction.py`. No module imports `google.genai`, `anthropic`, or `openai` directly. The abstraction uses the `google-genai` SDK with native async (`client.aio.models.generate_content`).

**Gemini config:** Thinking enabled (`ThinkingConfig(thinking_budget=-1)` — model decides), Google Search grounding (`Tool(google_search=GoogleSearch())`), temperature=1.0, max_output_tokens=4096. Response parsing via `_extract_text()` skips thinking parts (`.thought == True`) and only returns model text output. JSON extraction has regex fallback for truncated responses.

### Model Routing

| Task | Model | Rationale | Phase |
|---|---|---|---|
| UPC product resolution | Gemini 3.1 Flash Lite Preview | Fast, cost-effective UPC lookup with thinking + Google Search grounding. System instruction (9-step reasoning, cached by Gemini); user prompt (bare UPC + output format). Returns `device_name` only | 1 |
| Full-stack recommendation | Claude Sonnet | Multi-variable reasoning across all 9 layers | 3 |
| Image product identification | Claude Sonnet (vision) | Best vision quality in testing | 3 |
| Receipt OCR interpretation | Claude Sonnet (vision) | Structured data extraction from text | 3 |
| Price prediction reasoning | Claude Sonnet | Complex temporal pattern analysis | 4 |
| Watchdog self-healing | Claude Opus | Highest quality selector rediscovery; YC credits make cost viable | 2 |
| Extraction parsing | Qwen Flash / ERNIE | Parsing scraped content into structured data | 2 |
| Fallback (any task) | GPT-4o-mini / GPT-4o | If Claude API is down or returns errors | 3 |

### Prompt Templates

Stored in `backend/ai/prompts/` as Python string templates with variable injection. Each module that uses AI has a corresponding prompt file. The UPC lookup prompt uses a two-part architecture: `UPC_LOOKUP_SYSTEM_INSTRUCTION` contains full 9-step reasoning instructions (cached by Gemini across calls), while the user prompt is just the bare UPC string + output format constraint (`device_name` only). The service parses only `device_name` from the response (mapped to `name`), setting `source=gemini_upc`. Brand, category, ASIN, and description are left as None — populated by UPCitemdb fallback or future enrichment.

### Structured Outputs

All AI calls request JSON output. Use Instructor library for Pydantic model validation of LLM responses. If response fails validation, retry once with error context.

---

## API Endpoint Inventory

### Phase 1 Endpoints

| Method | Path | Module | Description | Rate Limit |
|---|---|---|---|---|
| GET | /api/v1/health | core | Health check (DB + Redis connectivity) | Exempt |
| POST | /api/v1/products/resolve | M1 | UPC/barcode → product (Gemini API, UPCitemdb backup) | 60/min |
| GET | /api/v1/prices/{product_id} | M2 | Get prices from all 11 retailers (via containers) | 60/min |

### Phase 2 Endpoints

| Method | Path | Module | Description | Rate Limit |
|---|---|---|---|---|
| GET | /api/v1/secondary/{product_id} | M3 | Secondary market listings | 30/min |
| GET | /api/v1/coupons/{retailer_id} | M4 | Available coupons for retailer | 60/min |
| GET | /api/v1/profile | M5 | Get user identity profile + cards | 60/min |
| PUT | /api/v1/profile | M5 | Update identity profile | 30/min |
| GET | /api/v1/profile/cards | M5 | Get user's card portfolio | 60/min |
| POST | /api/v1/profile/cards | M5 | Add card to portfolio | 30/min |

### Phase 3 Endpoints

| Method | Path | Module | Description | Rate Limit |
|---|---|---|---|---|
| POST | /api/v1/products/identify | M1 | Image → product (vision AI) | 10/min |
| POST | /api/v1/recommend | M6 | Full-stack recommendation | 10/min |
| GET | /api/v1/card-match/{product_id} | M5 | Card recommendation for product at retailer | 60/min |
| POST | /api/v1/receipts/scan | M8+M10 | Receipt text → savings calc | 10/min |
| GET | /api/v1/savings | M10 | Savings dashboard data | 60/min |

### Phase 4 Endpoints

| Method | Path | Module | Description | Rate Limit |
|---|---|---|---|---|
| GET | /api/v1/predict/{product_id} | M7 | Price prediction + buy/wait | 30/min |
| POST | /api/v1/watch | M9 | Watch a product for price drop | 30/min |
| GET | /api/v1/watch | M9 | User's watched items | 60/min |
| DELETE | /api/v1/watch/{item_id} | M9 | Stop watching | 30/min |

Phase 4 also adds free API adapters (Best Buy, eBay Browse, Keepa) as a speed optimization layer for production.

### Phase 5 Endpoints

| Method | Path | Module | Description | Rate Limit |
|---|---|---|---|---|
| GET | /api/v1/alerts | M9 | User's active push notification alerts | 60/min |
| POST | /api/v1/alerts | M9 | Configure push notification preferences | 30/min |

---

## iOS Route Map

| Tab | Screen | Auth | Phase | Description |
|---|---|---|---|---|
| Scan | ScannerView | Yes | 1 | Camera for barcode scanning |
| Scan | RecommendationView | Yes | 1 (basic), 3 (full) | Price comparison → full-stack result |
| Search | SearchView | Yes | 1 | Text search for products |
| Search | ProductDetailView | Yes | 1 (basic), 3 (full) | Price comparison + all layers |
| Savings | SavingsDashboard | Yes | 3 | Running totals, receipt history |
| Savings | ReceiptDetailView | Yes | 3 | Individual receipt breakdown |
| Profile | ProfileView | Yes | 2 | Identity profile, cards, memberships |
| Profile | CardPortfolioView | Yes | 2 | Card management, add/remove cards |
| Profile | SettingsView | Yes | 2 | Notification prefs, subscription |
| — | OnboardingFlow | No | 2 | Identity + card setup on first launch |
| — | PaywallView | Yes | 2 | Pro subscription upsell |
| — | CardInterstitialView | Yes | 3 | Purchase card recommendation overlay |

---

## Data Pipeline (5 Tiers)

Designed so 90%+ of queries resolve before hitting expensive LLM calls.

| Tier | Source | Latency | Cost | When |
|------|--------|---------|------|------|
| 1. Internal DB | PostgreSQL cache | <50ms | $0 | Always (cache hit) |
| 2. agent-browser containers | All 11 retailers (demo) | 3-8s | ~$0.0075 (proxy at scale) | Cache miss, Phase 1+ |
| 3. Free APIs (production) | Best Buy, eBay Browse | 200-800ms | $0 | Phase 4+ (speed optimization) |
| 4. Paid APIs (production) | Keepa (Amazon) | 500-1500ms | $0.01-0.02 | Phase 4+ (speed optimization) |
| 5. AI reasoning | Claude Sonnet recommendation | 1-2s | $0.01-0.03 (YC credits) | Every query, Phase 3+ |
