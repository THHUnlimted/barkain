# Barkain — Component Map (Tool Decisions)

> Source: Project Planning + Architecture Sessions, March–April 2026
> Scope: What tools/libraries to use, what was considered and dropped, why
> Last updated: April 2026 (v3.1 — Watchdog ✅, LocalStack ✅, SQS workers live via boto3 + moto[sqs]; Firecrawl promoted from "last resort" to live walmart path)

---

## Decision Principles

1. **Minimize dependencies** — use Apple/Python standard libraries before third-party
2. **SPM only** on iOS — no CocoaPods, no Carthage
3. **pip only** on Python — pinned versions in requirements.txt
4. **Justify every dependency** — must solve something the standard lib cannot
5. **YC credits first** — use Firecrawl, Exa before paying for alternatives
6. **Docker MCPs for live services, CLIs for everything else** — no custom skills or slash commands
7. **Free APIs > agent-browser > Firecrawl** — no paid aggregator APIs

---

## Master Decision Table

### Backend & Infrastructure

| Category | Tool | Action | Reason | Status |
|----------|------|--------|--------|--------|
| **Backend Framework** | FastAPI | KEEP | Async-native, Pydantic v2, best Python API framework | ✅ Confirmed |
| **ORM** | SQLAlchemy 2.0 (async) | KEEP | Mature, async support, Alembic migrations | ✅ Confirmed |
| **Database** | PostgreSQL 16 + TimescaleDB | KEEP | AWS credits; relational + time-series in one | ✅ Confirmed |
| **Cache** | Redis 7 (ElastiCache) | KEEP | Price caching + rate limiting + query cache | ✅ Confirmed |
| **Queue** | AWS SQS | KEEP | Managed, no ops; covered by credits. Wired in Step 2h — `backend/workers/queue_client.py` async-wraps boto3 via `asyncio.to_thread`; LocalStack for dev, real AWS in prod via empty `SQS_ENDPOINT_URL` → default credential chain | ✅ Phase 2 (Step 2h) |
| **SQS Client (async wrap)** | `boto3>=1.34` in `requirements.txt` | ADD | Official AWS SDK. Wrapped in `asyncio.to_thread` to live inside async workers without aioboto3 dep overhead — throughput matters at tens-of-thousands msgs/hour, which is well beyond MVP scale | ✅ Phase 2 (Step 2h) |
| **Local Dev** | Docker Compose | ADD | PostgreSQL+TimescaleDB + Test DB + Redis (Day 1) + LocalStack (Step 2h, SQS only) | ✅ Day 1 + Step 2h |
| **Auth** | Clerk | KEEP | Existing Pro sub; handles users + API keys. **MCP server** for dev inspection | ✅ Confirmed |

### AI & ML

| Category | Tool | Action | Reason | Status |
|----------|------|--------|--------|--------|
| **AI Primary** | Claude API (Sonnet + Opus) | KEEP | YC credits; Sonnet for tasks, Opus for Watchdog self-healing | ✅ Confirmed |
| **AI Fallback** | OpenAI GPT-4o-mini | KEEP | YC credits; fallback when Claude fails | ✅ Confirmed |
| **AI Structured Output** | Instructor library | KEEP | Pydantic model validation for LLM responses | ⬜ Phase 3 |
| **Scraper AI (Watchdog)** | Claude Opus via `anthropic` SDK | ADD | Watchdog self-healing agent. Highest quality selector rediscovery; YC credits make cost viable. Nightly via `scripts/run_watchdog.py --check-all`; `backend/workers/watchdog.py::WatchdogSupervisor` dispatches heal prompts from `backend/ai/prompts/watchdog_heal.py` | ✅ Phase 2 (Step 2a) |
| **Extraction Parsing** | Qwen Flash or ERNIE | ADD | Parsing scraped page content into structured data | ⬜ Phase 2 |
| **Price Prediction** | Prophet (Meta) | KEEP | Python-native time-series forecasting; lightweight | ⬜ Phase 4 |
| **AI Orchestration** | LangChain | DROP | Overkill for direct API calls; Instructor sufficient | — |

### Web Scraping & Data

| Category | Tool | Action | Reason | Status |
|----------|------|--------|--------|--------|
| **Primary Scraping** | agent-browser | ADD | CLI tool controlling Chrome via CDP. DOM eval pattern wins every test (avg 515ms, Grade A quality). Replaces Playwright for all scraping | ✅ Confirmed |
| **Playwright** | Playwright | DROP | agent-browser's DOM eval outperforms on all tested sites. Shell-scriptable, better anti-detection | — |
| **Firecrawl** | Firecrawl v2 (`/v1/scrape` with `rawHtml` + `country=US`) | ADD | Live path for Walmart scraping via `backend/modules/m2_prices/adapters/walmart_firecrawl.py` (post-Step-2a paradigm shift — PerimeterX defeats headless Chromium, `__NEXT_DATA__` is already server-rendered). Also retains its original role as last-resort fallback for other retailers if Watchdog heal fails | ✅ Phase 2 (Step 2a paradigm shift) |
| **HTML Parsing** | BeautifulSoup 4 | ADD | `backend/workers/portal_rates.py` parses Rakuten / TopCashBack / BeFrugal via stable-attribute selectors (not hash-based CSS classes). Deliberately chosen over agent-browser for portal rate pages since they're static-enough HTML tables — no JS rendering needed, no coupling to scraper containers | ✅ Phase 2 (Step 2h) |
| **SQS Test Mocking** | `moto[sqs]>=5.0` in `requirements-test.txt` | ADD | Stubs boto3 at the transport layer — hermetic worker tests with zero LocalStack dependency. Tests use `with mock_aws():` and force `SQSClient(endpoint_url=None)` via the `_UNSET` sentinel to bypass the `.env` LocalStack override. Swap to live LocalStack for manual smoke (`docker compose up -d localstack && python3 scripts/run_worker.py setup-queues`) | ✅ Phase 2 (Step 2h) |
| **Browser Use** | Browser Use | DROP | Fully replaced by agent-browser for all scraping + Watchdog healing | — |
| **Semantic Search** | Exa | ADD | YC credits; find retailer discount program pages | ⬜ Phase 2 |
| **PDF Extraction** | Reducto | ADD | YC credits; card benefit docs, fee schedules | ⬜ Phase 4+ |
| **Scrapy** | Scrapy | DROP | agent-browser covers all use cases | — |
| **Bright Data** | Bright Data | DROP | Too expensive for MVP; agent-browser + residential proxy sufficient | — |
| **Paid Aggregator APIs** | ShopSavvy, Zinc, BlueCart, etc. | DROP | No paid aggregator APIs. Free APIs + agent-browser containers only | — |

### Retail Data APIs

| Category | Tool | Action | Reason | Status |
|----------|------|--------|--------|--------|
| **Amazon Pricing** | Keepa API ($15/mo) | DEFER | Amazon PA-API deprecated April 30, 2026. Keepa has no sales gate, includes historical data. Demo uses agent-browser scraper; Keepa added as production speed optimization | ⬜ Phase 4 (production) |
| **Amazon PA-API** | Amazon Product Advertising API | DROP | Deprecated April 30, 2026. Replacement (Creators API) requires 10 qualified sales/month to access | — |
| **Amazon Creators API** | Amazon Creators API | FUTURE | Add when 10 sales/month sustained. Keep Keepa as fallback for historical data | 🔮 Post-launch |
| **Best Buy** | Best Buy Products API (free) | DEFER | Cleanest retailer API. Demo uses agent-browser scraper; API added as production speed optimization | ⬜ Phase 4 (production) |
| **eBay Data** | eBay Browse API (free) | DEFER | Product search + pricing. Demo uses agent-browser scraper; API added as production speed optimization | ⬜ Phase 4 (production) |
| **10 Demo Retailers (non-walmart)** | agent-browser containers | ADD | Amazon, Best Buy, Target, Home Depot, Lowe's, eBay (new + used), Sam's Club, BackMarket, Facebook Marketplace — all scraped via containers, unchanged since Phase 1 | ✅ Phase 1 |
| **Walmart (demo)** | Firecrawl managed scraper API | ADD | Post-Step-2a paradigm shift: walmart's PerimeterX defeats headless Chromium regardless of IP. `WALMART_ADAPTER=firecrawl` routes walmart through `backend/modules/m2_prices/adapters/walmart_firecrawl.py` which calls Firecrawl's `POST /v1/scrape` with `rawHtml` format + US geo-targeting. Parses `__NEXT_DATA__` for product list | ✅ Post-Step-2a |
| **Walmart (production)** | Decodo rotating residential proxy | ADD | Post-demo switch: `WALMART_ADAPTER=decodo_http` routes through `backend/modules/m2_prices/adapters/walmart_http.py`. Same parser as the Firecrawl path, just a direct httpx request through `gate.decodo.com:7000` with auto-prefixed `user-<name>-country-us`. ~2.7× cheaper than Firecrawl per request, no concurrency cap. 5/5 clean on probe (2026-04-10) | ⬜ Phase 2 (flip post-demo) |
| **UPC Lookup (primary)** | Gemini API | ADD | Cost-effective UPC→product resolution (OpenAI charges $10/1K — unacceptable). High accuracy, 4-6s latency. YC credits cover cost. Goes through ai/abstraction.py | ⬜ Phase 1 |
| **UPC Lookup (backup)** | UPCitemdb API | BACKUP | Free tier: 100/day. Fallback when Gemini fails or for validation. Paid tier ($10/mo, 1,500/day) available if needed | ⬜ Phase 1 |
| **Food Items** | Open Food Facts | DEFER | Free, no API key needed. Supplement for grocery/food items. Not relevant for Phase 1 electronics categories | 🔮 When grocery categories added |
| **Price History** | Keepa API | KEEP | Amazon historical data for prediction model | ⬜ Phase 4 (production speed + prediction) |

### iOS

| Category | Tool | Action | Reason | Status |
|----------|------|--------|--------|--------|
| **iOS Barcode** | AVFoundation | KEEP | Native iOS since iOS 7; no dependency needed | ✅ Confirmed |
| **iOS OCR** | Vision framework (VNRecognizeTextRequest) | KEEP | Native iOS 13+ OCR for receipt text extraction on-device | ⬜ Phase 3 |
| **iOS Document Camera** | VisionKit (VNDocumentCameraViewController) | KEEP | Native iOS 13+ document capture UI | ⬜ Phase 3 |
| **iOS Live Scanner** | VisionKit (DataScannerViewController) | KEEP | Native iOS 16+ live text/barcode recognition. Requires A12+ | ⬜ Phase 3 |
| **iOS Subscription** | StoreKit 2 via RevenueCat (purchases-ios-spm v5.67.2) + RevenueCatUI | KEEP | RevenueCat simplifies StoreKit for solo dev; free tier covers MVP. Built-in `PaywallView` + `CustomerCenterView` so dashboard owns layout | ✅ Phase 2 (Step 2f) |
| **iOS In-App Browser** | SFSafariViewController via SwiftUI `UIViewControllerRepresentable` (Apple SDK) | KEEP | Shares cookies with Safari so affiliate tracking cookies persist. Built-in nav bar, reader mode, TLS padlock. Chosen over `WKWebView` (isolated data store → unreliable affiliate attribution) | ✅ Phase 2 (Step 2g) |
| **Affiliate URL Router** | Custom `backend/modules/m12_affiliate` (pure-Python, zero dependencies) | ADD | Deterministic URL construction for Amazon Associates / eBay Partner Network / Walmart Impact Radius. `AffiliateService.build_affiliate_url` is a pure `@staticmethod` — no DB, no SDK, no LLM | ✅ Phase 2 (Step 2g) |
| **iOS Networking** | URLSession | KEEP | Native; async/await; no dependency needed | ✅ Confirmed |
| **iOS Image Loading** | AsyncImage | KEEP | Native; sufficient for product images | ✅ Confirmed |

### Development Tooling

| Category | Tool | Type | When |
|----------|------|------|------|
| **PostgreSQL+TimescaleDB** | Docker container | MCP Server | Day 1 |
| **Redis** | Docker container | MCP Server | Day 1 |
| **LocalStack** | Docker container (SQS only) | Docker compose service | ✅ Phase 2 (Step 2h) — `localstack/localstack:3`, port 4566, `SERVICES=sqs`, healthcheck via `curl /_localstack/health` |
| **Context7** | Standalone | MCP Server | Day 1 (always on) |
| **Clerk** | Standalone | MCP Server | Before Step 1a |
| **XcodeBuildMCP** | Standalone | MCP Server | Step 1d (iOS) |
| **`gh`** (GitHub CLI) | Homebrew | CLI | Day 1 |
| **`docker`** + **`docker compose`** | Docker Desktop | CLI | Day 1 |
| **`aws`** (AWS CLI v2) | Homebrew | CLI | Before first deploy |
| **`railway`** | npm global | CLI | Before first deploy |
| **`alembic`** | pip (in requirements) | CLI | Step 1a |
| **`ruff`** | pip (in requirements) | CLI | Step 1a |
| **`pytest`** | pip (in requirements) | CLI | Step 1a |
| **`swiftlint`** | Homebrew | CLI | Step 1d |
| **`xcodes`** | Homebrew | CLI | Day 1 |
| **`jq`** | Homebrew | CLI | Day 1 |
| **`fastlane`** | Homebrew | CLI | Phase 4 (deferred) |
| **`vercel`** | npm global | CLI | Phase 5 (deferred) |

### Monitoring & Ops

| Category | Tool | Action | Reason | Status |
|----------|------|--------|--------|--------|
| **Error Tracking** | Sentry (or Firebase Crashlytics) | ADD | Error tracking before public beta | ⬜ Phase 4 |
| **Monitoring** | AWS CloudWatch | KEEP | Covered by credits; logs + metrics | ⬜ Phase 2+ |
| **Push Notifications** | AWS SNS + APNs | KEEP | Push infrastructure | ⬜ Phase 5 |

---

## Evaluated and Dropped (with reasoning)

| Tool | Category | Why Dropped | Date |
|------|----------|-------------|------|
| Django REST | Backend | Too heavy for API-only; ORM overhead | Mar 2026 |
| Celery | Task queue | Too complex for solo dev; SQS + scripts simpler | Mar 2026 |
| LangChain | AI orchestration | Overkill; direct API calls + Instructor sufficient | Mar 2026 |
| Playwright | Web scraping | agent-browser DOM eval outperforms on all tested sites (35+ tests, 100+ requests). Shell-scriptable, better anti-detection | Apr 2026 |
| Scrapy | Web scraping | agent-browser covers all use cases | Mar 2026 |
| Bright Data | Proxy service | Too expensive for MVP | Mar 2026 |
| ShopSavvy/Zinc/BlueCart | Aggregator APIs | No paid aggregator APIs policy. Free APIs + agent-browser sufficient | Apr 2026 |
| Amazon PA-API | Product data | Deprecated April 30, 2026. Creators API requires 10 sales/month | Apr 2026 |
| ML Kit | Barcode scanning | Adds Google dependency; AVFoundation native and sufficient | Mar 2026 |
| Alamofire | iOS networking | URLSession async/await covers all needs | Mar 2026 |
| xcbeautify | Build output | XcodeBuildMCP handles structured build/test output natively | Apr 2026 |
| Browser Use | Web scraping/probing | agent-browser fully replaced all scraping + Watchdog healing. Browser Use was backup but never needed | Apr 2026 |
| Claude Haiku | AI (cheap tasks) | Replaced by tiered strategy: Opus for Watchdog, Sonnet for quality, Qwen/ERNIE for parsing | Apr 2026 |
| DeepSeek V4 / MiniMax M2.7 | Watchdog AI | Claude Opus selected for Watchdog self-healing — highest quality selector rediscovery, YC credits cover cost | Apr 2026 |
| UPCitemdb (as primary) | UPC lookup | Free tier (100/day) insufficient as primary. Kept as backup behind Gemini API | Apr 2026 |
| OpenAI API (for UPC) | UPC lookup | $10 per 1,000 calls — unacceptable cost for barcode lookups. Gemini API is far more cost-effective | Apr 2026 |
| GitHub MCP | Repo management | `gh` CLI does everything the MCP does and is more portable | Apr 2026 |
| Custom skills/slash commands | Dev workflow | Guiding docs are the single source of truth; skills would duplicate and diverge | Apr 2026 |
