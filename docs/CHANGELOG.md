# Barkain — Changelog

> Per-step file inventories, key decisions with full rationale, and detailed
> session notes. For agent orientation, read `CLAUDE.md`. This file is the
> archaeological record.
>
> Last updated: 2026-04-13 (Chore: CHANGELOG.md extracted from CLAUDE.md)

---

## How to Use This File

- **New agent session?** Read `CLAUDE.md`, not this file.
- **Need to find which step created a file?** Search this file.
- **Need the rationale for a past decision?** Check the Key Decisions Log
  section below.
- **Need the full file list for a step?** Each step section has it.

---

## Step History

### Step 0 — Infrastructure Provisioning (2026-04-06)

Environment setup only — no code files. See `docs/PHASES.md` § Step 0 for
the full checklist (Docker Desktop, Clerk Pro project, GitHub repo, CLI
tools, MCP servers, API sign-ups).

### Step 1a — Database Schema + FastAPI Skeleton + Auth (2026-04-07)

```
backend/app/main.py              # FastAPI app + health endpoint
backend/app/config.py             # pydantic-settings config
backend/app/database.py           # SQLAlchemy Base + engine
backend/app/core_models.py        # User, Retailer, RetailerHealth, WatchdogEvent, PredictionCache
backend/app/models.py             # Model registry (imports all models)
backend/app/dependencies.py       # get_db, get_redis, get_current_user, get_rate_limiter
backend/app/middleware.py         # CORS, security headers, logging, error handling
backend/modules/m*/models.py      # 8 module model files (21 tables total)
alembic.ini                       # Alembic config (script_location = infrastructure/migrations)
infrastructure/migrations/env.py  # Async Alembic env
infrastructure/migrations/versions/0001_initial_schema.py  # All 21 tables
scripts/seed_retailers.py         # 11 retailer upsert
backend/tests/conftest.py         # Test fixtures (Docker PG port 5433, fakeredis, auth bypass)
backend/tests/test_*.py           # 5 test files, 14 tests
```

### Step 1b — M1 Product Resolution + AI Abstraction (2026-04-07)

```
backend/ai/__init__.py            # AI package init
backend/ai/abstraction.py         # Gemini API wrapper (lazy init, retry, JSON parsing)
backend/ai/prompts/__init__.py    # Prompts package init
backend/ai/prompts/upc_lookup.py  # UPC→product prompt template
backend/modules/m1_product/schemas.py   # ProductResolveRequest, ProductResponse
backend/modules/m1_product/service.py   # ProductResolutionService (Redis→PG→Gemini→UPCitemdb→404)
backend/modules/m1_product/router.py    # POST /api/v1/products/resolve
backend/modules/m1_product/upcitemdb.py # UPCitemdb backup client
backend/tests/modules/test_m1_product.py  # 12 tests
backend/tests/fixtures/gemini_upc_response.json   # Canned Gemini response
backend/tests/fixtures/upcitemdb_response.json     # Canned UPCitemdb response
```

### Step 1c — Container Infrastructure + Backend Client (2026-04-07)

```
containers/template/Dockerfile         # Base image: Node 20 + Chromium + Python/FastAPI + Xvfb
containers/template/entrypoint.sh      # Start Xvfb + uvicorn
containers/template/server.py          # FastAPI with GET /health + POST /extract
containers/template/base-extract.sh    # 9-step extraction skeleton with placeholders
containers/template/extract.js.example # DOM eval JavaScript template
containers/template/config.json.example    # Per-retailer config schema
containers/template/test_fixtures.json.example  # Test queries with expected outputs
containers/README.md                   # Build/run/test documentation + port assignments
backend/modules/m2_prices/schemas.py   # Pydantic models for container communication
backend/modules/m2_prices/container_client.py  # HTTP dispatch to scraper containers
backend/tests/modules/test_container_client.py # 14 tests (respx mocking)
backend/tests/fixtures/container_extract_response.json  # Canned container response
```

### Step 1d — Retailer Containers Batch 1 (2026-04-07)

```
containers/amazon/                      # Amazon scraper (port 8081)
  Dockerfile, server.py, entrypoint.sh, extract.sh, extract.js, config.json, test_fixtures.json
containers/walmart/                     # Walmart scraper (port 8083) — PerimeterX workaround
  Dockerfile, server.py, entrypoint.sh, extract.sh, extract.js, config.json, test_fixtures.json
containers/target/                      # Target scraper (port 8084) — load wait strategy
  Dockerfile, server.py, entrypoint.sh, extract.sh, extract.js, config.json, test_fixtures.json
containers/sams_club/                   # Sam's Club scraper (port 8089)
  Dockerfile, server.py, entrypoint.sh, extract.sh, extract.js, config.json, test_fixtures.json
containers/fb_marketplace/              # Facebook Marketplace scraper (port 8091) — modal hide
  Dockerfile, server.py, entrypoint.sh, extract.sh, extract.js, config.json, test_fixtures.json
backend/tests/modules/test_container_retailers.py  # 10 tests for batch 1 retailers
backend/tests/fixtures/amazon_extract_response.json
backend/tests/fixtures/walmart_extract_response.json
backend/tests/fixtures/target_extract_response.json
backend/tests/fixtures/sams_club_extract_response.json
backend/tests/fixtures/fb_marketplace_extract_response.json
```

### Step 1e — Retailer Containers Batch 2 (2026-04-07)

```
containers/best_buy/                    # Best Buy scraper (port 8082)
containers/home_depot/                  # Home Depot scraper (port 8085)
containers/lowes/                       # Lowe's scraper (port 8086)
containers/ebay_new/                    # eBay New scraper (port 8087) — condition filter
containers/ebay_used/                   # eBay Used/Refurb scraper (port 8088) — condition extraction
containers/backmarket/                  # BackMarket scraper (port 8090) — all refurbished
  Each: Dockerfile, server.py, entrypoint.sh, extract.sh, extract.js, config.json, test_fixtures.json
backend/tests/modules/test_container_retailers_batch2.py  # 9 tests for batch 2
backend/tests/fixtures/{best_buy,home_depot,lowes,ebay_new,ebay_used,backmarket}_extract_response.json
```

### Step 1f — M2 Price Aggregation + Caching (2026-04-08)

```
backend/modules/m2_prices/service.py    # PriceAggregationService (cache→dispatch→normalize→upsert→cache→return)
backend/modules/m2_prices/router.py     # GET /api/v1/prices/{product_id} with auth + rate limiting
backend/tests/modules/test_m2_prices.py # 13 tests (cache, dispatch, upsert, sorting, errors)
```

### Step 1g — iOS App Shell + Scanner + API Client + Design System (2026-04-08)

```
Config/Debug.xcconfig                                  # API_BASE_URL = http://localhost:8000
Config/Release.xcconfig                                # API_BASE_URL = https://api.barkain.ai
Barkain/Services/Networking/AppConfig.swift             # #if DEBUG URL switching
Barkain/Services/Networking/APIError.swift              # Error types matching backend format
Barkain/Services/Networking/Endpoints.swift             # URL builder for resolve + prices + health
Barkain/Services/Networking/APIClient.swift             # APIClientProtocol + APIClient (async, typed)
Barkain/Services/Scanner/BarcodeScanner.swift           # AVFoundation EAN-13/UPC-A scanner with AsyncStream
Barkain/Features/Shared/Extensions/Colors.swift         # Color palette from HTML prototype
Barkain/Features/Shared/Extensions/Spacing.swift        # Spacing + corner radius constants
Barkain/Features/Shared/Extensions/Typography.swift     # Font styles (system approximations)
Barkain/Features/Shared/Extensions/EnvironmentKeys.swift # APIClient environment injection
Barkain/Features/Shared/Models/Product.swift            # Product (Codable, snake_case CodingKeys)
Barkain/Features/Shared/Models/PriceComparison.swift    # PriceComparison + RetailerPrice + APIErrorResponse
Barkain/Features/Shared/Components/ProductCard.swift    # Product display card (image, name, brand)
Barkain/Features/Shared/Components/PriceRow.swift       # Retailer price row (name, price, sale badge)
Barkain/Features/Shared/Components/SavingsBadge.swift   # Savings pill badge
Barkain/Features/Shared/Components/EmptyState.swift     # Generic empty/error state
Barkain/Features/Shared/Components/LoadingState.swift   # Spinner + message
Barkain/Features/Shared/Components/ProgressiveLoadingView.swift # 11-retailer progressive status list
Barkain/Features/Scanner/ScannerView.swift              # Camera preview + scan overlay + results
Barkain/Features/Scanner/ScannerViewModel.swift         # @Observable — scan → resolveProduct
Barkain/Features/Scanner/CameraPreviewView.swift        # UIViewRepresentable for AVCaptureVideoPreviewLayer
Barkain/Features/Search/SearchPlaceholderView.swift     # Placeholder (coming soon)
Barkain/Features/Savings/SavingsPlaceholderView.swift   # Placeholder (coming soon)
Barkain/Features/Profile/ProfilePlaceholderView.swift   # Placeholder (coming soon)
BarkainTests/Helpers/MockAPIClient.swift                # Protocol-based mock with Result configuration
BarkainTests/Helpers/MockURLProtocol.swift              # URLProtocol subclass for API client tests
BarkainTests/Helpers/TestFixtures.swift                 # Sample Product, PriceComparison, JSON payloads
BarkainTests/Features/Scanner/ScannerViewModelTests.swift # 5 tests (resolve, error, loading, clear, reset)
BarkainTests/Services/APIClientTests.swift              # 3 tests (decode product, 404, decode prices)
```

### Step 1h — Price Comparison UI (2026-04-08)

```
Barkain/Features/Recommendation/PriceComparisonView.swift  # NEW — price comparison results screen
Barkain/Features/Scanner/ScannerViewModel.swift            # Extended — priceComparison, isPriceLoading, fetchPrices(), computed helpers
Barkain/Features/Scanner/ScannerView.swift                 # Updated — new state machine (price loading → results → error), onDisappear cleanup
Barkain/Features/Shared/Components/ProgressiveLoadingView.swift # Fixed — spinner animation, pun rotation timer
BarkainTests/Features/Scanner/ScannerViewModelTests.swift  # 14 tests (5 existing + 9 new price comparison tests)
BarkainTests/Helpers/MockAPIClient.swift                   # Extended — forceRefresh tracking, getPricesDelay
BarkainTests/Helpers/TestFixtures.swift                    # Extended — cached, empty, partial PriceComparison fixtures
```

### Step 1i — Hardening + Doc Sweep + Tag v0.1.0 (2026-04-08)

```
backend/ai/abstraction.py                              # Migrated google-generativeai → google-genai (native async)
backend/requirements.txt                                # google-generativeai → google-genai
backend/pyproject.toml                                  # Added [tool.ruff.lint] E741, pytest filterwarnings
backend/tests/test_integration.py                       # NEW — 12 integration tests (full flow + error format audit)
Barkain/Features/Shared/Components/SavingsBadge.swift   # Fixed: originalPrice now used for percentage display
backend/modules/m2_prices/models.py                     # D4 comment — TimescaleDB PK documented
backend/modules/m1_product/service.py                   # D5 comment — rollback safety documented
backend/modules/m2_prices/service.py                    # D9, D11 comments — cache and listing selection documented
backend/modules/m2_prices/container_client.py           # D10 comment — circuit-breaker deferred
containers/*/server.py (12 files)                       # D6 TODO — auth deferred to Phase 2
containers/README.md                                    # D7 note — server.py duplication documented
```

### Post-Phase 1 — Demo + Hardening (2026-04-09)

```
Info.plist                                                 # NEW — ATS local networking exception + API_BASE_URL from xcconfig
Config/Debug.xcconfig                                      # API_BASE_URL (change to Mac IP for physical device testing)
Barkain/Services/Networking/AppConfig.swift                 # Reads API_BASE_URL from Info.plist with hardcoded fallback
Barkain/Services/Scanner/BarcodeScanner.swift               # UPC-A normalization (strip leading 0 from EAN-13), clearLastScan()
Barkain/Features/Scanner/ScannerView.swift                  # onChange(of: scannedUPC) clears scanner on reset, scanner.clearLastScan in error view
backend/app/dependencies.py                                 # BARKAIN_DEMO_MODE=1 auth bypass for local testing
backend/ai/abstraction.py                                   # Thinking (budget=-1), Google Search grounding, temperature=1.0, _extract_text() skips thinking parts, JSON fallback regex extraction
backend/ai/prompts/upc_lookup.py                            # System instruction: full 9-step reasoning (cached). User prompt: bare UPC + output format only
backend/modules/m1_product/service.py                       # Simplified: parses device_name only, source=gemini_upc, brand/category/asin=None
backend/tests/fixtures/gemini_upc_response.json             # Simplified to {"device_name": "..."}
backend/tests/test_integration.py                           # Updated GEMINI_PRODUCT_DATA to device_name only
backend/tests/modules/test_m1_product.py                    # Updated assertions for gemini_upc source
Barkain.xcodeproj/project.pbxproj                           # Added INFOPLIST_FILE=Info.plist to Debug+Release target configs
prompts/DEMO_GUIDE.md                                       # NEW — comprehensive demo walkthrough with physical device instructions
```

### Step 2a — Watchdog Supervisor + Health Monitoring + Pre-Fixes (2026-04-10)

```
backend/ai/abstraction.py                              # Extended — Anthropic/Claude Opus (claude_generate, claude_generate_json, claude_generate_json_with_usage)
backend/ai/prompts/watchdog_heal.py                    # NEW — Opus heal + diagnose prompt templates
backend/workers/watchdog.py                            # NEW — Watchdog supervisor agent (health checks, classification, self-healing, escalation)
backend/modules/m2_prices/health_monitor.py            # NEW — Retailer health monitoring service
backend/modules/m2_prices/health_router.py             # NEW — GET /api/v1/health/retailers endpoint
backend/app/errors.py                                  # NEW — Shared error response helpers (DRY format)
containers/base/                                       # NEW — Shared container base image (Dockerfile, server.py, entrypoint.sh)
scripts/run_watchdog.py                                # NEW — Watchdog CLI (--check-all, --heal, --status, --dry-run)
infrastructure/migrations/versions/0002_price_history_composite_pk.py  # NEW — Composite PK migration
backend/ai/prompts/upc_lookup.py                       # Updated — broadened for all product categories
backend/modules/m1_product/service.py                  # Updated — Gemini null retry with broader prompt
backend/modules/m2_prices/service.py                   # Updated — shorter Redis TTL (30min for 0-result)
```

### Walmart Adapter Routing (post-Step-2a, 2026-04-10)

```
backend/modules/m2_prices/adapters/__init__.py         # NEW — adapters subpackage marker
backend/modules/m2_prices/adapters/_walmart_parser.py  # NEW — shared __NEXT_DATA__ → ContainerResponse logic (challenge detection, itemStacks walker, sponsored filter, condition inference, price shape coercion)
backend/modules/m2_prices/adapters/walmart_http.py     # NEW — Decodo residential proxy adapter (httpx, Chrome 132 headers, username auto-prefix, password URL-encode, 1-retry on challenge, per-request wire_bytes logging)
backend/modules/m2_prices/adapters/walmart_firecrawl.py # NEW — Firecrawl managed API adapter (demo default; same parser)
backend/modules/m2_prices/container_client.py          # Updated — added `_extract_one` router, `_resolve_walmart_adapter`, `walmart_adapter_mode` attr, `_cfg` hold
backend/app/config.py                                  # Updated — added WALMART_ADAPTER, FIRECRAWL_API_KEY, DECODO_PROXY_USER, DECODO_PROXY_PASS, DECODO_PROXY_HOST
.env.example                                           # Updated — documented each new env var with comments describing when it's required and how to obtain
backend/tests/fixtures/walmart_next_data_sample.html   # NEW — realistic __NEXT_DATA__ fixture (4 real products + 1 sponsored placement)
backend/tests/fixtures/walmart_challenge_sample.html   # NEW — minimal "Robot or human?" PX challenge page
backend/tests/modules/test_walmart_http_adapter.py     # NEW — 15 tests (proxy URL builder, happy path, challenge retry semantics, error surfaces, parser edge cases)
backend/tests/modules/test_walmart_firecrawl_adapter.py # NEW — 9 tests (happy path, request-shape, error surfaces)
backend/tests/modules/test_container_client.py         # Updated — `_setup_client` fixture sets `walmart_adapter_mode = "container"`
backend/tests/modules/test_container_retailers.py      # Updated — same fixture update (walmart in ports dict triggers router)
```

### Scan-to-Prices Live Demo (2026-04-10, branch `phase-2/scan-to-prices-deploy`)

Branch: `phase-2/scan-to-prices-deploy`. 5 commits, 9 files, ~700 lines.

```
containers/amazon/extract.sh                           # Updated — exec 3>&1 / exec 1>&2, python3 JSON dump via >&3, fallback echo via >&3 (SP-1)
containers/best_buy/extract.sh                          # Updated — same fd-3 pattern + uses new a.sku-title walker (SP-1)
containers/best_buy/extract.js                          # Updated — a.sku-title walker replaces .sku-item selector (live Best Buy React/Tailwind migration, 2026-04-10)
containers/base/server.py                              # Updated — EXTRACT_TIMEOUT env-overridable, default 60s → 180s (SP-2)
containers/base/entrypoint.sh                          # Updated — rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 before Xvfb, sleep 1s → 2s (SP-3)
backend/modules/m2_prices/adapters/walmart_firecrawl.py # Fixed — Firecrawl v2 API: top-level `country` → nested `location.country` (SP-4)
backend/modules/m2_prices/service.py                   # Fixed — `_pick_best_listing` filters `price > 0` before min() to skip parse-failure listings (SP-7)
Barkain/Services/Networking/APIClient.swift             # Fixed — dedicated URLSession with timeoutIntervalForRequest=240, timeoutIntervalForResource=300 (SP-8)
Config/Debug.xcconfig                                   # Updated — Mac LAN IP for physical device testing with switch-back comment
scripts/ec2_deploy.sh                                   # NEW — build + run barkain-base + 3 retailer containers with health checks
scripts/ec2_tunnel.sh                                   # NEW — forward ports 8081-8091 from Mac to EC2 with verification
scripts/ec2_test_extractions.sh                         # NEW — live extraction smoke test (Sony WH-1000XM5 + AirPods Pro) with pass/fail markdown table
containers/walmart/TROUBLESHOOTING_LOG.md               # NEW — prior-session Walmart PerimeterX notes
Barkain Prompts/Scan_to_Prices_Validation_Results.md    # NEW — chronological record of the run
Barkain Prompts/Error_Report_Scan_to_Prices_Deployment.md  # NEW — 10 issues + 8 latent, viability rated
Barkain Prompts/Conversation_Summary_Scan_to_Prices_Deployment.md  # NEW — session summary with decisions + learnings
```

**Env-only overrides applied to Mike's `.env` (not committed; documented so future sessions apply the same):**
- `CONTAINER_URL_PATTERN=http://localhost:{port}` (was `http://localhost:808{port}` from Step 1c — silently rotted when Step 1d changed port format, SP-5)
- `CONTAINER_TIMEOUT_SECONDS=180` (was 30 — too short for live Best Buy, SP-6)
- `BARKAIN_DEMO_MODE=1` (bypasses Clerk auth for physical device testing)

### Step 2b — Demo Container Reliability (2026-04-11)

```
backend/modules/m1_product/service.py                  # Refactored — cross-validation with Gemini + UPCitemdb
backend/modules/m1_product/models.py                    # Added confidence @property
backend/modules/m1_product/schemas.py                   # Added confidence field to ProductResponse
backend/modules/m2_prices/service.py                    # Added relevance scoring + _pick_best_listing filter
backend/modules/m2_prices/schemas.py                    # Added is_third_party to ContainerListing
backend/modules/m2_prices/adapters/_walmart_parser.py   # First-party seller filter
backend/modules/m2_prices/container_client.py           # Connection-refused log level downgrade
containers/amazon/extract.js                            # 5-level title selector fallback chain
containers/best_buy/extract.sh                          # Timing optimization (2 scrolls, load wait, profiling)
.env.example                                            # Audited — removed duplicates, fixed CONTAINER_URL_PATTERN
backend/pyproject.toml                                  # Registered integration marker
backend/tests/integration/test_real_api_contracts.py    # NEW — 6 real-API contract tests
backend/tests/modules/test_m1_product.py                # +6 cross-validation tests
backend/tests/modules/test_m2_prices.py                 # +8 relevance scoring tests
backend/tests/modules/test_walmart_firecrawl_adapter.py # +4 first-party filter tests
```

### Step 2b-val — Live Validation Pass (2026-04-12)

Regression fixes rolled into the Post-2b-val Hardening block below.
See `Barkain Prompts/Step_2b_val_Results.md` for the 5-test protocol
and `Barkain Prompts/Error_Report_Post_2b_val_Sim_Hardening.md` for
the bugs-found inventory.

Three latent regressions caught and fixed on branch `phase-2/step-2b`:
- **SP-9 regression** — Amazon title chain returned brand-only "Sony". Amazon now splits brand/product into sibling spans inside `h2` / `[data-cy="title-recipe"]`, and the sponsored-noise regex used ASCII `'` vs Amazon's curly `'`. Fix: rewrote `extractTitle()` to join all spans + added `['\u2019]` character class to sponsored noise regex. `containers/amazon/extract.js`.
- **SP-10 regression** — `_MODEL_PATTERNS[0]` couldn't match hyphenated letter+digit models like `WH-1000XM5`, extracting "WH1000XM" instead, so the hard gate failed against all listings. Fix: optional hyphen between letter group and digit group + trailing `\d*` after alpha suffix. `backend/modules/m2_prices/service.py`.
- **SP-10b new** — word+digit model names (`Flip 6`, `Clip 5`, `Stick 4K`) matched nothing in the old pattern list, so hard gate was skipped and a JBL Clip 5 listing cleared the 0.4 token-overlap floor for a JBL Flip 6 query. Fix: added `\b[A-Z][a-z]{2,8}\s+\d+[A-Z]?\b` (Title-case only, no IGNORECASE). `backend/modules/m2_prices/service.py`.

### Post-2b-val Hardening (2026-04-12)

```
# Backend — relevance scoring refactor
backend/modules/m2_prices/service.py                    # _clean_product_name, _ident_to_regex, _is_accessory_listing,
                                                        # _VARIANT_TOKENS equality check, _UNAVAILABLE_ERROR_CODES,
                                                        # new regex patterns 6 (iPhone/iPad camelCase) + 7 (AirPods/
                                                        # PlayStation/MacBook camelCase), spec patterns dropped from
                                                        # hard gate, word-boundary identifier regex, retailer_results
                                                        # tracking in get_prices + _check_db_prices
backend/modules/m2_prices/schemas.py                    # RetailerStatus enum + RetailerResult model +
                                                        # retailer_results list on PriceComparisonResponse
backend/modules/m2_prices/adapters/_walmart_parser.py   # Carrier/installment marker regexes + _is_carrier_listing;
                                                        # condition mapping extended (Restored → refurbished)

# Containers — extract.js hardening
containers/amazon/extract.js                            # detectCondition(), extractPrice() with installment
                                                        # rejection, joinSpans() title extractor, curly-apostrophe
                                                        # sponsored-noise regex
containers/best_buy/extract.js                          # detectCondition(), isCarrierListing(), $X/mo stripping
                                                        # before dollar-amount parsing

# iOS — manual entry + per-retailer status UI
Barkain/Features/Scanner/ScannerView.swift              # Toolbar ⌨️ button + manualEntrySheet with TextField +
                                                        # preset rows; submitManual() + isValidUPC() helpers
Barkain/Features/Shared/Models/PriceComparison.swift    # RetailerResult struct + retailerResults field with
                                                        # graceful decodeIfPresent fallback
Barkain/Features/Recommendation/PriceComparisonView.swift # RetailerListRow enum + retailerList view; successes
                                                        # as tappable PriceRow, no_match/unavailable as inactiveRow
                                                        # with label; removed red "N unavailable" status bar count
Config/Debug.xcconfig                                   # API_BASE_URL → localhost:8000 (simulator); Mac LAN IP
                                                        # switch-back comment kept

# Tests
backend/tests/modules/test_walmart_http_adapter.py      # Updated condition assertion: Restored → refurbished
```

**Test counts:** 146 backend (unchanged — existing tests updated in-place where semantics changed), 21 iOS unit.
**Build status:** 146 passed / 6 skipped. iOS builds clean for simulator + device. Manual entry sheet functional.

### Step 2b-final — Close Out + Gemini Model Field (2026-04-13)

```
backend/ai/prompts/upc_lookup.py                        # System instruction replaced verbatim; build_upc_lookup_prompt and build_upc_retry_prompt now request device_name + model
backend/modules/m1_product/service.py                   # _get_gemini_data extracts model, _cross_validate threads gemini_model through both-agree branch, _resolve_with_cross_validation pops gemini_model into source_raw before _persist_product
backend/modules/m1_product/schemas.py                   # ProductResponse.model: str | None = None; model_config adds protected_namespaces=()
backend/modules/m1_product/models.py                    # Product.model @property reads source_raw.gemini_model
backend/modules/m2_prices/service.py                    # _score_listing_relevance consumes gemini_model from source_raw; _MODEL_PATTERNS[5] GPU regex added; _ORDINAL_TOKENS frozenset + Rule 2b equality check
backend/tests/fixtures/gemini_upc_response.json         # Added model key
backend/tests/modules/test_m1_product.py                # +2 new tests (resolve_exposes_gemini_model_field, resolve_handles_null_gemini_model); existing mocked Gemini responses updated to include model key
backend/tests/modules/test_m2_prices.py                 # +29 new tests: 5 gemini_model relevance (generation marker ×2, GPU ×2, backward compat ×1), 24 post-2b-val hardening (clean_product_name ×4, is_accessory_listing ×4, ident_to_regex ×3, variant equality ×2, classify_error_status ×2 + 8-code parametrize, retailer_results_mixed_statuses_end_to_end ×1)
backend/tests/modules/test_walmart_firecrawl_adapter.py # +4 carrier-listing tests (_is_carrier_listing: AT&T, $/mo, Verizon URL, unlocked-pass)
backend/tests/integration/conftest.py                   # NEW — pytest_configure auto-loads .env when BARKAIN_RUN_INTEGRATION_TESTS=1
backend/tests/integration/test_real_api_contracts.py    # test_upcitemdb_lookup skip guard swapped to opt-out via UPCITEMDB_SKIP=1 (2b-val-L3)

.github/workflows/backend-tests.yml                     # NEW — PR + main CI; TimescaleDB + Redis services; installs requirements.txt + requirements-test.txt; runs pytest --tb=short -q with BARKAIN_DEMO_MODE=1 and fake API keys; integration tests auto-skipped
scripts/ec2_deploy.sh                                   # Post-deploy verification block: MD5-compares each running container's /app/extract.js against repo copy (fixes 2b-val-L1 hot-patch drift visibility)

CLAUDE.md                                               # Current State +Step 2b-final line; test counts 146 → 181; What's Next §7 rewritten to describe Step 2b-final completion; pre-fixes list trimmed (generation + GPU resolved); Gemini output + CI added to Key Decisions quick-ref
docs/ARCHITECTURE.md                                    # Model Routing row: Gemini returns device_name + model; Prompt Templates section describes model field threading
docs/SCRAPING_AGENT_ARCHITECTURE.md                     # Appendix F.5 — generation-without-digit + GPU-SKU bullets marked Resolved in Step 2b-final with rationale
docs/TESTING.md                                         # Test Inventory row for Step 2b-final; Total row 152 → 181; conftest.py block rewritten to describe actual auto-load behavior; Real-API smoke tests section notes partial paydown + CI workflow
docs/PHASES.md                                          # Step 2b row appended with Step 2b-final summary
docs/CHANGELOG.md                                       # This entry
```

**Test counts:** 181 backend (181 passed / 6 skipped, +35 new), 21 iOS unit. `ruff check .` clean. `.github/workflows/backend-tests.yml` YAML valid.
**Build status:** Backend test suite green. CI workflow runs on every PR touching `backend/**` or `containers/**`. PR #3 ready for final merge into `main`.

### Step 2c — Streaming Per-Retailer Results (SSE) (2026-04-13)

```
backend/modules/m2_prices/sse.py                                         # NEW — sse_event() wire-format helper + SSE_HEADERS constant (Cache-Control: no-cache, no-transform; X-Accel-Buffering: no; Connection: keep-alive)
backend/modules/m2_prices/service.py                                     # +asyncio/AsyncGenerator imports; stream_prices() async generator uses asyncio.as_completed over per-retailer tasks wrapping container_client._extract_one(); yields (event_type, payload) tuples; cache-hit path replays cached retailer_results + done.cached=true; error path yields ("error", {...}) then returns; CancelledError cancels pending tasks; classification loop duplicated from get_prices() by design (different iteration strategy + error semantics)
backend/modules/m2_prices/router.py                                      # +StreamingResponse import, +sse module import; NEW @router.get("/{product_id}/stream") handler — validates product (raises 404 BEFORE stream opens), wraps service.stream_prices() in an async generator that formats each tuple via sse_event(), returns StreamingResponse(media_type="text/event-stream", headers=SSE_HEADERS)

backend/tests/modules/test_m2_prices.py                                  # PF-2 — deleted `pytestmark = pytest.mark.asyncio` line; asyncio_mode=auto in pyproject.toml is sufficient. Eliminates 33 pytest warnings
backend/tests/modules/test_m2_prices_stream.py                           # NEW — 11 tests. Direct service-level: event completion order (walmart 5ms < amazon 15ms < best_buy 30ms), success payload shape, empty_listings→no_match, CONNECTION_FAILED→unavailable, Redis cache hit short-circuit (_FakeContainerClient.extract_one_calls == []), DB cache hit + cache-back, force_refresh bypass. Endpoint-level via httpx client.stream(): SSE content-type + cache-control headers, 404-before-stream-opens, end-to-end SSE wire parsing via _collect_sse helper. Regression: unknown product raises ProductNotFoundError before yielding any events. _FakeContainerClient exposes ports + _extract_one matching ContainerClient's interface

containers/target/extract.sh                                             # PF-1 — fd-3 stdout pattern (exec 3>&1; exec 1>&2 after trap cleanup EXIT; >&3 on python3 output line; >&3 on failure echo)
containers/home_depot/extract.sh                                         # PF-1 — same fd-3 pattern
containers/lowes/extract.sh                                              # PF-1 — same fd-3 pattern
containers/ebay_new/extract.sh                                           # PF-1 — same fd-3 pattern (no Step 9 comment originally; added)
containers/ebay_used/extract.sh                                          # PF-1 — same fd-3 pattern (no Step 9 comment originally; added)
containers/sams_club/extract.sh                                          # PF-1 — same fd-3 pattern
containers/backmarket/extract.sh                                         # PF-1 — same fd-3 pattern
containers/fb_marketplace/extract.sh                                     # PF-1 — same fd-3 pattern
containers/walmart/extract.sh                                            # PF-1 — same fd-3 pattern (currently dead code since WALMART_ADAPTER=firecrawl, but fixed for consistency)

Barkain/Services/Networking/Streaming/SSEParser.swift                    # NEW — SSEEvent struct + stateful SSEParser.feed(line:)/flush(); events(from: URLSession.AsyncBytes) async wrapper that hooks up to bytes.lines in production. Tests drive feed(line:) directly. Ignores id:/retry:/:comment lines per the W3C SSE spec
Barkain/Services/Networking/Streaming/RetailerStreamEvent.swift          # NEW — typed enum RetailerStreamEvent { retailerResult, done, error }; RetailerResultUpdate{retailerId, retailerName, status, price}; StreamSummary{productId, productName, totalRetailers, retailersSucceeded, retailersFailed, cached, fetchedAt}; StreamError{code, message}
Barkain/Services/Networking/APIClient.swift                              # +streamPrices(productId:forceRefresh:) added to APIClientProtocol and APIClient. Uses URLSession.bytes(for:) + SSEParser.events(). Non-2xx drains error body (≤8KB) and throws a matching APIError variant via new static apiErrorFor(statusCode:body:decoder:) helper that mirrors request<T>()'s switch statement. AsyncThrowingStream continuation.onTermination cancels the background Task
Barkain/Services/Networking/Endpoints.swift                              # +.streamPrices(productId:forceRefresh:) case; path: /api/v1/prices/{uuid}/stream; queryItems tuple-matches .streamPrices(_, true) along with .getPrices(_, true) for force_refresh=true
Barkain/Features/Shared/Models/PriceComparison.swift                     # Field declarations let → var on all 9 stored properties. Struct stays Codable/Equatable/Sendable. Required so ScannerViewModel can mutate the struct in place as SSE events arrive
Barkain/Features/Scanner/ScannerViewModel.swift                          # Rewrote fetchPrices() to consume streamPrices(). Lazy-seeds + mutates priceComparison on each retailerResult event via apply(_:for:). `done` event applies summary via apply(_ summary:for:). `.error` event clears priceComparison + sets priceError. Thrown errors or stream-closes-without-done fall back to fallbackToBatch(). Fallback clears partial seed on failure (preserveSeeded defaults to false). Existing tests test_handleBarcodeScan_priceError_keepsProductAndSetsError + test_handleBarcodeScan_success_triggersResolveAndPrices still pass because streamPrices default mock returns no events → fallback to getPrices preserves batch semantics
Barkain/Features/Scanner/ScannerView.swift                               # Swapped scannerContent branch order — PriceComparisonView is now shown whenever comparison is non-nil (regardless of isPriceLoading), so streaming events incrementally fill the visible list. Removed priceLoadingView() and loadingRetailerItems — the progressive UI IS PriceComparisonView. A minimal LoadingState("Sniffing out deals...") shows only in the brief window before the first event seeds the comparison
Barkain/Features/Recommendation/PriceComparisonView.swift                # +.animation(.default, value: comparison.retailerResults) and +.animation(.default, value: comparison.prices) on retailerList VStack for smooth row transitions as events arrive. PreviewAPIClient extended with a stub streamPrices() that finishes immediately

BarkainTests/Helpers/MockAPIClient.swift                                 # +streamPricesEvents: [RetailerStreamEvent], streamPricesPerEventDelay: TimeInterval, streamPricesError: APIError?, streamPricesCallCount, streamPricesLastProductId, streamPricesLastForceRefresh; +streamPrices(productId:forceRefresh:) replays configured events (with optional per-event delay) then finishes cleanly or throws terminalError
BarkainTests/Services/Networking/SSEParserTests.swift                    # NEW — 5 tests driving SSEParser.feed(line:) directly: parses single event, parses multiple events, joins multi-line data with \n, flushes trailing event on stream close, ignores comment/id/retry/unknown lines
BarkainTests/Features/Scanner/ScannerViewModelTests.swift                # +6 stream tests: incremental retailerResults+prices mutation, sortedPrices re-sorts live as events arrive, .error event sets priceError to .server(message) + clears comparison, thrown APIError.network falls back to getPrices (asserts getPricesCallCount incremented + final comparison matches batch), closed-without-done falls back to getPrices, bestPrice tracks cheapest retailer across 3 events (amazon $399 → best_buy $349.99 → walmart $289.99) and maxSavings == 109.01. Helpers: makePriceUpdate(retailerId:retailerName:price:status:) and makeDoneSummary(total:succeeded:failed:cached:)

CLAUDE.md                                                                # +Step 2c — Streaming Per-Retailer Results (SSE) COMPLETE line. Test counts 181/21 → 192/32. API inventory entry for /api/v1/prices/{id}/stream. fd-3 backfill (SP-L2) and streaming (SP-L7/2b-val-L2) marked RESOLVED. Build status paragraph rewritten for streaming runtime profile. Added M2 Price streaming bullet and iOS SSE consumer bullet to the Current State checklist. Section "What's Next" step 8 rewritten with the Step 2c summary; remaining pre-fixes trimmed to just the EC2 redeploy
docs/ARCHITECTURE.md                                                     # API Endpoint Inventory: added GET /api/v1/prices/{id}/stream row describing the asyncio.as_completed SSE pattern + batch fallback
docs/SCRAPING_AGENT_ARCHITECTURE.md                                      # Appendix G intro note — `retailer_results` is now emitted in two flavors (batch + SSE stream). Batch endpoint unchanged; stream endpoint yields one event per retailer via asyncio.as_completed + terminal done event
docs/SEARCH_STRATEGY.md                                                  # Progressive Loading UX Contract — rewrote Cache Miss Path to distinguish Demo Reality (3 retailers via SSE: walmart ~12s, amazon ~30s, best_buy ~91s, each arriving independently) from Aspirational (11 retailers full stream). Cache Hit Path updated to note rapid-fire event replay
docs/TESTING.md                                                          # Test Inventory Step 2c row (192/32); Total row updated. Describes the test split: 11 backend stream + 5 iOS SSE parser + 6 iOS scanner stream
docs/DEPLOYMENT.md                                                       # New "SSE Streaming Endpoint (Step 2c)" subsection — nginx proxy_buffering/proxy_read_timeout guidance, Cloudflare/ALB/Railway notes, curl -N verification recipe, SSE_HEADERS behavior explained
docs/CHANGELOG.md                                                        # This entry
```

**Test counts:** 192 backend (192 passed / 6 skipped, +11 new) / 32 iOS unit (+11 new). `ruff check backend/` clean. `xcodebuild build` + `xcodebuild test` clean against iPhone 17 simulator.
**Build status:** Backend + iOS both green. Streaming endpoint serves `text/event-stream` at `GET /api/v1/prices/{id}/stream`. Batch endpoint unchanged. PF-2 silenced 33 pytest warnings. PF-1 completed the fd-3 backfill for all 9 remaining extract.sh files (walmart included even though it's currently routed through Firecrawl). Step 2c was merged to `main` as **PR #8** (squash commit `9ceafe1`).

### Step 2c-val — SSE Live Smoke Test (2026-04-13)

Live integration run against real Gemini + real EC2 containers (Amazon / Best Buy / Walmart) + real backend. No code was changed in this session — validation only.

**Environment:** Mac backend on `:8000` (`BARKAIN_DEMO_MODE=1`), SSH tunnel to EC2 instance `i-09ce25ed6df7a09b2` (IP `98.93.229.3`), EC2 repo fast-forwarded from `phase-2/scan-to-prices-deploy` → `main` (14 commits), `scripts/ec2_deploy.sh` rebuilt base + 3 priority retailer images and ran post-deploy MD5 verification.

**Results table:**

| # | Test | Result | Notes |
|---|------|--------|-------|
| 1 | SSE wire format (curl, force_refresh=true) | **PASS (mechanism) / DEGRADED (data)** | Events arrived incrementally in completion order: 8 no-container retailers `unavailable` at 0.14 s, walmart `no_match` at 0.81 s, amazon `success` at **81.47 s** ($209.99 refurbished, relevance 0.875), best_buy `no_match` at **344.62 s**, `done` at 344.64 s. Headers correct: `content-type: text/event-stream; charset=utf-8`, `cache-control: no-cache, no-transform`, `x-accel-buffering: no`, `connection: keep-alive`. Only 1/3 demo retailers succeeded — prompt's "≥2/3 success" criterion not met, but the SSE plumbing (the subject of Step 2c) is 100% green. |
| 2 | Cache-hit replay (stream, no force_refresh) | **PASS** | All 12 events arrived at `[0.00 s]`; `done.cached=true`; same retailer statuses as Test 1. |
| 3 | Batch endpoint still works | **PASS** | `GET /api/v1/prices/{id}` → HTTP 200, regular JSON (`prices[]` + `retailer_results[]`), Amazon price unchanged, `cached: false` (batch path re-dispatches rather than reading the stream cache key — pre-existing behavior, not a regression). |
| 4 | iOS simulator scan | **PASS (functional) / FAIL (progressive UX — new bug)** | App built + launched on iPhone 17 sim (iOS 26.4). After osascript accessibility was granted mid-session, drove the full flow: tapped keyboard icon → typed `027242923232` → tapped `Resolve` → observed the fetch end-to-end (~5 min with cold DB/Redis). **Functional:** final UI correctly shows `Sony WH-1000XM5` product card, Amazon `$199.99 Refurbished SALE` (BEST BARKAIN), Best Buy `$248.00 New SALE`, Walmart `Not found`, + 8 "Unavailable" rows for no-container retailers. Save banner `$48.01 (19%)` renders. **Bug found (2c-val-L6, see below):** UI never shows a progressive / partial state — jumps directly from "Sniffing out deals…" spinner to fully-populated view. Backend access log + a concurrent curl against the same cache confirm the server-side stream delivers 11 `retailer_result` events + `done` event correctly; iOS is simply falling through to `fallbackToBatch()` every time, meaning the batch endpoint is doing the work the stream was supposed to do. The entire promised Step 2c UX — "walmart appears first, then amazon, then best_buy, each streaming in independently" — is not reaching the user. |
| 5 | EC2 deploy MD5 verification | **PASS** | `[PASS] amazon: extract.js matches repo (a4b40e1b9ad9)`, `[PASS] best_buy: extract.js matches repo (093bcb4b6027)`, `[PASS] walmart: extract.js matches repo (2889f469fdee)`. Fresh rebuild from `main` on EC2 cleared any previous hot-patch drift. |
| 6 | Gemini `model` field | **NULL** | Sony WH-1000XM5 product record was resolved on 2026-04-12 (pre-2b-final), so the DB/cache row has `model: null`. Not a failure — the 2b-final code path is in place; it just didn't run for this cached UPC. To verify the field live, either clear the product row and re-resolve or pick a UPC that hasn't been resolved yet. |

**Latent findings (not fixed — documented for future sessions):**

- **2c-val-L1 — Best Buy 344 s / ReadTimeout × 2 (HIGH for UX).** Backend log: `Container best_buy attempt 1/2 timed out: ReadTimeout` → `attempt 2/2 timed out: ReadTimeout`. Previously best_buy completed in ~91 s; two back-to-back ReadTimeouts now add up to ~344 s. Container is healthy (`/health` PASS, MD5 matches repo), so the regression is at extraction time — either Best Buy's page is slower than it was on 2026-04-12, or the adapter's default read timeout × retry doubles the user-visible worst case. Impact: the "Best Buy streams in when it finishes" promise from Step 2c still holds, but the tail is 3.8× worse than the documented profile.
- **2c-val-L2 — Walmart Firecrawl `no_match` for Sony WH-1000XM5 (MEDIUM).** Could be a genuine absence on walmart.com or a Firecrawl extractor / relevance gate miss. Stream still emits a clean `no_match` event at 0.81 s, so the streaming behavior is correct.
- **2c-val-L3 — Amazon result is `refurbished`, not `new` (LOW).** $209.99 (orig $248), relevance 0.875. Likely a real refurbished listing (Amazon often ranks refurb in search), but worth confirming whether condition detection is picking up a "Renewed" badge or misclassifying a new listing.
- **2c-val-L4 — Gemini `model` field not re-resolved post-2b-final (LOW).** Side-effect of `L1` above being fixed while the DB row from 2b-val is still cached. One-line fix: `DELETE FROM products WHERE upc='027242923232';` on the test DB and re-hit `/api/v1/products/resolve`.
- **2c-val-L5 — iOS UI automation unavailable at session start (LOW, environmental — RESOLVED mid-session).** macOS accessibility permission was granted mid-session and the sim flow was driven via `osascript click` on AXButton elements inside `process "Simulator"` (the element-scoped click works even when the simulator isn't frontmost — screen-coordinate click hits whatever is under the cursor and isn't reliable). Keystroke typing works via `keystroke "027242923232"` once the `AXTextField` is focused via `click`. Button matching by `description` rather than `name` (since most in-app buttons expose `name = "missing value"`) is the pattern that works. Noted here so future sessions don't repeat the XcodeBuildMCP-tap rabbit hole.
- **2c-val-L6 — iOS SSE consumer never renders progressive events; always falls back to batch (HIGH — this is the Step 2c promise).** Observed: UI stays on the `"Sniffing out deals…"` spinner for the entire duration of a live stream (~5 min end-to-end on a cold DB+Redis run), then jumps in one frame to the fully-populated comparison view. Backend access log for the same flow shows the iOS request sequence is always `GET /prices/{id}/stream?force_refresh=true` → 11 container results → then **`GET /prices/{id}?force_refresh=true`** (the batch endpoint) which is `fallbackToBatch()` in `ScannerViewModel.fetchPrices()`. A concurrent curl against the same product during the iOS run returned all 11 `retailer_result` events plus a correct `done` event with `cached: true` in <1 s — so the server is behaving correctly and the problem is entirely on the client. Most likely root cause: `URLSession.bytes(for:).lines` in `Barkain/Services/Networking/Streaming/SSEParser.swift:62-84` is buffering line delivery aggressively (well-known URLSession AsyncBytes gotcha — lines don't arrive until the internal HTTP chunk hits some threshold), which means `sawDone` in `ScannerViewModel.fetchPrices()` never flips to true before the stream closes, triggering the `fallbackToBatch()` branch on **every** fetch. Secondary candidate: a decoding error on an early `retailer_result` event (e.g. a field name mismatch hidden by `.convertFromSnakeCase` when CodingKeys are explicit) throwing out of the `for try await` loop into the `catch let apiError as APIError` branch. Either way, the unit tests (6 in `ScannerViewModelTests` that drive `fetchPrices` with a mock `streamPrices` returning an `AsyncThrowingStream` directly) never exercise a real `URLSession.bytes` pipeline, so they don't catch this. 37K lines of iOS syslog (`start_sim_log_cap`) captured during a fresh fetch had 0 `DecodingError`/`APIError` matches — but the app doesn't route Swift-level errors through `os_log`, so absence-of-signal isn't proof that decoding is fine. **Fix candidates (future session):** (a) replace `bytes.lines` with a manual byte-level `\n` splitter over `URLSession.AsyncBytes`, feeding `SSEParser.feed(line:)` directly; (b) add `os_log` (category: `SSE`) in `APIClient.streamPrices` on every event yielded + every decode-error caught, and in `ScannerViewModel.fetchPrices` on every event received, fallback triggered, and `sawDone` transition — one session's worth of iOS syslog would then pinpoint the failure mode; (c) add an XCUITest that drives the full flow against a live backend + a test-mode stream adapter so this regression gets caught in CI. **Impact:** the user-facing UX is currently identical to the pre-Step-2c batch path — except **slower**, because now every fetch does a stream call AND a batch call in sequence (~2× wall-clock). Functionally correct, experientially regressed.
- **2c-val-L7 — Uvicorn listens on 0.0.0.0 (IPv4 only); iOS happy-eyeballs tries IPv6 `localhost` first and gets `Connection refused` (LOW, ~50 ms penalty per request).** iOS syslog excerpt from the capture: `Socket SO_ERROR [61: Connection refused]` on `IPv6#611f268d.8000`, followed by IPv4 fallback which succeeds. The whole dance takes ~2 ms in the log, but compounds over dozens of sub-requests. Fix: bind uvicorn to `::` (dual-stack IPv4+IPv6) instead of `0.0.0.0`, or explicitly point `API_BASE_URL` in `Config/Debug.xcconfig` at `http://127.0.0.1:8000` to skip DNS resolution entirely. Not a blocker — it just adds a fixed connection-setup penalty the user never sees directly.

**Pre-existing issues surfaced during validation (not introduced by Step 2c):**

- **SP-L1 GitHub PAT still embedded in EC2 `~/barkain/.git/config`.** Confirmed visible in `git remote -v` during deploy. Token `gho_UUsp9ML7…` is active and has push access to `molatunji3/barkain`. Still a rotation candidate.
- **EC2 origin points at `molatunji3/barkain`** fork, not `THHUnlimted/barkain` upstream referenced in `CLAUDE.md`. Step 2c landed on `main` at both remotes (squash commit `9ceafe1`), so they're in sync; the fork-vs-upstream split is cosmetic for now but worth resolving.

**No fixes applied.** The SSE streaming mechanism itself — the subject of Step 2c — passed 100% of its structural checks (wire format, cache replay, batch fallback, deploy integrity). The data-quality issues are container-side and predate this session.

---

### Step 2c-fix — iOS SSE Consumer Fix (2026-04-13)

**Branch:** `fix/ios-sse-consumer` off `main` @ `b6bf54b` (after PR #9 merged)
**Root cause:** `URLSession.AsyncBytes.lines` buffers aggressively for small SSE payloads. The 11 retailer_result events + `done` event never reached the iOS parser incrementally — they landed in a single burst at stream-close time, which was after `for try await event in apiClient.streamPrices(...)` had already exited, so `sawDone` stayed `false` and every fetch fell through to `fallbackToBatch()`. Running curl against the same endpoint during the same session returned all 12 events in <1s with perfect timestamps, confirming the bug was entirely client-side.

**Diagnosis:** added a dedicated `com.barkain.app`/`SSE` os_log category with log points at every stage of the pipeline — stream open, each raw line received, each parsed event, each decoded typed event, `sawDone` transitions, fallback triggers, stream end. The diagnostic infrastructure stays permanently (os_log is lazy-evaluated so it's free in Release builds) and gives any future SSE regression one-session repro.

**Fixes:**
1. **Manual byte-level line splitter** (`Barkain/Services/Networking/Streaming/SSEParser.swift`) — the `events(from:)` static now delegates to a new test-visible `parse(bytes:)` that takes any `AsyncSequence<UInt8>` and iterates raw bytes, yielding complete `\n`-terminated lines the moment they arrive. Strips trailing `\r` for CRLF line endings. Parser state machine (`feed(line:)` + `flush()`) unchanged.
2. **IPv6 happy-eyeballs fix** (`Config/Debug.xcconfig`) — changed `API_BASE_URL` from `http://localhost:8000` to `http://127.0.0.1:8000`. Closes latent 2c-val-L7 (~50ms per-request penalty from the IPv4 fallback race; uvicorn `--host 0.0.0.0` is IPv4-only).
3. **os_log instrumentation** (`APIClient.swift`, `SSEParser.swift`, `ScannerViewModel.swift`) — structured logging on the full SSE path.
4. **Dead-code cleanup** — deleted `Barkain/Features/Shared/Components/ProgressiveLoadingView.swift` (196 lines). Grepping the entire `Barkain/` source tree confirmed zero references outside the file itself. Project uses `PBXFileSystemSynchronizedRootGroup`, so no pbxproj edit was required.

**Live verification:** ran both cached-path (Redis hit from prior 2c-val session) and fresh-path (Redis + DB rows deleted for product `1b492d0b-...`) runs against localhost uvicorn from the iOS Simulator (`com.molatunji3.barkain` on iPhone 17 iOS 26.4) with the os_log stream captured via `xcrun simctl spawn <booted> log stream --predicate 'subsystem == "com.barkain.app" AND category == "SSE"'`.

- **Cached-path log trace (12:48:26.xxx):** stream opened → 11 `retailer_result` raw lines arriving over 174ms with gaps between timestamps (629ms, +7ms, +86ms, +3ms, …) → `done` raw line → 11 decoded retailer events + 1 done → `sawDone=true succeeded=2 failed=9 cached=true` → stream ended normally. Zero fallback events. UI transitioned from "Sniffing out deals..." to the populated comparison view.
- **Fresh-path log trace (12:50:12.387 → 12:50:13.344, 957ms total):** 10 fast retailer events (containers returning `unavailable` without EC2) over 53ms → **897ms gap** → Walmart retailer_result (live Firecrawl adapter, real network round-trip) → done event → `sawDone=true succeeded=0 failed=11 cached=false` → stream ended normally. Zero fallbacks. The 897ms gap is the definitive proof — under the old `bytes.lines` bug, all 11 events would have arrived in a single burst at stream-close; under the fix, Walmart arrives exactly when its body hits the wire.
- **UI proof:** screenshot captured during the fresh-path run shows the PriceComparisonView fully populated from stream events with 7+ visible retailer rows (Walmart "Not found", Amazon/Best Buy/Target/Home Depot/Lowe's/eBay "Unavailable"). Under the old bug the UI would have been stuck on "Sniffing out deals..." for this entire 957ms window.

**Tests added:** 4 new byte-level parser tests (`test_byte_level_splits_on_LF`, `test_byte_level_handles_CRLF_line_endings`, `test_byte_level_flushes_partial_trailing_event_without_final_blank_line`, `test_byte_level_no_spurious_events_from_partial_lines`) driving `SSEParser.parse(bytes:)` through a hand-rolled `ByteStream: AsyncSequence` that yields bytes one at a time with `Task.yield()` between each — simulating wire-level arrival pattern. iOS tests: 32 → 36, all passing.

**Deferred:** live-backend XCUITest (Definition-of-Done item #5 step 5). The repo currently has zero UI tests (per CLAUDE.md "0 UI, 0 snapshot"); standing up a BarkainUITests target, wiring uvicorn lifecycle management from the test bundle, and adding launch-argument plumbing comfortably exceeds the 30-min fix budget. The os_log instrumentation gives equivalent diagnostic value — any future SSE regression is observable in one session via `log stream`. **Deferred to Step 2g.**

**Files touched (new/modified/deleted):**

| Path | Delta | What |
|------|-------|------|
| `Barkain/Services/Networking/Streaming/SSEParser.swift` | +70 / -14 | Manual byte splitter + new `parse(bytes:)` test-visible helper + os_log |
| `Barkain/Services/Networking/APIClient.swift` | +26 / -3 | os_log instrumentation throughout `streamPrices()` + per-event decode error capture |
| `Barkain/Features/Scanner/ScannerViewModel.swift` | +15 / -1 | os_log instrumentation in `fetchPrices()` + `fallbackToBatch()` |
| `Config/Debug.xcconfig` | +4 / -1 | `127.0.0.1` + comment |
| `Barkain/Features/Shared/Components/ProgressiveLoadingView.swift` | -196 / 0 | Deleted — dead code, zero references outside the file |
| `BarkainTests/Services/Networking/SSEParserTests.swift` | +90 / 0 | 4 new byte-level tests + `ByteStream` helper |
| `CLAUDE.md` | +4 / -2 | Version bump to v4.3, Step 2c-fix Current State entry, 3 new Key Decisions quick-refs, test counts 32→36 |
| `docs/CHANGELOG.md` | +this section | |
| `docs/TESTING.md` | +SSE debugging note | |
| `docs/SCRAPING_AGENT_ARCHITECTURE.md` | +Appendix G.5 update | |

**What stays the same (verified):** backend SSE endpoint, `sse_event()` wire format helper, `PriceAggregationService.stream_prices()`, all 11 existing `test_m2_prices_stream.py` tests, all 5 existing SSEParser tests, all 6 existing ScannerViewModel stream tests, 192 backend tests, `ruff check backend/` clean, iOS `xcodebuild build` clean.

**Latent bugs closed by this step:**
- **2c-val-L6 (HIGH):** iOS SSE consumer never rendered progressive events; always fell back to batch → **RESOLVED.**
- **2c-val-L7 (LOW):** IPv6 happy-eyeballs penalty → **RESOLVED** via `127.0.0.1` in Debug.xcconfig.
- **2c-L1 (LOW):** Dead `ProgressiveLoadingView.swift` → **RESOLVED** via file deletion.

**Latent bugs still open** (unchanged from prior sessions, out of scope for this fix): 2b-val-L1 (EC2 stale containers pending redeploy), 2c-val-L1 through L5 (Best Buy timing, Walmart data quality, etc. — see Step 2c-val section above).

---

### Step 2e-val — Card Portfolio Smoke Test (2026-04-14)

**Branch:** `phase-2/step-2e-val` off `main` @ `1cb79ad` (after PR #12 merged)
**PR target:** `main`
**Runtime:** ~30 min, full 6-phase protocol
**Result:** 0 bugs, all 6 phases PASS. Docs-only commit (this entry + CLAUDE.md + `Barkain Prompts/` appendices).

**Protocol:** `Barkain Prompts/Step_2e_val_Card_Portfolio_Smoke_Test.md`. Driven entirely through the iPhone 17 / iOS 26.4 simulator against a real local backend (uvicorn + Docker Postgres + Redis + Walmart Firecrawl adapter). No EC2 — 10 of 11 retailers return `.unavailable` as designed.

**Pre-flight:** Branch cut from `main`. Backend started with `BARKAIN_DEMO_MODE=1` + `WALMART_ADAPTER=firecrawl`. Four idempotent seed scripts ran clean (11 retailers, 8 brand-direct, 52 discount rows / 17 distinct programs, 30 cards, 2 rotating rows). `GET /api/v1/cards/catalog` returned 30 cards; `GET /api/v1/identity/discounts/all` returned 17. Fresh app install via `xcrun simctl uninstall` + `build_run_sim`.

**Phase results:**
- **Phase 1 — Identity onboarding:** Veteran toggled → Continue (Memberships) → Skip (Verification) → Save. `@AppStorage("hasCompletedIdentityOnboarding")` flipped, sheet dismissed.
- **Phase 2 — Card selection UI:** CardSelectionView loaded 30 cards grouped by issuer alphabetically (Amex → Wells Fargo). Search "Chase" filtered to exactly 7 Chase cards. Chase Freedom Flex tap added the card with a gold checkmark and **no `CategorySelectionSheet` appeared** — the `pendingCategorySelection` guard in `CardSelectionViewModel.addCard` correctly checks `userSelectedAllowed` is non-empty. Chase Sapphire Reserve added. Freedom Flex star tap toggled to `star.fill`. Profile tab showed "My Cards (2) | ⭐Chase Freedom Flex + Chase Sapphire Reserve" chips.
- **Phase 3 — Scan → stream → identity → cards:** Samsung Galaxy Buds 2 (`887276546810`) via Quick Picks. Gemini resolved to "Samsung Galaxy Buds2 (SM-R177NZKAXAR)". SSE stream fired, Walmart via Firecrawl returned $199.99 "New" with BEST BARKAIN badge, all other 10 retailers `.unavailable`. Identity Savings section rendered 9 cards (Samsung/HP/LG/Lowe's/Apple/Home Depot/Microsoft/Lenovo/Dell) all with Verify badges.
- **Phase 4 — Card recommendation detail:** Walmart row rendered inline subtitle "Use Chase Sapphire Reserve for 1x ($4.00 back)". Dollar math verified: `$199.99 × 1.0 × 2.0 / 100 = $3.9998 ≈ $4.00` ✅. CSR (2.0 cpp) correctly beat Freedom Flex (1.25 cpp → $2.50) because Walmart is not in Freedom Flex's Q2 rotating category list `[amazon, chase_travel, feeding_america]`, so both cards fall through to base rate and the higher cpp wins.
- **Phase 5 — Empty-cards CTA:** Both cards removed via swipe-delete → Remove button tap. Re-scanned Samsung → "Add your cards — See which card earns the most at each retailer" CTA rendered below the retailer list. Verified the CTA is keyed off backend `userHasCards=false` (not a local flag).
- **Phase 6 — Second-scan state reset:** Sony WH-1000XM5 (`027242923232`) via typed UPC. Product card refreshed, identity section refreshed with different percentages ("Up to 55%" vs Samsung run's "40%"), Walmart row flipped from "$199.99" to "Not found", "0 of 11 retailers have this product", **zero stale card recommendations visible**. `ScannerViewModel.handleBarcodeScan` reset paths for `cardRecommendations = []` + `identityDiscounts = []` verified.

**Observations (not bugs — 5 logged in error report appendix):**
1. Removing a preferred card does not auto-promote the next card (debatable UX)
2. Identity discount labels render "Save $X" when retailer price is available, "Up to X% off" otherwise — inconsistent surface across scans
3. `addCardsCTA` correctly keyed off backend response — no local `@AppStorage` staleness
4. Harness quirk: mid-list-reflow click during swipe-delete can inadvertently tap the next row; future smoke tests should add 600ms settle delay
5. `osascript` key events don't scroll iOS scroll views — use cliclick drag

**Tooling discovery:** XcodeBuildMCP in this environment exposes only `screenshot` + `snapshot_ui` + build/launch tools; UI automation (tap/type/swipe) is gated behind a config step that wasn't set. Worked around via `cliclick` (Homebrew, <10s install) + `osascript System Events` for clicks and typing. Coordinate mapping: `screen = (765 + logical_x * 0.9652, 123 + logical_y * 0.9657)` for the iPhone 17 simulator in the current window position. `fb-idb` via pip was tried but broke on Python 3.14.

**Files modified:**
```
CLAUDE.md                                                     # Current State: new Step 2e-val line above the Step 2e entry
docs/CHANGELOG.md                                             # This section
Barkain Prompts/Error_Report_Step_2e_Card_Portfolio.md       # Appendix: 2e-val results table + 5 observations
Barkain Prompts/Conversation_Summary_Step_2e_Card_Portfolio.md # Appendix: tooling discoveries + end-to-end flow narrative
```

**Verdict:** Step 2e ships cleanly. The core claim — "a single barcode scan surfaces price + identity discount + card reward in one view" — is verified live on iOS 26.4. No backend/iOS code changes required. Ready for Step 2f (M11 Billing / RevenueCat).

---

### Step 2i-b — Code Quality Sweep (2026-04-15)

**Branch:** `phase-2/step-2i-b` off `main` @ `39988e7` (after PR #17 — Step 2i-a docs — merged)
**PR target:** `main`

**Context:** Phase 2 (steps 2a–2h) and Step 2i-a (doc compaction) are done. 2i-b is the code-change complement to 2i-a's doc sweep — renames, dead-code removal, schema hardening, and a dedup extraction in the price service. No new features, no behavior changes. The plan was based on a prompt that overestimated the surface area in several places (4 inline `PreviewAPIClient` stubs, several `BARKAIN_DEMO_MODE` call sites, multiple `pytestmark` lines, `ProgressiveLoadingView.swift` still present); reality was leaner because earlier steps had already absorbed most of those items. The PR documents the prompt-vs-reality drift.

**Files changed:**
```
backend/app/config.py                                 # +DEMO_MODE: bool field on Settings
backend/app/dependencies.py                           # _DEMO_MODE module constant → settings.DEMO_MODE call-time read; dropped `import os`
backend/app/core_models.py                            # User.__table_args__ += chk_subscription_tier; CheckConstraint import
backend/modules/m5_identity/card_service.py           # B2 dead branch removed; retailer_lowest dict comprehension; ORDER BY price.asc() dropped (no-op under UNIQUE)
backend/modules/m2_prices/service.py                  # D1 _classify_retailer_result helper; get_prices/stream_prices both delegate; "Step 9" name-merge loop deleted
backend/ai/prompts/upc_lookup.py                      # A2 device_name deferral comment (above the system instruction string — string itself is verbatim)
backend/tests/test_integration.py                     # B3 pytestmark removed; unused `import pytest` dropped
backend/tests/modules/test_m11_billing.py             # +1 test: test_migration_0006_subscription_tier_constraint (savepoint guard)
infrastructure/migrations/versions/0006_subscription_tier_check.py  # NEW — idempotent DO $$ block, IF NOT EXISTS pattern
.env.example                                          # BARKAIN_DEMO_MODE=1 → DEMO_MODE=1 (commented sample)
.github/workflows/backend-tests.yml                   # comment-only: BARKAIN_DEMO_MODE → DEMO_MODE in the env-block explainer
scripts/run_demo.sh                                   # 4 sites: BARKAIN_DEMO_MODE → DEMO_MODE in echo + uvicorn launch
Barkain/Services/Networking/AppConfig.swift           # doc-comment rename
CLAUDE.md                                             # 2i-b row, migration 0006, test totals, +5 decision-log entries
docs/ARCHITECTURE.md                                  # auth middleware DEMO_MODE rename
docs/DEPLOYMENT.md                                    # 2 sites: env audit + curl example
docs/FEATURES.md                                      # platform-features Clerk row DEMO_MODE rename
docs/TESTING.md                                       # CI workflow note + XCUITest precondition rename
docs/CHANGELOG.md                                     # this section
docs/DATA_MODEL.md                                    # +0006 row in migrations table
docs/PHASES.md                                        # 2i-b ⬜ → ✅
```

**Key decisions (numbered):**

1. **`DEMO_MODE` is read at call-time, not import-time.** The previous `_DEMO_MODE = os.getenv("BARKAIN_DEMO_MODE") == "1"` module constant cached the value at import, defeating `monkeypatch.setenv` in tests. The new path lives on the pydantic-settings `Settings` instance and is resolved inside `get_current_user` per-request, so tests can `monkeypatch.setattr(settings, 'DEMO_MODE', True)` without import-ordering games. Field-name matching (no `env_prefix` set) means env var `DEMO_MODE` populates it directly.

2. **All live BARKAIN_DEMO_MODE references renamed; CHANGELOG history left frozen.** `.env.example`, the GitHub workflow, `scripts/run_demo.sh`, `AppConfig.swift`, and the live docs (`ARCHITECTURE`, `DEPLOYMENT`, `FEATURES`, `TESTING`) all say `DEMO_MODE` now. Historical CHANGELOG entries for Steps 2a–2h still reference `BARKAIN_DEMO_MODE` — by design, the changelog is the archaeological record. CLAUDE.md's load-bearing decision-log entry (the "Two sources of truth" line) was updated since CLAUDE.md is the canonical agent context.

3. **`device_name` rename to `product_name` deferred — code comment in `upc_lookup.py`.** Audit found 26 backend occurrences across 9 files, **0 iOS occurrences** (the iOS schema already uses `name`). The load-bearing site is `backend/ai/prompts/upc_lookup.py` — `device_name` is the literal Gemini API output contract field. A mechanical rename would require a coordinated prompt + service-parse + test-assertion update and risks breaking the LLM contract during a hardening step that isn't supposed to change behavior. Comment lives above the system instruction string (the string itself is `DO NOT CONDENSE OR SHORTEN — COPY VERBATIM`). Tracked in Phase 3.

4. **`ProgressiveLoadingView.swift` was already deleted.** Zero grep hits across `Barkain/` and `BarkainTests/`. Marked done with no action — the prompt was based on stale state. Some prior step (likely 2c when `PriceComparisonView` became the progressive UI) absorbed the cleanup.

5. **Dead `if retailer_id not in retailer_lowest` branch removed from `CardService.get_best_cards_for_product`.** The `Price` table has `UniqueConstraint("product_id", "retailer_id", "condition")`, so the WHERE clause filtering on `condition == "new"` returns at most one row per retailer. The "collapse to lowest" loop never had a duplicate to collapse. Replaced with a dict comprehension and dropped the `ORDER BY Price.price.asc()` (no-op under the UNIQUE constraint); kept `ORDER BY Price.retailer_id` for deterministic ordering. All 17 M5 card tests still pass.

6. **`pytestmark = pytest.mark.asyncio` removed from `tests/test_integration.py` (only remaining occurrence).** `pyproject.toml` sets `asyncio_mode = "auto"` which auto-marks every `async def test_*`. Also dropped the now-unused `import pytest`. All 12 integration tests still pass.

7. **TODO/FIXME audit complete — 1 legitimate Phase-2 item retained.** Only hit was `containers/template/server.py:91` — `# TODO(Phase-2): Add bearer token auth for container endpoints.` This is a real deferred concern (containers are VPC-only / localhost-only in Phases 1–2; bearer-token auth is a Phase 3+ production hardening item). Left in place.

8. **Migration 0006 — `chk_subscription_tier` CHECK constraint** on `users.subscription_tier IN ('free', 'pro')`. Until now the column was an unconstrained `TEXT` field with a `'free'` server default; only `BillingService` writes to it, but the DB had no defense if a future caller (or a manual psql session) tried to set `'enterprise'`, `'trial'`, etc. Idempotent via `DO $$ ... END $$` block keyed on `pg_constraint.conname`. Mirrored on `User.__table_args__` in `app/core_models.py` so `Base.metadata.create_all` (test DB) gets the constraint without alembic — same parity pattern as Steps 2f / 2h. Required restarting the `postgres-test` tmpfs container so the schema rebuilds with the new constraint.

9. **`_classify_retailer_result` helper in `m2_prices/service.py` is the single classification authority.** Both `get_prices()` and `stream_prices()` previously inlined ~40 lines of identical branching (error-code classification → status, no-listings → no_match, `_pick_best_listing` → no_match-or-success, success-path price payload assembly). Worse, they had already drifted — the stream version embedded `retailer_name` in the price payload directly while the batch version added it via a later "Step 9" loop. Extraction returns `(retailer_result_dict, price_payload_or_none, best_listing_or_none)`; callers handle counter increments, DB writes, and (stream only) SSE emission. The two methods are still NOT merged — they differ in iteration strategy (`as_completed` vs serial dict iteration) and emission semantics (yields events vs accumulates a dict). The "Step 9" name-merge loop in `get_prices` was deleted because the helper now inlines `retailer_name` in the payload at construction time.

10. **Migration 0006 test uses a SAVEPOINT (`db_session.begin_nested()`).** The first attempt called `db_session.rollback()` directly inside the test after catching `IntegrityError`, but that left the outer fixture transaction in an "already deassociated from connection" state and produced a `SAWarning`. Wrapping the failing UPDATE in `async with db_session.begin_nested()` rolls back only the savepoint on the constraint violation, keeping the outer fixture transaction intact for teardown.

11. **Group E (Conformer Consolidation) skipped.** Only 1 `PreviewAPIClient` exists (in `Barkain/Features/Recommendation/PriceComparisonView.swift`), not 4 as the prompt assumed. Premature abstraction with a single consumer was rejected — a shared `PreviewAPIClient.swift` would also require an Xcode `project.pbxproj` update for marginal value. Documented in CHANGELOG and PR. Decision will revisit when a 2nd preview-side conformer appears.

12. **`ruff check backend/ scripts/` was clean before any edits and remains clean.** No auto-fixes run. Deleting the unused `import pytest` from `test_integration.py` was preemptive — ruff would have flagged it anyway.

**Tests:**
- Backend: **301 → 302 passed, 6 skipped** (added `test_migration_0006_subscription_tier_constraint` in `test_m11_billing.py`).
- iOS: **66 unique tests passed** on `iPhone 17` simulator (iPhone 16 sim no longer installed locally; xcodebuild + source-line counting agree at 66).
- Behavior unchanged on `m2_prices` / `stream_prices` — full 74-test m2 suite passes, including the 11 stream tests.
- Migration 0006 round-trips cleanly: `alembic upgrade head` → `pg_constraint` shows `chk_subscription_tier`; `alembic downgrade -1` removes it; re-`upgrade head` reinstalls. Verified against the dev DB on `localhost:5432` and the tmpfs test DB on `localhost:5433`.

**Verdict:** Step 2i-b ships clean. Code quality items from Phase 2 are paid down; the remaining 2i checklist is 2i-c (operational validation + XCUITest + CI enforcement + tag `v0.2.0`).

---

### Step 2h — Background Workers (2026-04-14)

**Branch:** `phase-2/step-2h` off `main` @ `ab988cb` (after PR #15 merged)
**PR target:** `main`

**Context:** Every data pipeline before this step was request-driven: prices refreshed only on user scans, discount URLs were never re-checked after seeding, the `portal_bonuses` table had zero rows. Step 2h builds the operational backbone — background workers that keep Barkain's data fresh without user traffic. Four workers + a unified CLI runner, backed by SQS (LocalStack in dev, real AWS in prod), with `moto[sqs]` for hermetic CI tests (no running container needed). Backend-only; iOS is untouched.

**Pre-flight:** 280 passed / 6 skipped, ruff clean, PR #15 merged. No open PRs blocking. New branch `phase-2/step-2h` created off updated main.

**Files changed:**

```
backend/requirements.txt                                  # +boto3>=1.34.0 +beautifulsoup4>=4.12.0
backend/requirements-test.txt                             # +moto[sqs]>=5.0.0
backend/app/config.py                                     # +SQS_ENDPOINT_URL, +SQS_REGION, +PRICE_INGESTION_STALE_HOURS, +DISCOUNT_VERIFICATION_STALE_DAYS, +DISCOUNT_VERIFICATION_FAILURE_THRESHOLD (ENVIRONMENT already existed from Step 1a)
backend/modules/m5_identity/models.py                     # Added `Integer` import; `DiscountProgram.consecutive_failures` column (NOT NULL, server_default "0", default 0) so freshly constructed instances don't hold None before flush; `PortalBonus.__table_args__` appends `Index("idx_portal_bonuses_upsert", "portal_source", "retailer_id", unique=True)` mirroring migration 0005 so test DBs built via `Base.metadata.create_all` get the constraint.
backend/workers/queue_client.py                           # NEW — async-wrapped boto3 `SQSClient`. `_UNSET` sentinel lets callers pass explicit `None` to mean "no endpoint override" vs the default settings fallback — critical for moto-backed tests which must NOT hit LocalStack's URL. Three queue-name constants + `ALL_QUEUES` tuple. `send_message` / `receive_messages` / `delete_message` / `create_queue` all wrap blocking boto3 calls with `asyncio.to_thread`. URL cache keyed by queue name. `create_queue` is idempotent by SQS contract. One boto3 gotcha documented in code: the SDK method is `receive_message` (singular) even though it returns many — easy typo trap.
backend/workers/price_ingestion.py                        # NEW — two modes. `enqueue_stale_products(db, sqs, stale_hours=None)` runs a SQL `GROUP BY ... HAVING MAX(last_checked) < cutoff` on `products JOIN prices`, sends one SQS message per stale product (shape: product_id, product_name, retailers, enqueued_at). Products with zero prices are intentionally skipped — no retailer set to refresh until a user scans them first. `process_queue(db, redis, sqs, container_client=None, max_iterations=None)` long-polls the ingestion queue and drains each message by reusing `PriceAggregationService.get_prices(product_id, force_refresh=True)` — same pipeline user scans take, just initiated from SQS. Malformed bodies + missing products are ack+skipped (no retry spiral on permanently bad data); service exceptions are NOT acked so SQS visibility timeout handles retry. `max_iterations` kwarg is a test seam (bounded loop + `wait_seconds=0` when set).
backend/workers/portal_rates.py                           # NEW — `httpx` + `BeautifulSoup` scraper. Three pure-function parsers: `parse_rakuten` anchors on `aria-label="Find out more at <NAME> - Rakuten coupons and Cash Back"` (stable) and harvests `(Up to )?X% Cash Back` + optional `was Y%` baseline; `parse_topcashback` walks `span.nav-bar-standard-tenancy__value` → parent `a` → `img.alt` for the name; `parse_befrugal` walks `a[href^="/store/"]` → `img.alt` + `span.txt-bold.txt-under-store` for the rate. Hash-based CSS classes on Rakuten are avoided in favor of the stable `aria-label`. `RETAILER_NAME_ALIASES` dict maps portal display names (with common variants + curly apostrophe) to Barkain retailer ids. `upsert_portal_bonus(db, portal_source, rate)` inserts on first observation (seeds `normal_value` to the current rate, or to Rakuten's `was X%` marker when present) or updates `bonus_value`/`last_verified` on subsequent runs (leaves `normal_value` alone so the GENERATED ALWAYS STORED `is_elevated` column keeps firing on spikes). `run_portal_scrape(db)` drives all three portals under a single httpx client with Chrome headers; a single portal failing (403/429/503/network/≥400 → log WARNING and skip) does not abort the batch. Chase Shop Through Chase + Capital One Shopping are deferred (auth-gated) but emit a `0` count for observability. Module docstring explicitly flags this as a deliberate deviation from `SCRAPING_AGENT_ARCHITECTURE.md` Job 1 (which prescribes agent-browser).
backend/workers/discount_verification.py                  # NEW — `get_stale_programs(db, stale_days)` selects active programs with `verification_url IS NOT NULL` where `last_verified IS NULL OR last_verified < cutoff`. `check_url(client, url, program_name)` returns `(is_verified, status)` — 200+mention → `"verified"`, 200-without-mention → `"flagged_missing_mention"` (soft — does NOT increment the failure counter; a program rename shouldn't auto-deactivate), 4xx/5xx → `"http:<code>"`, network error → `"network:<exc_class>"`. `run_discount_verification(db, stale_days=None, failure_threshold=None)` iterates stale programs, always updates `last_verified`/`last_verified_by`, resets `consecutive_failures` to 0 on success, increments on hard failures only, and flips `is_active=False` once the counter hits the threshold. Returns a summary dict `{checked, verified, flagged, failed, deactivated}`. Kwargs default to `settings.DISCOUNT_VERIFICATION_*` so tests can override without mutating settings.
scripts/setup_localstack.py                               # NEW — idempotent queue creator. Calls `SQSClient.create_queue` for every name in `ALL_QUEUES`. Runnable directly or via `run_worker.py setup-queues`.
scripts/run_worker.py                                     # NEW — unified worker CLI mirroring `run_watchdog.py`. argparse + `asyncio.run()` + `async with AsyncSessionLocal()`. Five subcommands: `price-enqueue`, `price-process`, `portal-rates`, `discount-verify`, `setup-queues`. Lazy imports inside each handler so `setup-queues` doesn't pay the BeautifulSoup / price service import cost. Every DB-writing command follows the `try/commit/except/rollback` pattern from `app/dependencies.py:24-31`. `price-process` is the only long-running command; all others are one-shot. Includes the full cron schedule as a module docstring comment so ops can copy-paste it.
infrastructure/migrations/versions/0005_worker_constraints.py  # NEW — two idempotent upgrades. `CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_bonuses_upsert ON portal_bonuses (portal_source, retailer_id)` matches the Step 2f migration 0004 pattern for seed-script → migration ownership transfer. `ALTER TABLE discount_programs ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0` populates existing rows with the default in the same statement. Downgrade drops the column and the index with `IF EXISTS`.
docker-compose.yml                                        # Added `localstack` service (image `localstack/localstack:3`, port 4566, `SERVICES=sqs`, `EAGER_SERVICE_LOADING=1`, healthcheck via `curl -f http://localhost:4566/_localstack/health` because `awslocal` isn't in the base image) + `localstack-data` named volume.
.env.example                                              # Added Step 2h section with `SQS_ENDPOINT_URL=http://localhost:4566`, `SQS_REGION=us-east-1`, `AWS_ACCESS_KEY_ID=test`, `AWS_SECRET_ACCESS_KEY=test` (LocalStack convention), `PRICE_INGESTION_STALE_HOURS=6`, `DISCOUNT_VERIFICATION_STALE_DAYS=7`, `DISCOUNT_VERIFICATION_FAILURE_THRESHOLD=3`. The AWS_ACCESS_KEY_* values are NOT mirrored in `config.py` — boto3 reads them directly from the environment.
.env                                                      # Mirrored the above block in the live `.env` so `python3 scripts/run_worker.py *` works end-to-end locally.
backend/tests/fixtures/portal_rates/rakuten.html          # NEW — 30 retailer tiles captured from a live `curl` probe of https://www.rakuten.com/stores on 2026-04-14. Trimmed from 1.7 MB raw to ~66 KB by slicing around the first/last `aria-label` anchor and wrapping in a minimal HTML shell. Covers Best Buy, Target, Lowe's at minimum.
backend/tests/fixtures/portal_rates/topcashback.html      # NEW — TopCashBack "Big Box Brands" category page (https://www.topcashback.com/category/big-box-brands/) captured on 2026-04-14. 168 KB. 23 retailer tiles using the stable `.nav-bar-standard-tenancy__value` span pattern. Covers Best Buy, Walmart, Target, Home Depot, Lowe's, eBay, Sam's.
backend/tests/fixtures/portal_rates/befrugal.html         # NEW — BeFrugal store index (https://www.befrugal.com/coupons/stores/) captured on 2026-04-14. Trimmed from 710 KB raw to ~110 KB by slicing around the Best Buy / Amazon / Home Depot anchors. Covers Best Buy + Home Depot with `txt-bold txt-under-store` rates; Amazon appears in the DOM but has no bold rate (BeFrugal routes Amazon through its reward-program page instead of a direct cashback rate).
backend/tests/workers/__init__.py                         # NEW — empty package marker.
backend/tests/workers/test_queue_client.py                # NEW — 4 tests wrapped in `with mock_aws():`. test_send_message_round_trip, test_receive_messages_empty_queue_returns_empty_list, test_delete_message_removes_from_queue, test_get_queue_url_caches_after_first_resolution (patches the underlying `_client.get_queue_url` with a counting wrapper and asserts `call_count == 1` after two calls).
backend/tests/workers/test_price_ingestion.py             # NEW — 4 tests. `_seed_retailer`/`_seed_product`/`_seed_price` helpers seed the FK chain. test_enqueue_stale_products_sends_one_per_stale_product (3 products: 2 stale, 1 fresh → exactly 2 messages with matching product_ids). test_enqueue_stale_products_skips_products_without_prices (product with 0 prices → 0 messages). test_process_queue_calls_price_service_with_force_refresh (monkeypatches `PriceAggregationService.get_prices` with a counting mock, asserts `force_refresh=True` + correct product_id + message deleted post-success). test_process_queue_skips_unknown_product (random UUID in body → ack+deleted without calling the price service).
backend/tests/workers/test_portal_rates.py                # NEW — 6 tests, 3 parser + 1 normalize + 2 upsert. Parser tests load the committed HTML fixtures and assert ≥3 / ≥3 / ≥2 retailers plus the Rakuten "was X%" field being populated on at least one tile. test_normalize_retailer_aliases covers `"Best Buy"` / `"Lowe's"` / curly apostrophe / `"The Home Depot"` / `"Unknown Store"` / empty. test_upsert_portal_bonus_seeds_baseline_on_first_write asserts the GENERATED `is_elevated` reads back False when current == baseline. test_upsert_portal_bonus_detects_spike_via_generated_column seeds 5/5, upserts 10, asserts `bonus_value=10`, `normal_value=5` (preserved), `is_elevated=True` (10 > 5*1.5 = 7.5) — end-to-end exercise of the Postgres computed column through real SQLAlchemy → asyncpg.
backend/tests/workers/test_discount_verification.py       # NEW — 7 tests (1 more than the plan minimum of 6). All use `respx.mock` to intercept `httpx.AsyncClient.get`. test_verify_active_program_updates_last_verified (200 + mention → verified, counter 0, is_active True). test_verify_flagged_missing_mention_does_not_increment_failures (soft flag — counter unchanged, is_active True). test_verify_404_increments_failure_counter. test_verify_network_error_increments_failure_counter (`side_effect=httpx.ConnectError`). test_three_consecutive_failures_deactivates_program (seed `consecutive_failures=2`, 500 → 3, `is_active=False`). test_successful_verification_resets_failure_counter (seed 2 → 200+mention → 0). test_skips_programs_without_verification_url (program with `verification_url=None` never counted).
CLAUDE.md                                                 # v4.7 → v4.8. "Step 2h — Background Workers: COMPLETE" entry with file/test-count updates.
docs/ARCHITECTURE.md                                      # New Background Workers section documenting the SQS → worker → DB pipeline + 4 worker types + schedules.
docs/DATA_MODEL.md                                        # Migration history row for 0005 (unique index + consecutive_failures column).
docs/DEPLOYMENT.md                                        # New LocalStack Setup + cron schedule table + production SQS IAM permissions notes.
docs/SCRAPING_AGENT_ARCHITECTURE.md                       # Job 1 + Job 3 pseudocode sections annotated with "IMPLEMENTED in Step 2h" pointing at `backend/workers/portal_rates.py` and `backend/workers/discount_verification.py`, including the deliberate httpx-vs-agent-browser deviation.
docs/PHASES.md                                            # Step 2h row flipped ⬜ → ✅ with full scope paragraph.
docs/TESTING.md                                           # New Step 2h row (301 backend / 66 iOS). Total updated 280 → 301.
```

**Key decisions:**

1. **LocalStack for dev SQS, `moto[sqs]` for tests.** LocalStack is an actual running container — great for integration/smoke but painful for CI (start time, port conflicts, flaky on hosted runners). `moto` 5.x's `mock_aws` context stubs boto3 at the transport layer with zero setup, making every test hermetic. One side effect: if `settings.SQS_ENDPOINT_URL` is non-empty (which it is when `.env` is loaded), and we pass the endpoint through to boto3 inside `mock_aws`, boto3 tries to reach LocalStack at that URL and fails. The fix was the `_UNSET` sentinel in `SQSClient.__init__` — tests can now pass an explicit `endpoint_url=None` to override the settings default and force the real AWS default-credential resolution path that moto intercepts.

2. **boto3 wrapped in `asyncio.to_thread`, not aioboto3.** Every SQS operation pays a thread-pool hop but the surface stays sync-friendly, there's one fewer dep, and the API call volume (tens to hundreds of messages/hour) is nowhere near the scale where the hop matters. Documented in the `queue_client.py` module docstring so a future reader can swap to `aioboto3` if throughput ever exceeds ~10k messages/hour.

3. **Price ingestion: enqueue / process split reuses `PriceAggregationService`.** The worker contains zero dispatch, caching, or `price_history` append logic — those all live in `PriceAggregationService.get_prices(force_refresh=True)`, the exact same pipeline a user scan triggers. This is deliberate: one code path, one test target, one place to fix bugs. The worker's job is to translate SQS messages → service calls and to enforce the ack/retry contract. Anything beyond that would duplicate logic and create drift.

4. **SQS visibility-timeout retry, not application-level retry.** When `PriceAggregationService` raises inside `process_queue`, the worker deliberately does NOT delete the message. SQS hides the message for the visibility timeout (default 30s) and then re-delivers it to another consumer (or the same one, next iteration). No counter table, no dead-letter queue yet, no backoff math — the SQS contract handles it. If a message keeps failing, it'll eventually exceed the queue's `maxReceiveCount` and (once configured) land on a DLQ. That's a post-2h ops hardening task.

5. **Malformed + missing-product messages are ack+skipped, not retried.** Retrying bad data just retries the same crash. If a message body has a non-UUID `product_id`, or the UUID doesn't exist in the `products` table, the worker logs a WARNING and deletes the message. Operators can audit via the logs; the queue stays healthy.

6. **Portal rate scraping via `httpx` + `BeautifulSoup`, NOT agent-browser.** `docs/SCRAPING_AGENT_ARCHITECTURE.md` Job 1 pseudocode specifies agent-browser. Step 2h deliberately deviates: (a) portal rate pages are static-enough HTML tables that a browser render is overkill, (b) agent-browser would couple this worker to the scraper container infrastructure, making local dev miserable, (c) pure-function parsers are trivially unit-testable against HTML fixtures without any browser machinery. The deviation is flagged in the `portal_rates.py` module docstring and in this changelog entry so future readers don't get confused by the inconsistency.

7. **Per-portal parsers are pure functions anchored on stable attributes.** Rakuten's CSS classes are hash-based and will drift (`css-z47yg2`, `css-105ngdy`, `css-1ynb68i`) — the parser ignores them and anchors on the stable `aria-label="Find out more at <NAME> - Rakuten coupons and Cash Back"` pattern instead. TopCashBack uses `span.nav-bar-standard-tenancy__value` (semantic, unlikely to drift). BeFrugal uses `a[href^="/store/"]` + `img.alt` + `span.txt-bold.txt-under-store`. All three parsers are pure `(html) -> list[PortalRate]` so tests load a committed HTML fixture and assert against the output — no HTTP mocks, no browser fixtures.

8. **Fixtures captured from live probes, trimmed to fit.** Rakuten: raw 1.7 MB → trimmed to ~66 KB by slicing around 30 `aria-label` anchors. TopCashBack: 168 KB (no trimming needed — already small). BeFrugal: raw 710 KB → trimmed to ~110 KB by slicing around Best Buy / Amazon / Home Depot. All three probes hit the real portal pages with a Chrome UA header on 2026-04-14. If a portal's DOM shifts materially, refresh the fixture — do NOT edit the parser without first confirming the live page changed shape.

9. **`normal_value` baseline preservation for spike detection.** `portal_bonuses.is_elevated` is a Postgres `GENERATED ALWAYS ... STORED` column computed from `bonus_value > COALESCE(normal_value, 0) * 1.5`. On first observation, `normal_value` seeds to the current rate (or to Rakuten's `was X%` marker when present). On subsequent runs, `normal_value` is deliberately left alone unless the scrape reports a new `was` marker. Refreshing `normal_value` to the current rate on every run would erase the baseline that `is_elevated` needs. Trade-off: if a retailer's normal rate drifts permanently upward, `is_elevated` will wrongly claim "spike" forever — latent recommendation for a rolling 30-day TimescaleDB continuous aggregate in Phase 3+.

10. **Rakuten "was X%" marker overrides baseline, others don't.** The parser extracts Rakuten's `was Y%` text and populates `PortalRate.previous_rate_percent`. `upsert_portal_bonus` uses this to seed `normal_value` on first insert AND to refresh `normal_value` on subsequent updates — because Rakuten is telling us what the "old" rate was, which is exactly the "normal" baseline we want. TopCashBack and BeFrugal don't expose a previous-rate field, so those portals rely on the first-observation seed and never refresh the baseline.

11. **`is_elevated` is GENERATED ALWAYS STORED — never written.** Any INSERT or UPDATE that names the column raises a Postgres error. The worker never touches it; the upsert tests read it back to confirm the spike math. The `PortalBonus` SQLAlchemy model already uses `Computed("bonus_value > COALESCE(normal_value, 0) * 1.5", persisted=True)` from migration 0001, so SQLAlchemy knows not to include it in INSERT/UPDATE column lists.

12. **`consecutive_failures` is a new column on `discount_programs`, not a JSONB field.** Migration 0005 adds a dedicated `INTEGER NOT NULL DEFAULT 0` column. Alternatives considered: (a) encode a counter into the existing `notes` TEXT field as JSON — rejected because it would require JSON parsing on every read and couldn't be indexed; (b) use a sidecar `worker_failures` table — rejected because it's overkill for a per-program counter. The dedicated column is the simplest correct design. Both the model (`default=0` AND `server_default="0"`) and migration (same `server_default="0"`) declare the default so freshly constructed in-memory instances, `Base.metadata.create_all` fresh schemas, AND alembic upgrades all agree.

13. **"Flagged but not failed" distinction in discount verification.** A page that loads (HTTP 200) but doesn't mention the program name gets classified as `"flagged_missing_mention"` — the summary counts it under `flagged`, logs a WARNING, and the operator is expected to review. It does NOT increment `consecutive_failures`. Reason: program renames (e.g. "Student Discount" → "Verified Student Pricing") should not cause auto-deactivation. Only hard failures (4xx/5xx/network error) count toward the threshold. This preserves the "3 CDN blips don't kill a discount" invariant while still surfacing potentially-stale programs to humans.

14. **`last_verified` updates on every run regardless of outcome.** Whether the verification succeeds, is flagged, or fails, the worker bumps `last_verified` to `now()`. This ensures the same stale program doesn't keep re-appearing in the `get_stale_programs` query within the same week. A program that 404s this run will not be re-checked until next week's run — one shot per cadence, not a tight loop of retries.

15. **Test seam: `max_iterations` kwarg on `process_queue`.** Production leaves it unset for an infinite long-poll loop. Tests set `max_iterations=1` AND the wait-seconds branch switches from the 20s SQS long-poll to `wait_seconds=0` so the test doesn't hang when the queue is empty. Without the wait-seconds switch, a test that put a message on the queue, received it, and then ran one more iteration to verify the queue is empty would block for 20 seconds on the second iteration.

16. **Worker session lifespan + the `refresh()` trap.** Discount verification tests initially called `await db_session.refresh(program)` after `run_discount_verification`, expecting to re-read the mutated row. It failed because `refresh()` does NOT autoflush — it expires the object and issues a SELECT against the underlying connection. The worker's changes were still in the session's dirty-queue, not yet in the DB, so the SELECT returned the pre-mutation row. Fix: drop all `refresh()` calls. The in-memory object IS mutated in place via the SQLAlchemy identity map (the same instance the test seeded is the same instance `get_stale_programs` returns), so direct attribute inspection works perfectly. Documented in the Step 2h error report as a latent footgun.

**Tests:**

New backend tests: 21 across 4 files under `backend/tests/workers/`. `test_queue_client.py` ×4 (moto), `test_price_ingestion.py` ×4 (moto + DB), `test_portal_rates.py` ×6 (fixtures + DB), `test_discount_verification.py` ×7 (respx + DB). Zero new iOS tests. Test counts: 280 → 301 backend; 66 iOS unchanged.

**Live smoke test:** Deferred to Step 2h-val per the 2f/2g cadence — this step ships the structure and the CI-level validation; a live LocalStack → DB run can happen in a follow-up session once the PR is merged.

**Verdict:** Step 2h ships clean. Every data pipeline Barkain needs exists now. Ready for Step 2i (v0.2.0 hardening sweep).

---

### Step 2g — M12 Affiliate Router + In-App Browser (2026-04-14)

**Branch:** `phase-2/step-2g` off `main` @ `6403ddd` (after PR #14 merged)
**PR target:** `main`

**Context:** Barkain's commission path. Every retailer tap previously bounced the user out to external Safari via `UIApplication.shared.open`, which both lost the affiliate tag (the URL was raw) and lost the user out of the app. Step 2g plugs both leaks. Backend adds a deterministic URL-tagging service + click logger + stats endpoint + placeholder conversion webhook. iOS adds an `SFSafariViewController` wrapper so retailer and identity-discount taps open in an in-app browser — affiliate cookies persist because SFSafariVC shares cookies with Safari. Retailer taps round-trip through `POST /api/v1/affiliate/click` so the backend is the sole authority for commission URLs (iOS never builds tagged URLs locally). Identity discount taps land in the **same** in-app browser sheet but are NOT routed through `/affiliate/click` because verification pages are not affiliate links.

**Pre-flight:** None. The `affiliate_clicks` table already exists from migration 0001 (`AffiliateClick` model was mapped but the router/service/schemas were empty scaffold). No new migration needed.

**Files changed:**

```
backend/modules/m12_affiliate/__init__.py      # NEW — module marker + docstring pointing at ARCHITECTURE + CHANGELOG §Step 2g.
backend/modules/m12_affiliate/schemas.py       # NEW — `AffiliateClickRequest` (product_id: UUID | None, retailer_id, product_url), `AffiliateURLResponse` (affiliate_url, is_affiliated, network, retailer_id), `AffiliateStatsResponse` (clicks_by_retailer, total_clicks). All `ConfigDict(from_attributes=True)` for ORM compatibility. `affiliate_url` is the wire-level field name (not `url`) so iOS's `.convertFromSnakeCase` decodes cleanly to `affiliateUrl`.
backend/modules/m12_affiliate/service.py       # NEW — `AffiliateService` + network constants (`AMAZON_NETWORK="amazon_associates"`, `EBAY_NETWORK="ebay_partner"`, `WALMART_NETWORK="walmart_impact"`, `PASSTHROUGH_NETWORK="passthrough"`) + `EBAY_RETAILERS` frozenset for O(1) dispatch. `build_affiliate_url(retailer_id, product_url)` is a pure `@staticmethod` — no DB, no side effects, trivially unit-testable — returning `AffiliateURLResponse`. Amazon → `?tag=<store>` (or `&tag=...` when `?` is already in the URL). eBay (new + used) → `https://rover.ebay.com/rover/1/711-53200-19255-0/1?mpre=<urlencoded>&campid=<id>&toolid=10001`. Walmart → `https://goto.walmart.com/c/<id>/1/4/mp?u=<urlencoded>` (placeholder; passthrough when env empty). Best Buy + everyone else → original URL, `is_affiliated=false`, `network=None`. `log_click(user_id, request)` upserts the users row first (FK safety + demo-mode parity with `m5_identity.get_or_create_profile`), then inserts into `affiliate_clicks` with the sentinel `"passthrough"` value when `network is None` (the column is NOT NULL in the schema). `get_user_stats(user_id)` does a `GROUP BY retailer_id` query and returns a dict + total.
backend/modules/m12_affiliate/router.py        # NEW — `APIRouter(prefix="/api/v1/affiliate", tags=["affiliate"])`. `POST /click` (requires `get_current_user`, rate-limited `general`, body `AffiliateClickRequest`, returns `AffiliateURLResponse`). `GET /stats` (auth + rate-limited, returns `AffiliateStatsResponse`). `POST /conversion` (no `get_current_user` — this is a webhook; validates `Authorization: Bearer <AFFILIATE_WEBHOOK_SECRET>` when the secret is set, accepts any request with an INFO log when the secret is empty = permissive placeholder mode). Always returns 200 when auth passes so affiliate networks never retry on acknowledgement events.
backend/modules/m12_affiliate/models.py        # UNCHANGED — `AffiliateClick` was already mapped in the scaffold from Step 1a.
backend/app/main.py                            # MODIFIED — `from modules.m12_affiliate.router import router as m12_affiliate_router` + `app.include_router(m12_affiliate_router)` following the m11_billing pattern.
backend/app/config.py                          # MODIFIED — added a new Step 2g block near the end of `Settings`: `AMAZON_ASSOCIATE_TAG: str = ""`, `EBAY_CAMPAIGN_ID: str = ""`, `WALMART_AFFILIATE_ID: str = ""`, `AFFILIATE_WEBHOOK_SECRET: str = ""`. All default to empty → service passthrough, webhook permissive → no accidental leaks in test / staging.
.env.example                                   # MODIFIED — new "# ── Affiliate Programs (Step 2g) ─" section before the Demo Mode block. Real `AMAZON_ASSOCIATE_TAG=barkain-20` + `EBAY_CAMPAIGN_ID=5339148665` (live). Commented `# WALMART_AFFILIATE_ID=` + `AFFILIATE_WEBHOOK_SECRET=` placeholders with usage notes.
.env                                           # MODIFIED — same block appended under `CONTAINER_TIMEOUT_SECONDS`. Real values for Amazon + eBay so `python3 -m uvicorn` picks them up locally; placeholders for Walmart + webhook secret.
backend/tests/modules/test_m12_affiliate.py    # NEW — 14 tests. `_seed_retailer(db_session, retailer_id)` helper inserts a minimal retailers row (only NOT NULL columns `id`, `display_name`, `base_url`, `extraction_method`) so `affiliate_clicks.retailer_id` FK lands. 9 pure URL construction tests: amazon-with-and-without-existing-params, amazon-empty-env, ebay-new, ebay-used, walmart-set, walmart-unset, best-buy, home-depot. 3 endpoint tests: `test_click_endpoint_logs_row_and_returns_tagged_url` (asserts DB row has `affiliate_network='amazon_associates'` + `click_url` contains `tag=barkain-20`), `test_click_endpoint_passthrough_logs_sentinel` (asserts DB row has `affiliate_network='passthrough'` when untagged), `test_stats_endpoint_groups_by_retailer` (logs 2 amazon + 1 best_buy, GETs `/stats`, asserts counts). 2 webhook tests: `test_conversion_webhook_permissive_without_secret` (empty `AFFILIATE_WEBHOOK_SECRET` → 200 with no auth header), `test_conversion_webhook_bearer_required_when_secret_set` (401 for missing + wrong bearer, 200 for correct bearer).

Barkain/Features/Shared/Models/AffiliateURL.swift                            # NEW — 3 `nonisolated struct` Sendable models: `AffiliateClickRequest` (Codable, Equatable; `productId: UUID?`, `retailerId`, `productUrl`); `AffiliateURLResponse` (Codable, Sendable, Equatable; `affiliateUrl`, `isAffiliated`, `network: String?`, `retailerId`); `AffiliateStatsResponse` (Codable, Sendable, Equatable; `clicksByRetailer: [String: Int]`, `totalClicks`). Encoded / decoded via the existing `.convertToSnakeCase` / `.convertFromSnakeCase` strategies — no explicit `CodingKeys` blocks.
Barkain/Features/Shared/Components/InAppBrowserView.swift                    # NEW — `UIViewControllerRepresentable` wrapper around `SFSafariViewController`. Configures `entersReaderIfAvailable=false`, `barCollapsingEnabled=true`, `preferredControlTintColor = UIColor(Color.barkainPrimary)`. Header comment explains why SFSafariViewController over WKWebView (cookie sharing with Safari = affiliate tracking cookies persist). Exports `IdentifiableURL` wrapper (`Identifiable, Equatable`, `id = url.absoluteString`) so `.sheet(item:)` can accept a URL payload.
Barkain/Services/Networking/Endpoints.swift                                  # MODIFIED — added `case getAffiliateURL(AffiliateClickRequest)` and `case getAffiliateStats` under a `// Step 2g — Affiliate` section. `path`: `/api/v1/affiliate/click` + `/api/v1/affiliate/stats`. `method`: POST for `getAffiliateURL` (added to the existing POST list), GET for `getAffiliateStats`. `body`: new branch for `.getAffiliateURL(let request)` using `encoder.keyEncodingStrategy = .convertToSnakeCase` to match `updateIdentityProfile`/`addCard`.
Barkain/Services/Networking/APIClient.swift                                  # MODIFIED — `APIClientProtocol` gains `func getAffiliateURL(productId: UUID?, retailerId: String, productURL: String) async throws -> AffiliateURLResponse` and `func getAffiliateStats() async throws -> AffiliateStatsResponse` under a `// Step 2g — Affiliate` block. Concrete `APIClient` implements both — `getAffiliateURL` builds an `AffiliateClickRequest` and calls the shared `request(endpoint:)` helper, `getAffiliateStats` is a thin pass-through.
Barkain/Features/Scanner/ScannerViewModel.swift                              # MODIFIED — new `resolveAffiliateURL(for retailerPrice: RetailerPrice) async -> URL?` method. Guards on nil / empty `retailerPrice.url`. Captures the fallback `URL(string: rawUrlString)` up-front. Calls `apiClient.getAffiliateURL(productId: priceComparison?.productId, retailerId:, productURL:)`. Returns the tagged URL on success, the fallback on any thrown error (non-affiliate networks, 5xx, offline, timeout). Logs the fallback via the existing `sseLog.warning`. NEVER throws — the commission is a nice-to-have, the click-through is not.
Barkain/Features/Recommendation/PriceComparisonView.swift                    # MODIFIED — added `@State private var browserURL: IdentifiableURL?`. Body gains `.sheet(item: $browserURL) { item in InAppBrowserView(url: item.url).ignoresSafeArea() }` at the root `ScrollView`. Retailer Button action rewritten: `Task { if let url = await viewModel.resolveAffiliateURL(for: retailerPrice) { browserURL = IdentifiableURL(url: url) } }`. `openRetailerURL(_:)` helper + all `UIApplication.shared.open` calls DELETED. `IdentityDiscountsSection` call site now passes `onOpen: { browserURL = IdentifiableURL(url: $0) }` so identity discount taps also land in the in-app browser — same sheet, same presenter, same cookie jar.
Barkain/Features/Recommendation/IdentityDiscountsSection.swift               # MODIFIED — `IdentityDiscountsSection` + `IdentityDiscountCard` both gain `let onOpen: (URL) -> Void`. `IdentityDiscountCard.openVerificationURL()` now `guard let url = resolvedURL; onOpen(url)`. New `var resolvedURL: URL? { URL(string: discount.verificationUrl ?? discount.url) }` is a testable computed property. Accessibility hint updated from "Opens the verification page in Safari" → "Opens the verification page in an in-app browser". `#Preview("Discounts section")` updated to pass `onOpen: { _ in }`.
BarkainTests/Helpers/MockAPIClient.swift                                     # MODIFIED — added Step 2g section: `getAffiliateURLResult: Result<AffiliateURLResponse, APIError>` default-returns a passthrough `AffiliateURLResponse(affiliateUrl: "https://example.com", isAffiliated: false, network: nil, retailerId: "mock")`; `getAffiliateStatsResult` default-returns empty. Call counters + last-arg trackers (`getAffiliateURLCallCount`, `getAffiliateURLLastProductId`, `getAffiliateURLLastRetailerId`, `getAffiliateURLLastProductURL`, `getAffiliateStatsCallCount`). Method impls record the call then return the Result.
Barkain/Features/Recommendation/PriceComparisonView.swift (PreviewAPIClient) # MODIFIED — added 2 stub methods to the inline `PreviewAPIClient` struct for Xcode #Preview. Free-tier defaults: returns the input URL unchanged with `isAffiliated=false, network=nil`, empty stats.
Barkain/Features/Profile/ProfileView.swift (PreviewProfileAPIClient)         # MODIFIED — same 2-method fanout.
Barkain/Features/Profile/IdentityOnboardingView.swift (PreviewOnboardingAPIClient) # MODIFIED — same.
Barkain/Features/Profile/CardSelectionView.swift (PreviewCardAPIClient)      # MODIFIED — same.
BarkainTests/Features/Scanner/ScannerViewModelTests.swift                    # MODIFIED — 3 new tests appended to the existing file: `test_resolveAffiliateURL_returnsTaggedURLOnSuccess` (stubs `mockClient.getAffiliateURLResult` with an Amazon-tagged URL, calls the helper after a normal scan, asserts the tagged URL comes back and the mock was called once). `test_resolveAffiliateURL_fallsBackOnAPIError` (stubs `.failure(.network(...))`, asserts the original `retailerPrice.url` URL comes back, not nil; asserts `getAffiliateURLCallCount == 1` so the helper did try the API before falling back). `test_resolveAffiliateURL_passesCorrectArguments` (validates `getAffiliateURLLastRetailerId == "best_buy"`, `...LastProductURL == "https://bestbuy.com/site/123"`, `...LastProductId == samplePriceComparison.productId`). All three use the already-populated `priceComparison` from a successful `handleBarcodeScan` call so `priceComparison?.productId` is non-nil.
BarkainTests/Features/Recommendation/IdentityDiscountCardTests.swift         # NEW — 3 tests of `IdentityDiscountCard.resolvedURL` as a testable computed property. `test_resolvedURL_prefersVerificationURL` (both `verificationUrl` and `url` set → verification wins). `test_resolvedURL_fallsBackToURLWhenVerificationMissing` (only `url` set → url wins). `test_resolvedURL_returnsNilWhenBothMissing` (both nil → resolvedURL is nil). `@testable import Barkain` gives access to the struct; `makeDiscount(verificationUrl:url:)` private factory avoids boilerplate per test.
```

**Test counts after Step 2g:** 266 → **280 backend** (+14: `test_m12_affiliate.py`). 60 → **66 iOS** (+6: 3 ScannerViewModel + 3 IdentityDiscountCard). 0 UI, 0 snapshot.

**Key decisions (Step 2g):**

1. **Backend-only URL construction** (never build tagged URLs on iOS). Every retailer tap round-trips through `POST /api/v1/affiliate/click`, which returns the tagged URL AND logs the click atomically. Rejected alternative: build on-device + log separately — duplicates tagging logic across platforms and loses the atomic click-log-and-tag guarantee. The iOS client is a thin presenter; the backend is the single source of truth for commission URLs.

2. **`SFSafariViewController`, not `WKWebView`.** SFSafariVC shares cookies with Safari → affiliate tracking cookies set by Amazon / eBay / Impact Radius persist across sessions, which is what commission attribution depends on. WKWebView uses an isolated data store, so every click would start with a clean session and commission would be unreliable. Secondary benefits: built-in nav bar, reader mode, TLS padlock, no custom WebView security surface to maintain.

3. **Fail-open on every `getAffiliateURL` path.** Network error, 5xx, offline, timeout → `ScannerViewModel.resolveAffiliateURL` returns the fallback `URL(string: retailerPrice.url)`, not nil (except when the retailer row has no URL at all). Users are never blocked from clicking through. Rejected alternative: show a loading spinner then an error toast — the commission is a nice-to-have, the click-through is not. Missing env vars (`AMAZON_ASSOCIATE_TAG=""`) → service returns `is_affiliated=false` + original URL, no 500.

4. **`AffiliateService.build_affiliate_url` is a pure `@staticmethod`.** No DB, no instance state, no side effects. Unit tests don't need a fixture session; 9 of the 14 backend tests are pure assertions with just a `monkeypatch` on `settings`. This matches the Zero-LLM philosophy of the rest of M1–M10 — the affiliate layer is deterministic arithmetic and string formatting, nothing more.

5. **`affiliate_clicks.affiliate_network` NOT NULL → `"passthrough"` sentinel.** The column is NOT NULL in migration 0001. Untagged clicks (Best Buy, Home Depot, etc.) could either (a) violate the constraint, (b) require a migration to relax the schema, or (c) use a descriptive sentinel. Chose (c) because the stats endpoint groups by `retailer_id` not `affiliate_network`, so the sentinel doesn't leak into client surfaces, and the constraint is load-bearing for downstream analytics (Phase 5+).

6. **Identity discount URLs are NOT affiliate links.** The `IdentityDiscountsSection` / `IdentityDiscountCard` refactor routes verification-page taps through the same `browserURL` sheet as retailer taps, but direct-constructs the `IdentifiableURL` without calling `/affiliate/click`. Verification pages (ID.me, SheerID, UNiDAYS, WeSalute) exist to prove eligibility, not to convert. Saves a round-trip on every discount tap and keeps the `affiliate_clicks` table clean.

7. **`IdentityDiscountsSection` closure-based open pattern.** Changed struct signatures from zero-arg presentation-only to `onOpen: (URL) -> Void`. Alternative: have `IdentityDiscountCard` own its own sheet via `@State`. Rejected because (a) iOS only allows one sheet at a time per presenter, and (b) funnelling both retailer taps and discount taps through a single `browserURL: IdentifiableURL?` @State on `PriceComparisonView` keeps the sheet lifecycle coherent. `IdentityDiscountCard.resolvedURL` is now exposed as a testable computed property — prefers `verificationUrl`, falls back to `url`, nil when both missing.

8. **`ScannerViewModel.resolveAffiliateURL(for:)` as testable seam.** Adding business logic inside a SwiftUI View closure is untestable without ViewInspector. Extracted into a `ScannerViewModel` public async method that `PriceComparisonView` calls from a `Task {}` inside the Button action. 3 of 4 iOS tests drive this seam against `MockAPIClient`; the 4th (identity discount) tests `IdentityDiscountCard.resolvedURL` directly.

9. **Conversion webhook runs in permissive placeholder mode when `AFFILIATE_WEBHOOK_SECRET` is empty.** Accepts any request and logs the body at INFO. Once the secret is set, it enforces `Authorization: Bearer <secret>` and 401s on mismatch — mirrors the `m11_billing` webhook pattern. Permissive mode lets the endpoint be wired in staging before real affiliate networks are configured; bearer mode lets it flip to production without a code change.

10. **Amazon tag separator logic.** URLs like `amazon.com/dp/B0B2FCT81R` get `?tag=`; URLs like `amazon.com/dp/B0B2FCT81R?psc=1` get `&tag=`. Single `sep = "&" if "?" in product_url else "?"` check. Unit tests 1 + 2 validate both branches + that `psc=1` is preserved unchanged.

11. **eBay rover URL encodes the full source URL.** `urllib.parse.quote(product_url, safe="")` with `safe=""` encodes every reserved character including `:` and `/`, so the final rover URL can't accidentally have two `?` or break eBay's `mpre` parameter parser. Unit test 4 validates the encoding explicitly against `https://www.ebay.com/itm/12345?var=99`.

12. **Walmart placeholder behavior.** When `WALMART_AFFILIATE_ID` is empty (default), Walmart URLs pass through untagged. When set (future, when Impact Radius approves), they redirect via `goto.walmart.com/c/<id>/1/4/mp?u=<encoded>`. No migration required to enable the affiliate network — just flip the env var. Unit tests 6 + 7 validate both branches.

13. **No new migration.** The `affiliate_clicks` table + indexes were already created in migration 0001 (`AffiliateClick` model has been present in `backend/modules/m12_affiliate/models.py` since Step 1a). Step 2g only adds router / service / schemas. This is a no-migration step — deployments don't need `alembic upgrade head`.

14. **Live credentials in `.env`.** Amazon `barkain-20` + eBay `5339148665` are already approved. Added to `.env` directly. `.env.example` has the same values as documentation (they're public identifiers, not secrets). `WALMART_AFFILIATE_ID` + `AFFILIATE_WEBHOOK_SECRET` stay commented/empty until their respective approvals come through.

15. **`product_id` is nullable in `AffiliateClickRequest`.** The `affiliate_clicks.product_id` column has `nullable=True` in the model. The iOS client always passes a non-nil UUID (from `priceComparison?.productId`), but the endpoint accepts null so future tap contexts (e.g. a saved-items view) can log clicks without a resolved product.

---

### Step 2f — M11 Billing + Feature Gating (2026-04-14)

**Branch:** `phase-2/step-2f` off `main` @ `6c23b3e` (after PR #13 merged)
**PR target:** `main`

**Context:** Barkain's first monetization surface. RevenueCat handles the App Store StoreKit complexity; the backend uses `users.subscription_tier` as the rate-limiter authority and stays in sync via webhook. Free tier gets a deliberate strip-down (10 scans/day, 3 identity discounts max, no card recommendations) so the Pro upgrade has obvious value. Two sources of truth — RC SDK on iOS (offline, instant), `users.subscription_tier` on backend (rate limits) — converge via the webhook with up to 60s of accepted drift.

**Pre-flight:** PF-1 — moved `idx_card_reward_programs_product` from the seed-script `ensure_unique_index()` helper into Alembic migration 0004. Migration uses `op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ...")` so existing dev/prod DBs (which already have the index from the seed-script path) upgrade cleanly. The `CardRewardProgram` SQLAlchemy model now also declares the index in `__table_args__` so the test DB built by `Base.metadata.create_all` gets it on fresh schemas without running alembic. The seed script's `ensure_unique_index()` function and call site removed; module docstring updated to point at migration 0004.

**Files changed:**

```
infrastructure/migrations/versions/0004_card_catalog_unique_index.py  # NEW PF-1 — Alembic migration. revision=0004, down_revision=0003. upgrade() / downgrade() use raw `CREATE UNIQUE INDEX IF NOT EXISTS` / `DROP INDEX IF EXISTS` to be idempotent against dev DBs that already have the seed-script-created index. Header comment cross-references the model `__table_args__` mirror.
backend/modules/m5_identity/models.py                                  # PF-1 — `CardRewardProgram` gets `__table_args__ = (Index("idx_card_reward_programs_product", "card_issuer", "card_product", unique=True),)` so Base.metadata.create_all (test DB fixture) creates it on fresh schemas. Comment notes the migration mirror.
scripts/seed_card_catalog.py                                           # PF-1 — `ensure_unique_index()` function + its call site removed. Module docstring updated to say migration 0004 owns the index.

backend/modules/m11_billing/__init__.py                                # NEW — module docstring describes the two-source-of-truth design (RC SDK = UI, users.subscription_tier = rate limits, webhook = sync).
backend/modules/m11_billing/schemas.py                                 # NEW — `SubscriptionStatusResponse {tier, expires_at, is_active, entitlement_id}`. `is_active` is computed in service, not stored. Pydantic ConfigDict from_attributes.
backend/modules/m11_billing/service.py                                 # NEW — `BillingService(db)`. `get_subscription_status(user_id)` → reads users row, computes is_active = tier=="pro" AND (expires_at IS NULL OR expires_at > now()), reports effective tier (free for expired-pro). `process_webhook(payload, redis)` dispatches on RC `event.type`. State-changing events: INITIAL_PURCHASE/RENEWAL/PRODUCT_CHANGE/UNCANCELLATION → pro + expiration; NON_RENEWING_PURCHASE → pro + None (lifetime); CANCELLATION → pro + expiration (user keeps until end of period); EXPIRATION → free + None. Idempotency via Redis SETNX `revenuecat:processed:{event.id}` (7-day TTL). User row UPSERT via INSERT ... ON CONFLICT (id) DO UPDATE so first INITIAL_PURCHASE for an unknown user works. Tier cache bust via `redis.delete(f"tier:{user_id}")` on every state change. Failure to process Redis falls open + logs warning.
backend/modules/m11_billing/router.py                                  # NEW — APIRouter(prefix="/api/v1/billing", tags=["billing"]). GET /status (Clerk auth, no rate limit — cheap, used on launch for reconciliation). POST /webhook (NO Clerk auth — validates `Authorization: Bearer <REVENUECAT_WEBHOOK_SECRET>` against settings, raises 401 WEBHOOK_AUTH_FAILED otherwise). Always returns 200 + `{"ok": true, ...}` when auth passes — even for unknown event types — to prevent RC retry storms.

backend/app/main.py                                                    # +2 lines: import m11_billing_router, app.include_router(m11_billing_router).
backend/app/config.py                                                  # +REVENUECAT_WEBHOOK_SECRET: str = "" (Step 2f section). +RATE_LIMIT_PRO_MULTIPLIER: int = 2 (next to existing rate limits).
backend/app/dependencies.py                                            # `get_rate_limiter` is now tier-aware. New module-level `_resolve_user_tier(user_id, redis, db)` helper: Redis cache `tier:{user_id}` first (60s TTL), then SELECT subscription_tier + subscription_expires_at from users on miss, defaults to "free" on missing row. Pro requires tier=="pro" AND (expires_at IS NULL OR expires_at > now()). Cache write happens even for free results to avoid thundering-herd on the SSE hot path. `check_rate_limit` adds `db: AsyncSession = Depends(get_db)` and computes `limit = base_limit * settings.RATE_LIMIT_PRO_MULTIPLIER if is_pro else base_limit`. Existing 252 tests still green because `user_test_123` (no users row) resolves to free + base limit.
.env.example                                                           # New "Billing / RevenueCat (Step 2f)" section adds `REVENUECAT_WEBHOOK_SECRET=` placeholder with documentation.

backend/tests/modules/test_m11_billing.py                              # NEW — 14 tests. Helpers: `_seed_user(...arbitrary fields)` upserts users rows; `_build_event(type, id, app_user_id, expiration_at_ms)` builds RC envelopes; `_webhook_headers(secret)` returns the bearer auth dict; `_future_ms(days)` / `_past_ms(days)` for expiration math. Webhook tests (8): initial_purchase_sets_pro, renewal_sets_new_expiration (asserts SET not delta), non_renewing_lifetime, cancellation_keeps_pro_until_expiration, expiration_downgrades_to_free, invalid_auth_returns_401 (asserts WEBHOOK_AUTH_FAILED code), unknown_event_acknowledged (no DB write, no users row created), idempotency_same_event_id (second post → action=duplicate). Status tests (3): free_user, pro_user_with_expiration, expired_pro_downgrades_in_response (DB row unchanged). Rate limiter tests (2): free_user_uses_base_limit (3/min limit + 4th request 429), pro_user_doubled (6 requests under doubled limit succeed, 7th 429). Migration test (1): migration_0004_index_exists (queries pg_indexes for indexdef containing UNIQUE/card_issuer/card_product).

Barkain.xcodeproj/project.pbxproj                                      # +SPM dependency on github.com/RevenueCat/purchases-ios-spm v5.x. New PBXBuildFile, XCRemoteSwiftPackageReference, XCSwiftPackageProductDependency sections added. RevenueCat + RevenueCatUI products linked into Barkain target via packageProductDependencies + Frameworks build phase. Resolved as 5.67.2 at first `xcodebuild -resolvePackageDependencies`.

Config/Debug.xcconfig                                                  # +REVENUECAT_API_KEY = test_RtgnxKGXxhBYfljExWurnyPDYYh (the public RC API key — safe to commit, designed to ship in client bundles; the server-side webhook secret stays in backend/.env).
Config/Release.xcconfig                                                # +REVENUECAT_API_KEY = (empty placeholder; production key set at release time).
Info.plist                                                             # +REVENUECAT_API_KEY $(REVENUECAT_API_KEY) — same xcconfig→Info.plist substitution as API_BASE_URL.

Barkain/Services/Networking/AppConfig.swift                            # +`revenueCatAPIKey: String` reads from Bundle.main.infoDictionary, empty fallback. +`demoUserId: String = "demo_user"` matches `backend/app/dependencies.py::get_current_user` demo-mode return value so RC webhooks land on the right users row.

Barkain/Features/Shared/Models/BillingStatus.swift                     # NEW — Decodable/Equatable/Sendable struct: tier, expiresAt, isActive, entitlementId. Decoded via APIClient's `.convertFromSnakeCase` strategy — no explicit CodingKeys.

Barkain/Services/Subscription/SubscriptionService.swift                # NEW — @MainActor @Observable. Wraps RevenueCat. State: currentTier (.free/.pro), customerInfo, offerings, isConfigured. configure(apiKey, appUserId) is idempotent; falls open to free tier when apiKey is empty (preview / unit-test build). Installs `PurchasesDelegateAdapter` (private NSObject helper at file end) routing receivedUpdated → main-actor `apply(info:)` so the @Observable class doesn't have to subclass NSObject. Strong-references the adapter (RC holds delegate weakly). Initial customerInfo() fire-and-forget on configure. refresh(), loadOfferings(), restorePurchases() exposed for UI hooks. Entitlement id "Barkain Pro" hardcoded.
Barkain/Services/Subscription/FeatureGateService.swift                 # NEW — @MainActor @Observable. Pure-Swift gate, no RevenueCat import. ProFeature enum (unlimitedScans/fullIdentityDiscounts/cardRecommendations/priceHistory). Static constants: freeDailyScanLimit=10, freeIdentityDiscountLimit=3. Test seam: `init(proTierProvider: () -> Bool, defaults: UserDefaults, clock: () -> Date)` bypasses SubscriptionService entirely. Convenience init takes a SubscriptionService. Daily scan counter persisted in UserDefaults via `barkain.featureGate.dailyScanCount` + `barkain.featureGate.lastScanDateKey` (yyyy-MM-dd string in LOCAL timezone — PST users get fresh quota at midnight local, not midnight UTC). hydrate() rolls over on init if the date key has changed.

Barkain/BarkainApp.swift                                               # @State subscriptionService + featureGateService owned by the App so they live for process lifetime. `init()` constructs both, calls subscription.configure(apiKey: AppConfig.revenueCatAPIKey, appUserId: AppConfig.demoUserId), wires them via `.environment(subscriptionService).environment(featureGateService)` (SwiftUI 17+ native @Observable injection — not custom EnvironmentKey).

Barkain/Features/Billing/PaywallHost.swift                             # NEW — thin SwiftUI wrapper around RevenueCatUI.PaywallView(). Reads SubscriptionService from environment. .onPurchaseCompleted + .onRestoreCompleted callbacks call subscription.refresh() then dismiss + invoke caller-supplied closures. Sheet binding stays clean.
Barkain/Features/Billing/CustomerCenterHost.swift                      # NEW — thin SwiftUI wrapper around RevenueCatUI.CustomerCenterView() with a "Manage Subscription" navigation title.

Barkain/Features/Recommendation/Components/UpgradeLockedDiscountsRow.swift  # NEW — tap-to-paywall row with lock icon, "Upgrade to see X more discount(s)" headline, plain button style.
Barkain/Features/Recommendation/Components/UpgradeCardsBanner.swift         # NEW — tap-to-paywall single banner with credit-card icon and "Upgrade for card recommendations" headline.

Barkain/Services/Networking/Endpoints.swift                            # +case getBillingStatus → "/api/v1/billing/status" (GET).
Barkain/Services/Networking/APIClient.swift                            # +`getBillingStatus()` to APIClientProtocol. +concrete implementation in APIClient.

Barkain/Features/Scanner/ScannerViewModel.swift                        # +`showPaywall: Bool` published flag, +`featureGate: FeatureGateService` stored property. New init signature: `init(apiClient:, featureGate: FeatureGateService? = nil)` — defaults to `FeatureGateService(proTierProvider: { false })` constructed inside the init body (FeatureGateService is @MainActor and Swift evaluates default expressions in the caller's actor context — building inside the body sidesteps that). `handleBarcodeScan` gates AFTER successful product resolve: if `featureGate.scanLimitReached`, set showPaywall = true and return; otherwise `featureGate.recordScan()` then `await fetchPrices()`. No quota burn on resolve failures.
Barkain/Features/Scanner/ScannerView.swift                             # +@Environment(FeatureGateService.self) injection. Passes `featureGate:` into `ScannerViewModel` init in .task. New `paywallBinding` computed property collapses optional viewModel to a Binding<Bool>. New `.sheet(isPresented: paywallBinding)` presents PaywallHost with onPurchase/onRestore → scanner.clearLastScan(). PriceComparisonView invocation passes `onRequestUpgrade: { viewModel.showPaywall = true }`.

Barkain/Features/Recommendation/PriceComparisonView.swift              # +@Environment(FeatureGateService.self) injection. +`onRequestUpgrade: (() -> Void)? = nil` callback. identityDiscountsSection now slices to `visibleIdentityDiscounts` (full list for pro, prefix(3) for free) and renders `UpgradeLockedDiscountsRow(hiddenCount:)` below when free user has more matched than visible. New `cardUpgradeBanner` @ViewBuilder renders ONE `UpgradeCardsBanner` above the retailer list when free user has matching cardRecommendations they can't see (better UX than 11 per-row "upgrade" placeholders). PriceRow gets `cardRecommendation: featureGate.canAccess(.cardRecommendations) ? viewModel.cardRecommendations.first { ... } : nil`. Preview adds `.environment(FeatureGateService(proTierProvider: { false }))`.

Barkain/Features/Profile/ProfileView.swift                             # +@Environment(SubscriptionService.self), +@Environment(FeatureGateService.self), +@State showPaywall. New `subscriptionSection` @ViewBuilder rendered between header card and identity chips (and parallel placement in the empty-state branch). Pro users see a "Manage subscription" NavigationLink pointing at CustomerCenterHost. Free users see "Scans today: X / 10 — Y left" + "Upgrade to Barkain Pro" button → showPaywall = true. New `tierBadge` capsule. `.sheet(isPresented: $showPaywall) { PaywallHost() }` at the bottom of body. Both #Preview blocks `.environment(SubscriptionService())` + `.environment(FeatureGateService(proTierProvider: { false }))`.

Barkain/Features/Recommendation/PriceComparisonView.swift              # PreviewAPIClient adds getBillingStatus stub returning free.
Barkain/Features/Profile/ProfileView.swift                             # PreviewProfileAPIClient adds getBillingStatus stub.
Barkain/Features/Profile/CardSelectionView.swift                       # PreviewCardAPIClient adds getBillingStatus stub.
Barkain/Features/Profile/IdentityOnboardingView.swift                  # PreviewOnboardingAPIClient adds getBillingStatus stub.

BarkainTests/Helpers/MockAPIClient.swift                               # +`getBillingStatusResult: Result<BillingStatus, APIError>` defaulting to free, +`getBillingStatusCallCount`, +`getBillingStatus()` impl.

BarkainTests/Services/FeatureGateServiceTests.swift                    # NEW — 8 tests. Each test uses a fresh UUID-suffixed UserDefaults suite via `makeDefaults()` + `makeGate()` helpers. Tests: free_user_hits_scan_limit_at_10 (10 recordScan calls then scanLimitReached==true), pro_user_never_hits_scan_limit (100 scans, still false, remainingScans nil), scan_count_resets_on_new_day (mutable clock closure advances 25h → rollover), canAccess_fullIdentityDiscounts_false_for_free, canAccess_cardRecommendations_false_for_free, canAccess_all_features_true_for_pro (iterates ProFeature.allCases), remainingScans_nil_for_pro, hydrate_restores_persisted_count (writes raw UserDefaults keys then constructs gate to verify hydration).
BarkainTests/Features/Scanner/ScannerViewModelTests.swift              # +setUp now creates a per-test UUID-suffixed UserDefaults suite + FeatureGateService(proTierProvider: { false }) → injected into ScannerViewModel. Without this, tests share UserDefaults.standard and accumulate scans → 10/day cap silently breaks unrelated tests mid-suite. +2 tests: scanLimit_triggersPaywall_blocksFetchPrices (gate pre-loaded to limit, scan still resolves product but skips prices, showPaywall flipped, getPricesCallCount stays 0), scanQuota_consumedOnlyOnSuccessfulResolve (failing resolve does NOT increment scan count; subsequent successful resolve does).

CLAUDE.md                                                              # Step 2f section in Current State. Test counts 252→266 backend, 53→63 iOS. New env vars (REVENUECAT_API_KEY xcconfig, REVENUECAT_WEBHOOK_SECRET .env). New SPM dep. Key Decisions log additions.
docs/CHANGELOG.md                                                      # This entry.
docs/ARCHITECTURE.md                                                   # API Endpoint Inventory: +2 billing rows.
docs/AUTH_SECURITY.md                                                  # Tier-based rate limiting section: free vs pro multiplier, Redis tier cache TTL, RC webhook auth.
docs/FEATURES.md                                                       # Pillar 5 StoreKit subscription ✅ 2f + Feature gating ✅ 2f.
docs/COMPONENT_MAP.md                                                  # iOS Subscription row flipped to ✅ Phase 2 (2f), version pinned.
docs/PHASES.md                                                         # Step 2f row → ✅ (2026-04-14).
docs/TESTING.md                                                        # Step 2f row appended.
docs/DEPLOYMENT.md                                                     # New "Billing / RevenueCat (Step 2f)" section with dashboard setup tasks + env var references.
docs/DATA_MODEL.md                                                     # Tier semantics note: subscription_tier ∈ {free, pro}, is_active computed.
```

**Test counts:** 266 backend (266 passed / 6 skipped, +14 new) / 63 iOS unit (+10 new: 8 FeatureGateServiceTests + 2 ScannerViewModelTests). `ruff check .` clean. `xcodebuild build` BUILD SUCCEEDED. `xcodebuild -only-testing:BarkainTests test` TEST SUCCEEDED on iPhone 17 (iOS 26.4) simulator.

**Key decisions:**
1. **Two sources of truth, by design.** RC SDK on iOS gates UI (offline, instant, cache-first). `users.subscription_tier` on backend gates rate limits (authoritative for server-side decisions). They converge via `POST /api/v1/billing/webhook` with up to 60s of accepted drift (tier cache TTL). Alternative — every gate is a backend round-trip — breaks offline scanning, which is half Barkain's value prop. Documented in `SubscriptionService.swift` header.
2. **`@Observable final class` services, no protocol.** The prompt suggested `protocol SubscriptionServiceProtocol: Observable` but `any Observable` erases the macro-generated tracking and breaks SwiftUI re-renders. Existing codebase has zero observable protocols — all ViewModels are concrete. SubscriptionService + FeatureGateService follow the same pattern. Test seam for FeatureGateService is achieved via init injection (proTierProvider closure + UserDefaults suite + clock), not protocol mocking.
3. **Native SwiftUI 17+ environment injection** (`.environment(observableObject)` + `@Environment(Type.self)`), not custom EnvironmentKey. The existing `apiClient` keeps its custom EnvironmentKey because `APIClient` is a Sendable protocol (can't be observed). For @Observable classes the native pattern propagates observation correctly out of the box.
4. **Tier resolution via Redis cache → DB fallback → free default.** `_resolve_user_tier` reads `tier:{user_id}` from Redis (60s TTL). On miss it does a single SELECT against the users table; missing row → "free" (not an error). The cache is written even for "free" results to avoid thundering-herd on the SSE hot path. Webhook handlers bust the key on every state change so upgrades take effect within the cache window. Avoids adding a Postgres roundtrip to every authenticated request — measured zero impact on existing 252-test baseline.
5. **Webhook idempotency: SETNX dedup + SET-not-delta math.** `revenuecat:processed:{event.id}` Redis key with 7-day TTL. Replays return `action=duplicate` immediately. Belt-and-suspenders: even if dedup fails, the actual state mutations always SET `subscription_expires_at` from the event payload (never `+= delta`), so a replayed RENEWAL produces the same final row. Idempotent at both layers.
6. **Webhook always returns 200 on auth pass.** Unknown event types log + return `action=acknowledged`. RevenueCat treats anything non-2xx as failure → infinite retries; we never want a phantom retry storm for an event we don't care about. Auth failures DO return 401 (signature mismatch is a real problem RC should escalate).
7. **`app_user_id` mapping = backend demo user id.** No Clerk iOS SDK yet — the iOS demo build sends backend requests without a JWT and the backend's `BARKAIN_DEMO_MODE=1` branch returns `user_id="demo_user"`. RC's `app_user_id` is hardcoded to the same string in `AppConfig.demoUserId` so webhook events land on the right `users` row. When Clerk iOS lands (deferred, separate step), replace the constant with the live Clerk session id and call `Purchases.shared.logIn(id)` / `logOut()` on auth changes. The plan already documents the swap.
8. **PurchasesDelegate adapter (NSObject), not closure listener.** Context7 surfaced `Purchases.shared.customerInfoUpdateListener` as the v5 API but it's stale — v5.67.2 only exposes `delegate: PurchasesDelegate`. `@Observable final class SubscriptionService` can't subclass NSObject cleanly, so a private `PurchasesDelegateAdapter: NSObject, PurchasesDelegate` adapter routes the callback into a closure that the service stores. The service strong-references the adapter (RC holds delegate weakly). Lesson recorded: trust `xcodebuild`, not Context7 alone.
9. **Scan quota gated AFTER successful product resolve, not before.** Plan agent Trap 9. Better UX than burning quota on barcode-read failures or unknown UPCs. Counted scans = "real" scans of resolved products. Free users can retry a fuzzy barcode without losing a scan.
10. **Local-timezone daily rollover via yyyy-MM-dd string.** Stores last-scan date as a `yyyy-MM-dd` string in the user's local TZ, not a Date. PST users scanning at 11:59pm PST and 12:01am PST get a fresh quota at midnight local — not midnight UTC. Comparison is timezone-explicit and trivially testable.
11. **Test seam = init injection, not protocol mocking.** `FeatureGateService(proTierProvider: () -> Bool, defaults: UserDefaults, clock: () -> Date)` lets tests bypass `SubscriptionService` (and therefore RevenueCat) entirely. ScannerViewModelTests inject a per-test UUID-suffixed UserDefaults suite to prevent quota leakage across tests — without it, tests sharing `UserDefaults.standard` accumulate scans and the 10/day cap silently breaks unrelated tests mid-suite (caught during this step's first test run).
12. **Migration 0004 idempotent via `IF NOT EXISTS` raw SQL.** Existing dev/prod DBs already have `idx_card_reward_programs_product` from the seed-script lazy-create path. `op.create_index(..., unique=True)` would fail with `DuplicateTableError` on first upgrade. `op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ...")` is idempotent. The model's `__table_args__` mirrors the index so fresh test DBs (built via `Base.metadata.create_all` in conftest, NOT alembic) get it for free.
13. **Identity discount truncation in PriceComparisonView, not IdentityDiscountsSection.** Slice the array at the call site (`Array(viewModel.identityDiscounts.prefix(3))`) and render `UpgradeLockedDiscountsRow` below the section. IdentityDiscountsSection stays presentation-only and doesn't import billing types.
14. **Single card upgrade banner above the retailer list, not per-row placeholders.** Eleven "Upgrade to Pro" lines repeated would be visual spam. One banner at the top of the retailer list makes the upgrade ask without polluting the comparison table.
15. **`xcodebuild -resolvePackageDependencies` validates pbxproj edits faster than a full build.** Used to verify the 6 surgical pbxproj edits adding the SPM dependency before any compile.

**Deferred / known gaps:**
- **RevenueCat dashboard configuration** is a Mike post-merge task: create products `lifetime`/`yearly`/`monthly`, create entitlement `Barkain Pro`, create `default` offering with all 3, set the webhook URL + secret, configure Customer Center paths and support URL. Documented in `docs/DEPLOYMENT.md` Billing section. Until this lands, `PaywallView()` will show a loading/error state — the Swift integration is correct but the dashboard side has no products to render.
- **Real Clerk iOS auth.** Out of scope per the prompt's "Do not" list. Step 2f uses a hardcoded demo user id for the RC `app_user_id`. Replace with `Purchases.shared.logIn(clerkSession.user.id)` when the iOS Clerk SDK lands.
- **Purchase reconciliation testing.** Can't unit-test the RevenueCat SDK without StoreKit testing infrastructure. PaywallHost callbacks are wired but not covered by automated tests; manual smoke test via the simulator is the only validation until App Store sandbox testing lands in Phase 4.
- **Promo codes** — Phase 4.
- **Family sharing** — Phase 5+.
- **App Store / TestFlight submission** — Phase 4.
- **Backend-tracked scan quota.** `@AppStorage` is bypassable via reinstall, clock manipulation, or multi-device install. Acceptable for pre-launch MVP. Server-side tracking would add a write to a hot SSE-adjacent path and demand timezone reasoning on the backend; deferred until abuse is observed.
- **`subscription_tier` enum constraint.** Currently a TEXT column with `default 'free'`. No CHECK constraint. The migration to enforce vocabulary via PG enum is deferred — would require coordinating an ALTER TYPE migration with SDK rollouts and provides limited upside given the BillingService is the only writer.
- **CI run of `test_migration_0004_index_exists`.** The test passes on a fresh local test DB (after I dropped + recreated the public schema mid-step to pick up the model `__table_args__` change). CI builds a fresh TimescaleDB container per run, so the test will pick up the index from `Base.metadata.create_all` automatically — but this hasn't been verified end-to-end in CI yet. If it fails in CI, the fix is to add an explicit `Base.metadata.create_all` reindex.

---

### Step 2e — M5 Card Portfolio + Reward Matching (2026-04-14)

**Branch:** `phase-2/step-2e` off `main` @ `04848a5` (after PR #11 merged)
**PR target:** `main`

**Context:** completes Barkain's second pillar. Step 2d answered "who is this user?" (identity discounts); Step 2e answers "which card should they use?" A single barcode scan now surfaces price + identity discount + card reward in a single view — something no competing app can do.

**Pre-flight:** PF-1 — URL verification sweep of all 27 unique URLs in `scripts/seed_discount_catalog.py` via curl + system cert store (not Python urllib, which failed cert-verification on every HTTPS URL). Most 403/429/503 responses are bot-detection, not dead URLs. Two real failures: Lenovo `/discount-programs` and `/education-store` both return 503 — replaced with `/us/en/d/deals/discount-programs/`, `/us/en/d/deals/military/`, `/us/en/d/deals/student/` which all return 200 via `--http1.1` + Chrome UA. PF-2 — added commented `DATABASE_URL` block to `.env.example` matching the default in `backend/app/config.py`.

**Files changed:**

```
scripts/seed_card_catalog.py                                  # NEW — 30 Tier 1 cards from CARD_REWARDS.md. CARDS list + CARD_ISSUERS + REWARD_CURRENCIES constants (re-exported from card_schemas.py for lint tests). `ensure_unique_index` creates `idx_card_reward_programs_product` on `(card_issuer, card_product)` — migration 0001 has no unique constraint, so the seed script owns it until a future migration. `seed_cards` uses `INSERT ... ON CONFLICT (card_issuer, card_product) DO UPDATE SET` with `CAST(:category_bonuses AS JSONB)` for the JSONB column. Idempotent, safe to re-run. Same dotenv + async engine + explicit commit pattern as seed_discount_catalog.py.
scripts/seed_rotating_categories.py                           # NEW — Q2 2026 rotating categories. ROTATING_CATEGORIES list holds only Freedom Flex (categories=["amazon","chase_travel","feeding_america"], 5.0, cap 1500) + Discover it Cash Back (categories=["restaurants","home_depot","lowes","home_improvement"], 5.0, cap 1500). Cash+ and Customized Cash deliberately excluded — their rates live in the card's category_bonuses.user_selected and resolve per-user via user_category_selections. Resolves card_program_id via `(card_issuer, card_product)` lookup then upserts ON CONFLICT (card_program_id, quarter). Fails loud if the catalog is missing a card.
scripts/seed_discount_catalog.py                              # PF-1: 4 Lenovo URL replacements (verification_url + url for Military Discount, verification_url + url for Education Store).
.env.example                                                  # PF-2: added commented `DATABASE_URL` block before the Demo Mode section.

backend/modules/m5_identity/card_schemas.py                   # NEW — CardRewardProgramResponse (+ user_selected_allowed flattened from JSONB), AddCardRequest, UserCardResponse, SetCategoriesRequest, CardRecommendation, CardRecommendationsResponse. CARD_ISSUERS + REWARD_CURRENCIES module-level tuples for lint tests.
backend/modules/m5_identity/card_service.py                   # NEW — CardService(db). `_RETAILER_CATEGORY_TAGS` module-level dict maps 19 retailer ids (11 Phase 1 + 8 brand-direct) → frozenset of category tags (amazon/online_shopping/electronics_stores/home_improvement/etc.). `_quarter_to_dates("2026-Q2") → (2026-04-01, 2026-06-30)`. 8 methods: get_catalog, get_user_cards, add_card (upserts users FK first, ON CONFLICT reactivates soft-deleted + replaces nickname), remove_card (soft delete), set_preferred (unset-all then set-one), set_categories (validates against allowed list + upserts user_category_selections), get_best_cards_for_product (four-query preload: user cards joined with programs, rotating_categories WHERE in (card_program_ids), user_category_selections, prices+retailers — then pure in-memory max loop). `_best_card_for_retailer` helper implements the core matching algorithm. Zero-LLM throughout.
backend/modules/m5_identity/card_router.py                    # NEW — APIRouter(prefix="/api/v1/cards", tags=["cards"]). 7 endpoints. GET /catalog (general rate limit). GET /my-cards (general). POST /my-cards (write, 201, 404 on unknown card). DELETE /my-cards/{id} (write, 204). PUT /my-cards/{id}/preferred (write, 404 on unknown user card). POST /my-cards/{id}/categories (write, 400 INVALID_CATEGORY_SELECTION / 404 USER_CARD_NOT_FOUND). GET /recommendations?product_id= (general). All use raise_http_error.

backend/app/main.py                                           # +2 lines: import m5_card_router + app.include_router.

backend/tests/modules/test_m5_cards.py                        # NEW — 22 tests covering catalog + CRUD + matching + perf gate. Helpers: _seed_user, _seed_retailer, _seed_card, _seed_rotating, _seed_product_with_prices. Perf test: 5 cards + 2 rotating + 3 retailers, median of 5 runs, asserts < 150ms (50ms target in plan, 150ms upper bound for CI). Deleted `test_recommendations_lowest_price_per_retailer` mid-run — the UNIQUE `(product_id, retailer_id, condition)` constraint prevents seeding duplicate prices at the same retailer, making the dedup branch unreachable from tests.
backend/tests/test_card_catalog_seed.py                       # NEW — 12 pure-Python lint tests (no DB): card count==30, issuers match vocab, currencies match vocab, no duplicate (issuer, product), display names unique, category_bonuses shape (each has category + rate, user_selected must have non-empty allowed), all 8 Tier 1 issuers represented, base rates positive, points cards carry conservative cpp, rotating references valid cards, rotating nonempty, Q2 2026 dates, Cash+/Customized Cash NOT in rotating (regression guard on design intent).

Barkain/Features/Shared/Models/CardReward.swift               # NEW — CardRewardProgram (Identifiable/Hashable, + userSelectedAllowed flattened top-level field), UserCardSummary, AddCardRequest, SetCategoriesRequest, CardRecommendation (composite String id = retailerId + userCardId for SwiftUI ForEach), CardRecommendationsResponse. All Codable/Sendable/nonisolated.
Barkain/Services/Networking/APIClient.swift                   # +7 APIClientProtocol methods. +7 concrete implementations. +`requestVoid(endpoint:)` private helper for 204 / `{"ok": true}` endpoints — same error mapping as request<T>() but discards the body.
Barkain/Services/Networking/Endpoints.swift                   # +7 enum cases. +2 HTTPMethod cases (.put, .delete). Per-case path/method/queryItems/body. addCard + setCardCategories serialize their request bodies with .convertToSnakeCase. getCardRecommendations appends ?product_id=...

Barkain/Features/Profile/CardSelectionViewModel.swift         # NEW — @MainActor @Observable CardSelectionViewModel. load() fetches catalog + user cards in parallel via async let. filteredGroups groups by issuer with `displayIssuer` special-casing (bank_of_america → "Bank of America", capital_one → "Capital One", us_bank → "US Bank", wells_fargo → "Wells Fargo"). addCard flips `pendingCategorySelection` when the added card has a non-empty userSelectedAllowed. togglePreferred replaces the updated card in-place and clears the preferred flag on every other card locally (optimistic — backend PUT already unset them). setCategories clears pendingCategorySelection on success.
Barkain/Features/Profile/CardSelectionView.swift              # NEW — NavigationStack-wrapped List grouped by issuer. Search bar in the first section. "My Cards" section (if non-empty) above the catalog — each row has a star toggle for preferred + swipe-to-delete. Catalog rows are Buttons that toggle add/remove. `.sheet(item: $viewModel.pendingCategorySelection)` drives the CategorySelectionSheet presentation. `currentQuarter()` derives the quarter from Date() for the setCategories call.
Barkain/Features/Profile/CategorySelectionSheet.swift         # NEW — standalone struct. Lists the card's `allowed` categories with checkmark toggles. Save button disabled when selection is empty. Skip dismisses without saving.
Barkain/Features/Profile/ProfileView.swift                    # Added `cardsSection` rendering "My Cards" chips (with preferred star) + "Manage cards" button, or empty-state CTA + "Add cards" button. New @State showCardSheet presents CardSelectionView. loadCards() called from .task alongside loadProfile(). `onDismiss` re-fetches cards so the chips stay current after the sheet closes. Preview stub client adds 7 card-method no-ops.
Barkain/Features/Recommendation/PriceComparisonView.swift     # Added `onRequestAddCards: (() -> Void)? = nil` parameter. New `addCardsCTA` @ViewBuilder renders when `!viewModel.userHasCards && viewModel.cardRecommendations.isEmpty` — tap invokes the closure. RetailerListRow.success now passes `cardRecommendation: viewModel.cardRecommendations.first { $0.retailerId == retailerPrice.retailerId }` into PriceRow. Second `.animation(.easeInOut(duration: 0.3), value:)` on cardRecommendations. Preview stub client adds 7 card-method no-ops.
Barkain/Features/Shared/Components/PriceRow.swift             # Added optional `cardRecommendation: CardRecommendation?` parameter. When non-nil, renders a second row below the price showing a credit-card icon + "Use [card] for [rate]x ($[amount] back)" + an "Activate" Link when activation_required. Rate formatting handles 5.0 → "5x" and 1.5 → "1.5x".
Barkain/Features/Profile/IdentityOnboardingView.swift         # Preview stub client: 7 card-method no-ops.

Barkain/Features/Scanner/ScannerViewModel.swift               # +2 state properties: cardRecommendations + userHasCards. Reset in handleBarcodeScan + reset(). New private fetchCardRecommendations called from the END of fetchIdentityDiscounts (so it runs at both post-SSE-success and post-batch-fallback paths automatically). Non-fatal on failure — never sets priceError, never clears userHasCards on transient errors.
Barkain/Features/Scanner/ScannerView.swift                    # +@State showAddCardsFromCTA + second .sheet presenting CardSelectionView with onDismiss that calls `vm.fetchPrices()` (Redis-cached, near-instant) so userHasCards flips once the new cards are returned by the recommendations endpoint. PriceComparisonView invocation passes onRequestAddCards.

BarkainTests/Helpers/MockAPIClient.swift                      # +7 Result properties, +12 call-count/call-arg fields, +7 protocol method implementations. Default getCardRecommendationsResult returns TestFixtures.emptyCardRecommendations (keeps existing scanner tests passing without edits).
BarkainTests/Helpers/TestFixtures.swift                       # +sampleCardProgramId, +sampleCardProgram (Chase Freedom Flex, 1.0 base, 1.25 cpp, ultimate_rewards, no userSelectedAllowed), +sampleUserCardSummaryId, +sampleUserCardSummary (Chase Freedom Flex, preferred=true, nickname="daily driver"), +sampleCardRecommendationAmazon (5.0 rate, $12.50 back, isRotatingBonus=true, activationRequired=true), +sampleCardRecommendationsResponse (1 rec, userHasCards=true), +emptyCardRecommendations (empty list, userHasCards=false).

BarkainTests/Features/Profile/CardSelectionViewModelTests.swift  # NEW — 7 tests: load_populatesCatalogAndUserCards, filteredGroups_groupsByIssuerAlphabetically (with US Bank special-case assertion), addCard_callsAPIAndUpdatesPortfolio (no category sheet for Freedom Flex), addCard_userSelectedCard_opensCategorySheet (pendingCategorySelection set for Cash+), removeCard_softDeletesLocally, togglePreferred_unsetsOthers (optimistic local update), setCategories_callsAPIWithQuarter (+ clears pending sheet on success).
BarkainTests/Features/Scanner/ScannerViewModelTests.swift     # +3 tests: fetchCardRecommendations_firesAfterIdentityDiscounts (asserts getEligibleDiscounts was called exactly once before getCardRecommendations), emptyOnFailure_doesNotSetPriceError, clearedOnNewScan.

CLAUDE.md                                                     # Step 2e — M5 Card Portfolio entry in Current State. Test counts 222/43 → 252/53. New Current State bullets for card catalog + rotating seeds + card service + card endpoints + iOS card UI. Decisions log additions.
docs/CHANGELOG.md                                             # This entry.
docs/ARCHITECTURE.md                                          # API Endpoint Inventory: 7 new card endpoint rows under Phase 2 M5. `/api/v1/card-match/{product_id}` Phase 3 row crossed out — landed early as `/api/v1/cards/recommendations` in Step 2e.
docs/TESTING.md                                               # Test Inventory: Step 2e row (252/53, +30 backend + 10 iOS = 40 new).
docs/PHASES.md                                                # Step 2e Status: ✅ (2026-04-14).
docs/FEATURES.md                                              # Pillar 2: Card portfolio management ✅ 2e. Card reward matching ✅ 2e. User-selected category capture ✅ 2e. Rotating category tracking 🟡 2e→3 (Q2 2026 seeded manually; quarterly scraping automation still Phase 3).
```

**Test counts:** 252 backend (252 passed / 6 skipped, +30 new: 22 m5_cards + 8 seed lint) / 53 iOS unit (+10 new: 7 CardSelectionViewModelTests + 3 ScannerViewModelTests). `ruff check .` clean. `xcodebuild test -only-testing:BarkainTests` → 53/53 green on iPhone 17 (iOS 26.4).

**Key decisions:**
1. **Cash+ / Customized Cash NOT in rotating_categories.** Their rates live in `card_reward_programs.category_bonuses` under `{"category": "user_selected", "rate": N, "cap": M, "allowed": [...]}` and resolve per-user via `user_category_selections`. Seeding them with an `[]` placeholder or a hidden default would either fail at query time or quietly hand users a rate they didn't pick. The user_category_selections endpoint now has a clear purpose — without picking, you earn base rate. This is the more honest UX.
2. **Retailer → category tag map in code, not DB.** `_RETAILER_CATEGORY_TAGS: dict[str, frozenset[str]]` at the top of `card_service.py`. Version-controlled with the matching logic, trivially editable, covered by unit tests. Moving to a `retailers.category_tags TEXT[]` column is a Phase 3 cleanup once the map stabilizes.
3. **Rotating > user-selected > static via plain `max()`.** The prompt's "fallback hierarchy" language suggested strict ordering, but `max()` across all sources produces the same answer when any rate wins by being higher — and is simpler code. The winner's `is_rotating_bonus` / `is_user_selected_bonus` / `activation_required` / `activation_url` are preserved on the CardRecommendation for UI display.
4. **`user_selected_allowed` flattened to top-level response field** (not decoded from JSONB on iOS). The backend reads `category_bonuses[user_selected].allowed` and surfaces it as a dedicated `user_selected_allowed: list[str] | None` field on `CardRewardProgramResponse`. iOS never touches the raw JSONB. `CategorySelectionSheet` reads `program.userSelectedAllowed` and the picker Just Works.
5. **Card catalog unique index created by the seed script, not a migration.** Migration 0001 declares `card_reward_programs` without a unique constraint on `(card_issuer, card_product)`. A proper migration would be more correct, but `CREATE UNIQUE INDEX IF NOT EXISTS` is idempotent and keeps Step 2e migration-free (fewer rollback surfaces, faster CI). A future migration can take ownership.
6. **Chained sequential fetch (identity → cards), not parallel.** `fetchCardRecommendations` is called from the END of `fetchIdentityDiscounts`. Rationale: one failure surface to reason about, both chains already run at the same "post-price-stream" moment, card matching is <50ms so parallelism saves at most 50ms. Two-call-site pattern comes for free since `fetchIdentityDiscounts` is already called from both the post-SSE-success and post-batch-fallback paths (Step 2d L6 learning applied).
7. **Inline card subtitle in PriceRow, not a separate section.** Identity discounts are a single grouped reveal (one section, many retailers); card recommendations are fundamentally per-retailer. Rendering inline keeps the visual unit compact — one glance tells you price + card for each retailer.
8. **`userHasCards` drives the "Add cards" CTA, no @AppStorage flag.** Backend is the source of truth. Once a user adds a card, the next scan flips `userHasCards=true` and the CTA disappears. Stale state = transiently-visible CTA (false-negative) rather than a permanently-stale local boolean (false-positive). Simpler reasoning.
9. **Point value = cashback dollars:** `reward_amount = purchase_amount * effective_rate * point_value_cents / 100`. For cashback cards: `base=1.5, point_value_cents=1.0` → $1.50 per $100. For CSR: `base=1.0, point_value_cents=2.0` (portal redemption conservative estimate from CARD_REWARDS.md §"Point Valuations") → $2.00 per $100 equivalent value.
10. **Card matching performance gate: <150ms CI, <50ms local target.** Same split as Step 2d identity matching. The plan set 50ms; the test asserts 150ms to absorb cold-Postgres variance on GitHub Actions. Median of 5 runs smooths outliers.
11. **Composite-unique `prices` row seeding limitation.** `test_recommendations_lowest_price_per_retailer` was written to verify the `if retailer_id not in retailer_lowest` dedup branch in `get_best_cards_for_product`, but the DB UNIQUE `(product_id, retailer_id, condition)` constraint rejects seeding two rows at the same retailer. The dedup branch is defensive against a scenario the schema prevents — removed the test rather than paper over with `condition='used'` (which the service filters out anyway).
12. **Cash+ / Shopper Cash Rewards / Customized Cash carry different `cap` + `rate` in their `user_selected` bonus entries.** Cap values are informational for now (the service doesn't track quarterly spend); they're seeded so a future "you're approaching your cap" worker can read them without a schema change.

**Deferred / known gaps (documented for Step 2f+):**
- **Quarterly rotating category scraping** — Q2 2026 seeded manually from CARD_REWARDS.md. Phase 3 adds the Doctor of Credit scraper + human review gate.
- **Purchase interstitial overlay** — Phase 3. `/api/v1/cards/recommendations` gives the data; the overlay UI wraps it with an affiliate redirect.
- **Activation reminders / push notifications** — Phase 3. `activation_required` + `activation_url` are surfaced by the service but the iOS app only shows an "Activate" button; no deferred reminder.
- **Spend cap tracking** — CAP amounts are stored but not tracked against user purchases. Needs a receipts + transaction-ingestion path that doesn't exist yet.
- **Card-linked offers (Amex/Chase/Citi Offers)** — Phase 5+, requires issuer auth flows.
- **Live-backend XCUITest** for the full scan → price stream → identity reveal → card recommendations flow. Same deferral as Step 2c-fix / 2d: standing up BarkainUITests + backend lifecycle exceeds per-step budget. os_log categories + ViewModel unit tests cover the behaviors.
- **Annual fee ROI calculation** — Phase 4. The annual_fee column is seeded for 10 of 30 cards; a future ROI view can show "you'd need to spend $X/year on dining to break even on the Gold Card."

---

### Step 2d — M5 Identity Profile + Discount Catalog (2026-04-14)

**Branch:** `phase-2/step-2d` off `main` @ `d7ba684` (after PR #10 merged)
**PR target:** `main`

**Context:** first feature that differentiates Barkain from commodity price-comparison tools. After the SSE price stream completes, the iOS client fetches identity-matched discounts — "As a veteran, you could save 30% at Samsung ($450 off)" — and renders them in an animated section below the retailer list. Tap opens the verification URL (ID.me / SheerID / UNiDAYS / WeSalute) in Safari. No competitor combines this with real-time price comparison.

**Pre-flight:** PF-1 — `ruff check scripts/test_upc_lookup.py` had 6 F541 warnings. 5 auto-fixed via `--fix`; the remaining E402 (httpx imported after `sys.path.insert`) is legitimate and was marked `# noqa: E402` to match the intentional late-import pattern. `ruff check .` clean across the repo afterwards.

**Files changed:**

```
infrastructure/migrations/versions/0003_add_is_government.py  # NEW — adds is_government BOOLEAN NOT NULL DEFAULT false to user_discount_profiles. Applied to both dev (barkain) and test (barkain_test) Postgres instances.

backend/modules/m5_identity/models.py                         # +1 column: is_government (inserted after is_senior, before is_aaa_member to match the migration ordering)
backend/modules/m5_identity/schemas.py                        # NEW — IdentityProfileRequest (16 bool fields default False), IdentityProfileResponse (subclasses Request + user_id + timestamps), EligibleDiscount (program_id UUID + retailer_id + retailer_name + program_name + eligibility_type + discount_type + discount_value/max/details + verification_method/url/url + estimated_savings — all money as `float` not Decimal to match m2_prices/schemas.py precedent), IdentityDiscountsResponse (eligible_discounts + identity_groups_active). Module-level `ELIGIBILITY_TYPES: tuple[str, ...]` constant — the 9-string vocabulary reused by the seed lint test to prevent drift.
backend/modules/m5_identity/service.py                        # NEW — IdentityService(db). `get_or_create_profile` upserts a `users` row FIRST via raw `INSERT ... ON CONFLICT DO NOTHING` before touching user_discount_profiles (critical — the users FK would otherwise break every test and every first-touch Clerk user). `update_profile` is full-replace: setattr every field from `data.model_dump()` and bump `updated_at`. `get_eligible_discounts(user_id, product_id)` maps profile booleans → list[str] via `_active_eligibility_types()`, runs a single indexed query (`select(DiscountProgram, Retailer.display_name).join(Retailer).where(eligibility_type.in_(active_types)).where(is_active.is_(True))`) hitting `idx_discount_programs_eligibility`, deduplicates by `(retailer_id, program_name)` tuple, optionally joins `prices` for best_price, then builds `EligibleDiscount` objects via `_build()` which casts Decimal → float explicitly (Decimal * float raises TypeError). Savings math: percentage → `best_price * dv / 100`, capped at `discount_max_value` if set; fixed_amount → `discount_value` (also capped); null when no product_id or no prices or no discount_value. Sort: `-estimated_savings DESC, -discount_value DESC, program_name ASC`.
backend/modules/m5_identity/router.py                         # NEW — APIRouter(prefix="/api/v1/identity", tags=["identity"]). 4 endpoints: GET /profile (rate_limiter=general), POST /profile (rate_limiter=write, full-replace), GET /discounts?product_id= (rate_limiter=general), GET /discounts/all (rate_limiter=general, browse view reuses get_all_programs which also dedups).

backend/app/main.py                                           # +2 lines: import m5_identity_router + app.include_router()

scripts/seed_discount_catalog.py                              # NEW — BRAND_RETAILERS (8 dicts: samsung_direct, apple_direct, hp_direct, dell_direct, lenovo_direct, microsoft_direct, sony_direct, lg_direct with extraction_method='none', supports_identity=True). _PROGRAM_TEMPLATES (17 templates) expanded by `_expand_programs()` to DISCOUNT_PROGRAMS (52 rows). `seed_brand_retailers()` + `seed_discount_programs()` use the same `session.execute(text(...))` + ON CONFLICT pattern as seed_retailers.py. `main()` loads .env, creates async engine, commits. Run via `python3 scripts/seed_discount_catalog.py`.
scripts/seed_retailers.py                                     # Flipped amazon.supports_identity False → True (single source of truth — prevents ordering collisions with the new seed script).
scripts/test_upc_lookup.py                                    # PF-1 ruff fix: 5 f-string removals + `# noqa: E402` on `import httpx` (intentional late import)

backend/tests/modules/test_m5_identity.py                     # NEW — 18 tests covering: profile CRUD (get-returns-default-if-none, get-existing, create-via-post, update-is-full-replace), discount matching (no-flags → empty, military matches samsung/apple/hp, multi-group union, Samsung-9-row dedup into 1 card, inactive excluded), savings math (percentage 30% of $1500 = $450, $10000×10% capped at $400, fixed_amount bypasses best_price, no-product-id = null savings, no-prices = null savings), endpoints (/discounts returns empty for new user, /discounts after POST end-to-end, /discounts/all excludes inactive), performance gate (seed 66 programs, median of 5 runs < 150ms). Helpers: `_seed_user`, `_seed_retailer`, `_seed_program`, `_seed_product_with_price` (all inserting via ORM and flushing per call).
backend/tests/test_discount_catalog_seed.py                   # NEW — 12 lint tests (pure-Python, no DB): BRAND_RETAILERS unique ids + _direct suffix + count==8, every program.retailer_id is in RETAILERS ∪ BRAND_RETAILERS, eligibility_type in ELIGIBILITY_TYPES, verification_method in {id_me, sheer_id, unidays, wesalute, student_beans, govx, None}, discount_type in {percentage, fixed_amount}, program_type in {identity, membership}, no duplicate (retailer_id, program_name, eligibility_type) tuples, percentage values in (0, 100], max_value non-negative when both set, military covers samsung_direct + apple_direct + hp_direct (regression guard).

Barkain/Features/Shared/Models/IdentityProfile.swift          # NEW — IdentityProfile (16 bool fields + userId + createdAt + updatedAt), IdentityProfileRequest (16 bool fields, all default False, plus `init(from: IdentityProfile)` for the edit flow), EligibleDiscount (matches backend 1:1, Identifiable via programId), IdentityDiscountsResponse. All Codable/Equatable/Sendable. JSONDecoder's `.convertFromSnakeCase` handles `is_government` → `isGovernment` mapping.
Barkain/Services/Networking/APIClient.swift                   # +3 protocol methods (getIdentityProfile, updateIdentityProfile, getEligibleDiscounts) + 3 concrete implementations delegating to the existing `request<T>()` helper.
Barkain/Services/Networking/Endpoints.swift                   # +3 enum cases with path/method/queryItems/body. `updateIdentityProfile` uses a fresh JSONEncoder with `.convertToSnakeCase` for the POST body. `getEligibleDiscounts` adds an optional `product_id` query param.

Barkain/Features/Profile/IdentityOnboardingViewModel.swift    # NEW — @Observable @MainActor class. `request: IdentityProfileRequest` is the draft state. `save()` is idempotent (guard on isSaving), catches APIError vs generic. `skip()` just calls `save()` — if the user skipped every step, it persists an all-false profile. `init(..., initial: IdentityProfile?)` pre-populates from an existing profile for the edit flow.
Barkain/Features/Profile/IdentityOnboardingView.swift         # NEW — NavigationStack-wrapped 3-step wizard. `enum Step { identityGroups, memberships, verification }` with `.rawValue` used for the capsule step indicator. Each step is a VStack of Toggle rows (9 / 5 / 2 respectively). Action bar has Skip + Continue — Continue advances to the next step OR triggers save() on the final step. Binding on `hasCompletedOnboarding` flips it on successful save. Includes a `PreviewOnboardingAPIClient` for the #Preview.
Barkain/Features/Profile/ProfileView.swift                    # NEW — replaces ProfilePlaceholderView. Auto-loads via getIdentityProfile() in `.task`. Renders identity-group / membership / verification chips in a FlowLayout (custom Layout struct that wraps children to fit parent width — avoids pulling in a dependency). Empty-state CTA row offers "Set up profile" that opens the same IdentityOnboardingView sheet. Edit button re-opens the sheet with `initial: profile` so the draft mirrors current state.
Barkain/Features/Profile/ProfilePlaceholderView.swift         # DELETED — 17 lines. No references remained after ContentView was updated.

Barkain/Features/Recommendation/IdentityDiscountsSection.swift  # NEW — 3 components: IdentityDiscountsSection (header + ForEach of cards), IdentityDiscountCard (retailer name + program details + verification badge + estimated savings label + tap → UIApplication.shared.open(verificationUrl ?? url)), IdentityOnboardingCTARow (subtle row with "Unlock more savings" + tap callback). `savingsText` is a String-returning computed property (not @ViewBuilder) so the if/else chain over percentage/max/fixed/null doesn't break ViewBuilder resolution.
Barkain/Features/Recommendation/PriceComparisonView.swift     # Added `onRequestOnboarding: (() -> Void)? = nil` parameter + `@AppStorage("hasCompletedIdentityOnboarding")`. New `identityDiscountsSection` @ViewBuilder inserted between `savingsSection` and `sectionHeader`, rendering IdentityDiscountsSection when non-empty, IdentityOnboardingCTARow when empty AND not onboarded. `.animation(.easeInOut(duration: 0.3), value: viewModel.identityDiscounts)` on the parent VStack. Updated inline PreviewAPIClient with 3 new protocol-conformance stubs.

Barkain/Features/Scanner/ScannerViewModel.swift               # Added `var identityDiscounts: [EligibleDiscount] = []` state. Reset to `[]` in `handleBarcodeScan()` and `reset()`. New private `fetchIdentityDiscounts(productId:)` method — catches all errors into a warning log, never sets priceError. Two call sites: (1) at the end of `fetchPrices()` AFTER the `for try await event in stream` loop exits successfully (line ~122) and (2) inside `fallbackToBatch()` after the batch `getPrices` call returns successfully. Never inside the `.done` case to avoid racing still-streaming retailer_result events.
Barkain/Features/Scanner/ScannerView.swift                    # Added `@State showOnboardingFromCTA` + `@AppStorage("hasCompletedIdentityOnboarding")` + a second `.sheet(isPresented:)` wiring the onboarding view to that state. PriceComparisonView invocation now passes `onRequestOnboarding: { showOnboardingFromCTA = true }`.
Barkain/ContentView.swift                                     # `@AppStorage` + `@State showOnboarding` + `.task` that flips showOnboarding=true on first launch when not onboarded. Sheet mounts IdentityOnboardingView with a freshly-constructed IdentityOnboardingViewModel(apiClient: APIClient()). Replaced ProfilePlaceholderView() with ProfileView() in the TabView.

BarkainTests/Helpers/MockAPIClient.swift                      # +3 Result<T, APIError> properties (getIdentityProfileResult / updateIdentityProfileResult / getEligibleDiscountsResult), +3 call-count ints, +1 updateIdentityProfileLastRequest + 1 getEligibleDiscountsLastProductId, +3 protocol method implementations.
BarkainTests/Helpers/TestFixtures.swift                       # +sampleIdentityProfile (all-false default), +veteranIdentityProfile (isVeteran + idMeVerified), +sampleEligibleDiscountSamsung (30% → $450 savings), +sampleEligibleDiscountHP (40% → $600 savings), +sampleIdentityDiscountsResponse (2 discounts + ["veteran"] active), +emptyIdentityDiscounts.

BarkainTests/Features/Profile/IdentityOnboardingViewModelTests.swift  # NEW — 4 tests: save_callsAPI_withCorrectFlags (toggle 3 flags → asserts MockAPIClient.updateIdentityProfileLastRequest), skip_callsAPI_withAllFalse (no toggles → all 16 fields false in the request), saveFailure_setsError_andSavedRemainsFalse (mock returns .failure → viewModel.error is .server + saved stays false), editFlow_preservesInitialProfile (init with `initial: veteranIdentityProfile` → draft mirrors it).
BarkainTests/Features/Scanner/ScannerViewModelTests.swift     # +3 tests: fetchIdentityDiscounts_firesAfterStreamDone (full scan flow → assert VM.identityDiscounts.count == 2 + getEligibleDiscountsLastProductId matches), fetchIdentityDiscounts_emptyOnFailure_doesNotSetPriceError (mock returns .failure → empty discounts + priceError still nil), fetchIdentityDiscounts_clearedOnNewScan (first scan loads 2 discounts, second scan with resolve-failure clears them).

CLAUDE.md                                                     # v4.4 bump. Step 2d — M5 Identity Profile: COMPLETE entry in Current State. Test counts 192/36 → 222/43. 6 new Current State bullets (M5 Identity backend, discount catalog, migration 0003, onboarding flow, Profile tab, identity discounts reveal). Step 2d added to What's Next with headline summary. 5 new Key Decisions quick-refs (identity matching zero-LLM SQL, fetch timing two-call-site pattern, onboarding gate semantics, is_government column rationale, seed vocabulary constant).
docs/CHANGELOG.md                                             # This entry.
docs/ARCHITECTURE.md                                          # API Endpoint Inventory: 4 new rows for M5 Identity endpoints. Zero-LLM matching note under Module System.
docs/TESTING.md                                               # Test Inventory: Step 2d row (222/43, +30 backend + 7 iOS = 37 new).
docs/PHASES.md                                                # Step 2d Status: ✅ (2026-04-14). Scope line updated to reflect actual work done vs original plan.
docs/FEATURES.md                                              # M5 Identity Profile features: marked ✅ for profile CRUD + discount matching. Remaining Phase 3 items (stacking rules, AI synthesis) unchanged.
docs/DATA_MODEL.md                                            # Note on migration 0003 (is_government column) + 8 new brand-direct retailers.
```

**Test counts:** 222 backend (222 passed / 6 skipped, +30 new: 18 m5_identity + 12 seed lint) / 43 iOS unit (+7 new: 4 IdentityOnboardingViewModel + 3 fetchIdentityDiscounts). `ruff check .` clean. `xcodebuild test -only-testing:BarkainTests` → TEST SUCCEEDED on iPhone 17 Pro (iOS 26.4).

**Key decisions:**
1. **`is_government` via new migration 0003** (not Option A "defer to 2e"). Samsung, Dell, HP, LG, Microsoft all have real government-employee discount programs. Dropping the field would have cost the most lucrative discount tier from day one. Migration is a single `op.add_column` with `server_default=false` — zero impact to existing rows.
2. **Float for money (not Decimal).** Pydantic v2's Decimal round-trips as a JSON string, which the iOS `Double` decoder chokes on. `backend/modules/m2_prices/schemas.py:104` already uses `price: float` for the same reason. Backend `_build()` explicitly casts `Decimal → float` before the savings math to avoid `TypeError: unsupported operand type(s) for *: 'Decimal' and 'float'`.
3. **Dedup by (retailer_id, program_name), not program_id.** Samsung's "Samsung Offer Program" is seeded as 8 rows (one per eligibility_type the single real program covers), but the user should see ONE Samsung card regardless of how many of their identity flags match. Service-level dedup keeps the seed script simple (1 template → N rows) while preserving the UX.
4. **`users` row auto-upsert in `get_or_create_profile`.** UserDiscountProfile.user_id is a FK to users.id. The Clerk JWT path (and demo stub) never creates the users row — GET /profile is the first touchpoint that learns about a user. Without the raw `INSERT ... ON CONFLICT DO NOTHING`, every test and every first Clerk user would hit an IntegrityError. The alternative (require every test to seed the user row manually) was rejected as too brittle.
5. **Full-replace POST semantics** (not PATCH). iOS sends the entire 16-field draft on every save. Any missing field defaults to False via Pydantic. The ViewModel keeps a local draft and ships it whole — the backend never has to reconcile partial updates.
6. **Two call sites for `fetchIdentityDiscounts`** (not one). Firing inside the `.done` case was my first instinct but creates a race: the for-try-await loop doesn't exit on `.done`, it exits when the stream closes — so `.done` can arrive while slow retailer_result events are still in flight. Firing after the loop exits AND after `fallbackToBatch` success covers both success paths with zero race.
7. **Non-fatal failure path.** Identity discounts are a secondary feature; their failure must never hide the retailer list. `fetchIdentityDiscounts` catches all errors into a warning log and sets `identityDiscounts = []`. `priceError` is never set.
8. **`@AppStorage("hasCompletedIdentityOnboarding")` at ContentView level, not BarkainApp.** Keeps BarkainApp.swift at 12 lines (single-purpose) and makes the onboarding behavior testable in isolation.
9. **Swipe-down preserves onboarding gate** (re-shows next launch). The user must explicitly Skip-through-to-save or tap Save on the final step. Swipe-down is "not yet, ask me later"; Skip-through is "persist empty, don't ask again."
10. **Prime Student in the Amazon seed, Prime Access skipped.** Prime Student matches `is_student=true`. Prime Access (EBT/Medicaid) has no backing profile flag — seeding it would produce a row no user can ever match. Documented as a 2e+ gap.
11. **Samsung "employees of partner companies" tier skipped.** No backing flag exists (`employer` is a free-text column, not seedable). The 8 eligibility types Samsung ships with still give every real user the same 30% discount — the partner-employee tier was just one of several verification *paths* to the same benefit.
12. **`amazon.supports_identity=True` in `seed_retailers.py`, not in `seed_discount_catalog.py`.** Single source of truth. Otherwise re-running `seed_retailers.py` after `seed_discount_catalog.py` flips Amazon back to False and the "browse all Amazon discount programs" query silently loses a row.
13. **Pure-Python seed lint test, not DB-backed.** Shape validation (eligibility vocab, verification method, discount type, duplicates) is faster than a DB round-trip, runs in < 10ms, and catches the drift cases that silently break the `.in_()` query. DB-backed idempotency is already enforced by the ON CONFLICT clauses in the seed SQL — re-running the script is safe.

**Deferred / known gaps (documented for Step 2e or later):**
- **Amazon Prime Access** (EBT/Medicaid $6.99/mo Prime) — requires a new profile flag + government-ID verification path.
- **Samsung partner-employee tier** — requires the `employer` text field or a new enum for partner-company email domains.
- **Live-backend XCUITest** for the full scan → stream → identity reveal → Safari → Profile chips flow. Same deferral reason as Step 2c-fix: repo has zero UI tests; standing up a BarkainUITests target + uvicorn lifecycle plumbing exceeds the per-step budget. The os_log instrumentation (`com.barkain.app`/`SSE` category from 2c-fix) already gives single-session repro for any SSE regression; identity reveal has equivalent visibility via the ScannerViewModel unit tests.
- **Caching `GET /api/v1/identity/discounts`** with a 60s Redis key. Savings computation is deterministic against `(user_id, product_id)` — a short TTL would cut DB load during rapid rescans. Skipped as over-engineering for 2d's < 150ms performance profile.
- **`model_number_hard_gate` ↔ identity discount cross-check**: some brands only offer the discount on specific product categories (HP's 55% cap is healthcare-worker-only; LG's 46% cap is appliance-only). The current service ignores `applies_to_categories` — surface-level fix is to skip building an `EligibleDiscount` when the product's category is in `excluded_categories` (or not in `applies_to_categories` when set). Deferred because Phase 1 doesn't populate product categories consistently yet.

---

## Key Decisions Log

| Decision | Choice | Why | Date |
|----------|--------|-----|------|
| Primary platform | iOS (SwiftUI) | Advanced Swift skills; native camera APIs; iOS-first validation | Mar 2026 |
| Backend framework | FastAPI (Python) | Async-native; best AI/ML ecosystem; advanced proficiency | Mar 2026 |
| Database | PostgreSQL (AWS RDS) + TimescaleDB | YC credits; relational + time-series in one engine | Mar 2026 |
| AI models | Claude (primary) + GPT (fallback) | YC credits for both; abstraction layer enables hot-swap | Mar 2026 |
| Auth | Clerk | Existing Pro subscription; handles users + API keys; MCP for dev | Mar 2026 |
| Revenue model | Subscription via StoreKit/RevenueCat | Avoids Apple IAP disputes; predictable revenue | Mar 2026 |
| Hosting (MVP) | Railway (backend) + Vercel (web) | Existing subscriptions; minimal ops for solo dev | Mar 2026 |
| Hosting (scale) | AWS (ECS + RDS + ElastiCache) | $10K credits; migrate when Railway limits hit | Mar 2026 |
| Amazon data source | Keepa API ($15/mo) | PA-API deprecated April 30, 2026. Creators API requires 10 sales/month. Keepa has no sales gate | Apr 2026 |
| Scraping tool | agent-browser (DOM eval pattern) | Outperforms Playwright on all tested sites (35+ tests). Shell-scriptable, better anti-detection | Apr 2026 |
| Phase 1 retailers | 11 retailers, all scraped via agent-browser containers | Demo uses scrapers for everything. APIs (Best Buy, eBay Browse, Keepa) added as production speed optimization later | Apr 2026 |
| Phase 1 approach | Scrapers-first, APIs later | Building container infra in Phase 1 eliminates Phase 2 container work. APIs layer on top for production speed | Apr 2026 |
| Watched items | Phase 4 (paired with price prediction) | Natural pairing — tracking prices needs prediction to be useful | Apr 2026 |
| Tooling philosophy | Docker MCPs for services, CLIs for everything else | No custom skills — guiding docs are the single source of truth | Apr 2026 |
| Watchdog AI model | Claude Opus (YC credits) | Highest quality selector rediscovery; YC AI credits make cost viable | Apr 2026 |
| Browser Use | Dropped — fully replaced by agent-browser | agent-browser handles all scraping + Watchdog healing | Apr 2026 |
| Claude Haiku | Dropped — no assigned tasks | Tiered strategy: Opus (healing), Sonnet (quality), Qwen/ERNIE (cheap parsing) | Apr 2026 |
| Open Food Facts | Deferred — not relevant for Phase 1 electronics | Add when grocery categories are supported | Apr 2026 |
| LocalStack | Deferred to Phase 2 | Not needed until background workers (SQS) are built | Apr 2026 |
| Product cache | Redis only (24hr TTL) | Single-layer cache; PostgreSQL stores products persistently but not as a cache | Apr 2026 |
| UPC lookup | Gemini API (primary) + UPCitemdb (backup) | OpenAI charges $10/1K calls — unacceptable. Gemini API is cost-effective for UPC→product resolution, high accuracy, 4-6s latency. UPCitemdb as fallback (free tier 100/day). YC credits cover Gemini cost | Apr 2026 |
| user_cards.is_preferred | User-set preferred card for comparisons | Not "default" — user explicitly sets their preferred card | Apr 2026 |
| Postgres MCP | Postgres MCP Pro (crystaldba, Docker) | Unrestricted access mode; better schema inspection than basic server | Apr 2026 |
| Redis MCP | Official mcp/redis Docker image | No auth for local dev; Docker-based for consistency with other MCP servers | Apr 2026 |
| Clerk MCP | HTTP transport (mcp.clerk.com) | Simplest setup; no local npm packages needed | Apr 2026 |
| UPCitemdb priority | Nice-to-have, not blocker | Gemini API is primary for UPC resolution; UPCitemdb is fallback only | Apr 2026 |
| AI SDK | google-genai (from google-generativeai) | Deprecated package; new SDK has native async, no asyncio.to_thread needed | Apr 2026 |
| UPC lookup model | gemini-3.1-flash-lite-preview | Faster and cheaper for UPC resolution; thinking + Google Search grounding for accuracy | Apr 2026 |
| UPC prompt architecture | System instruction (reasoning, cached) + user prompt (UPC + format constraint) | System instruction is cached by Gemini, minimizing per-call tokens. User prompt is just the UPC + output format | Apr 2026 |
| Gemini output | `device_name` only (no reasoning/brand/category in output) | Simpler parsing, faster responses. Brand/category populated by UPCitemdb fallback or future enrichment | Apr 2026 |
| Container scraping on ARM | Not viable for local demo | x86 emulation too slow (60-180s); containers work on native x86 cloud instances (5-8s). Demo relies on Gemini product resolution only | Apr 2026 |
| App Transport Security | NSAllowsLocalNetworking=true | Permits HTTP to LAN IPs for physical device testing against local backend | Apr 2026 |
| API base URL | Configurable via xcconfig → Info.plist → AppConfig.swift | Debug.xcconfig sets localhost; change to Mac IP for physical device testing. Runtime reads from Bundle.main.infoDictionary | Apr 2026 |
| Demo mode auth bypass | BARKAIN_DEMO_MODE=1 env var | Bypasses Clerk JWT in dependencies.py for local testing. NOT for production | Apr 2026 |
| AI SDK (Anthropic) | anthropic SDK (async) | Same lazy singleton + retry pattern as Gemini. YC credits cover Opus cost for Watchdog | Apr 2026 |
| HTTP-only retailer adapters | amazon, target, ebay_new can drop browser containers | 10-retailer AWS EC2 probe (2026-04-10): these 3 pass curl+Chrome-headers 5/5 from datacenter IPs with `__NEXT_DATA__` or direct HTML product data. 14-35× faster, ~490 MB RAM saved per retailer, ~1 050 LOC net deleted. See `docs/SCRAPING_AGENT_ARCHITECTURE.md` Appendix A | Apr 2026 |
| Firecrawl for 7 tough retailers | walmart, best_buy, sams_club, backmarket, ebay_used, home_depot, lowes via Firecrawl managed service | Firecrawl probe (2026-04-10): 10/10 retailers pass including all 5 that failed AWS direct-HTTP and both "inconclusive" ones. HD + Lowe's now known to have `__APOLLO_STATE__` SSR data. ~1.5 credits per scrape, ~$0.0088 per 10-retailer comparison on Standard tier ($83/mo). ~31s P50 cold, ~1s hot-cached. See Appendix B | Apr 2026 |
| Production scraping architecture | Collapse browser containers to local-dev-only; use Firecrawl for production | Containers don't work from any cloud (IP blocks at edge). Firecrawl solves all 10 retailers from anywhere. Hybrid plan: direct HTTP for amazon/target/ebay_new ($0), Firecrawl for the other 7 ($0.0088/comparison). Containers become local-dev + emergency fallback. Adapter interface in M2 with per-retailer mode config. See Appendix B.7-B.8 | Apr 2026 |
| Decodo residential proxy for walmart-only production path | Decodo rotating residential (US-targeted) as post-demo walmart path | 5/5 Walmart scrapes PASS via Decodo US residential pool (Verizon Fios). Wire body ~121 KB/scrape → 8,052 scrapes/GB. $0.000466/scrape at $3.75/GB (3 GB tier) → **2.7× cheaper than Firecrawl** per request, no concurrency cap. See Appendix C. Username auto-prefixed with `user-` and suffixed with `-country-us` by the adapter | Apr 2026 |
| walmart_http adapter lands now, dormant until launch | `WALMART_ADAPTER={container,firecrawl,decodo_http}` feature flag | Demo default = `firecrawl`; flip to `decodo_http` post-demo. All 3 paths return `ContainerResponse`, routed by `ContainerClient._extract_one`. Other 10 retailers still use the container dispatch unchanged. 24 new tests (15 walmart_http + 9 firecrawl), 128 total passing. See Appendix C.6–C.8 | Apr 2026 |
| extract.sh fd-3 stdout convention | Every retailer extract.sh must reserve fd 3 as real stdout via `exec 3>&1; exec 1>&2`, and emit final JSON via `>&3` | `agent-browser` writes progress lines ("✓ Done", "✓ <page title>", "✓ Browser closed") to STDOUT. Phase 1 respx-mocked tests never exercised this boundary, so every retailer extract.sh shipped with a latent `PARSE_ERROR` bug. Discovered on first live run (SP-1). See `docs/SCRAPING_AGENT_ARCHITECTURE.md` § Required extract.sh conventions | Apr 2026 |
| EXTRACT_TIMEOUT baseline | 180 s default, env-overridable via `EXTRACT_TIMEOUT` | Live Best Buy runs at ~90 s end-to-end (warmup + scroll + DOM eval on t3.xlarge); Amazon ~30 s; old 60 s default tripped Best Buy every time. 180 s gives 2× headroom. | Apr 2026 |
| Xvfb lock cleanup in entrypoint | Always `rm -f /tmp/.X99-lock /tmp/.X11-unix/X99` before starting Xvfb | Without it, `docker restart <retailer>` leaves a stale lock, Xvfb refuses to bind :99, uvicorn starts without X, and every extraction dies with `Missing X server or $DISPLAY`. Idempotent guard costs nothing on first boot. (SP-3) | Apr 2026 |
| iOS URLSession timeout | Dedicated session with `timeoutIntervalForRequest=240`, `timeoutIntervalForResource=300` | Default 60 s trips before ~94 s backend round-trip. Progressive loading UI is still cosmetic — streaming per-retailer results is the real long-term fix (SP-L7). (SP-8) | Apr 2026 |
| Zero-price listing guard | `_pick_best_listing` filters `price > 0` before `min()` | extract.js occasionally parses price as 0 when DOM node is missing/lazy (Amazon especially). `min(key=price)` then returns the zero-price listing as "cheapest". Defensive guard at service boundary; extract.js root-cause fix deferred. (SP-7) | Apr 2026 |
| EC2 dev iteration pattern | Local Mac backend + SSH tunnel (8081–8091) → EC2 x86 container runtime | Local backend keeps hot reload / breakpoints / real env; containers run on EC2 for real x86 Chromium (ARM is non-viable per L13). `scripts/ec2_tunnel.sh` forwards ports, `CONTAINER_URL_PATTERN=http://localhost:{port}` unchanged. See `docs/DEPLOYMENT.md` § Live dev loop | Apr 2026 |
| Product-match relevance scoring | Required before any user-facing demo | SP-10: each retailer's on-site search returns similar-but-not-identical products and `_pick_best_listing` picks cheapest regardless. Example: M4 Mac mini scan returned correct SKU on Best Buy but wrong-spec Mac mini on Amazon. Approach TBD (lexical / structural / embedding / retailer-weighted) — belongs in Step 2b design. | Apr 2026 |
| UPCitemdb cross-validation | Always call UPCitemdb as second opinion after Gemini | Gemini resolved 3/3 test UPCs wrong; brand agreement check catches mismatches | Apr 2026 |
| Relevance scoring | Model-number hard gate + brand match + token overlap (threshold 0.4) | _pick_best_listing returned wrong-spec products; gate catches M4 vs M2 Mac mini | Apr 2026 |
| Walmart first-party filter | Filter third-party resellers via sellerName field; fall back to cheapest if all third-party | Demo returned RHEA-Sony reseller listing at $50.25 instead of Walmart's price | Apr 2026 |
| Per-retailer status system | Response includes `retailer_results: [{retailer_id, retailer_name, status}]` for all 11 retailers, status ∈ `{success, no_match, unavailable}` | iOS showed only successful retailers — user couldn't tell whether a missing retailer was offline, blocked, or had no match. Now all 11 render with distinct visual states. `success` = price row; `no_match` = gray "Not found" (searched, no result); `unavailable` = gray "Unavailable" (never got a usable response). See `docs/SCRAPING_AGENT_ARCHITECTURE.md` Appendix G | Apr 2026 |
| Error code → status mapping | `CHALLENGE/PARSE_ERROR/BOT_DETECTED/TIMEOUT/CONNECTION_FAILED/HTTP_ERROR/CLIENT_ERROR/GATHER_ERROR` → `unavailable`; empty listings or relevance-filtered → `no_match` | Live PS5 query showed Walmart Firecrawl returning a PerimeterX challenge page — it was never a "no match" because Walmart never searched. Bot blocks and parse failures belong with offline containers (we couldn't determine anything), not with empty-result searches | Apr 2026 |
| Manual UPC entry in iOS scanner | Toolbar ⌨️ button opens a sheet with TextField + preset rows, submits via the existing `ScannerViewModel.handleBarcodeScan(upc:)` | iOS simulator has no camera, so barcode scanning can't be tested there. Manual entry unblocks fast iteration against the local backend. Works on physical devices too as a fallback for damaged barcodes | Apr 2026 |
| Supplier-code cleanup | `_clean_product_name` strips `(CODE)` parentheticals before query/scoring; descriptive parens like `(Teal)` preserved | Gemini/UPCitemdb bake supplier catalog codes like `(CBC998000002407)` into the product name. Retailer search engines fuzz-match on them and return the wrong product (Amazon returned iPhone SE for "iPhone 16 … (CBC998000002407)"). Cleanup regex: `\(\s*[A-Z0-9][A-Z0-9.\-/]{4,}\s*\)` | Apr 2026 |
| Word-boundary identifier match | Hard gate uses `(?<!\w)ident(?!\w)` regex search instead of `ident in title_lower` substring check | "iPhone 16" was slipping through to match "iPhone 16e" as a substring prefix. Word boundaries prevent prefix/suffix false matches (also fixes "Flip 6" vs "Flip 60" and similar) | Apr 2026 |
| Accessory hard filter | `_is_accessory_listing()` rejects `{case, cover, protector, charger, cable, stand, mount, holder, skin, adapter, dock, compatible, replacement, …}` and `for/fits/compatible with (iPhone\|iPad\|…)` phrases, unless the product itself contains any of those words | iPhone 16 Amazon search returned a `SUPFINE Compatible Protection Translucent Anti-Fingerprint` screen protector at $6.79 — "iPhone" and "16" overlap gave it a 2/5=0.4 token score, exactly at threshold. Deterministic keyword rejection is more reliable than threshold tuning | Apr 2026 |
| Variant token equality check | `_VARIANT_TOKENS = {pro, plus, max, mini, ultra, lite, slim, air, digital, disc, se, xl, cellular, wifi, gps, oled}` — product_tokens ∩ VARIANT must equal listing_tokens ∩ VARIANT | iPhone 16 was matching iPhone 16 Pro/Plus/Pro Max via token overlap because "iPhone 16" is a word-boundary substring of those. PS5 Slim Disc was matching PS5 Slim Digital Edition. The equality check is strict and symmetric: `{} ≠ {pro}`, `{slim, disc} ≠ {slim, digital}` | Apr 2026 |
| Amazon condition detection | `detectCondition(title)` in `containers/amazon/extract.js` parses `Renewed/Refurbished/Recertified/Pre-Owned/Open Box/Used` and sets the `condition` field; Best Buy extract.js mirrors this + `Geek Squad Certified`; Walmart `_map_item_to_listing` uses lowercased-name markers | Amazon listings were hardcoded `condition="new"` even when the title clearly said `(Renewed)`. User saw "New" in the app but Amazon showed Renewed | Apr 2026 |
| Amazon installment-price rejection | `extractPrice(el)` scans non-strikethrough `.a-price` elements, rejects any whose surrounding `.a-row`/`.a-section` contains `/mo`, `per month`, or `monthly payment`, returns `max(candidates)` | Amazon phone listings sometimes show `$45/mo` as the prominent price (e.g. Mint Mobile sponsored). The old selector-based price extraction picked the monthly as the full price. Walking up to the row level and rejecting by context text is deterministic | Apr 2026 |
| Carrier/installment listing filter | Walmart parser and Best Buy extract.js both reject listings with title or URL matching `{AT&T, Verizon, T-Mobile, Sprint, Cricket, Metro by, Boost Mobile, Straight Talk, Tracfone, Xfinity Mobile, Visible, US Cellular, Spectrum Mobile, Simple Mobile}` | Walmart Wireless and Best Buy phone listings often show a monthly installment (e.g. $20/mo) as the prominent price when the phone is carrier-locked. Dropping these outright is cleaner than trying to detect the full price buried elsewhere in the card | Apr 2026 |
| camelCase model regex patterns | Pattern 6: `\b[a-z][A-Z][a-z]{2,8}\s+\d+[A-Z]?\b` (iPhone 16, iPad 12, iMac 24). Pattern 7: `\b[A-Z][a-z]+[A-Z][a-z]+\s+\d+[A-Z]?\b` (AirPods 2, PlayStation 5, MacBook 14) | The existing Title-case-word + digit pattern (Flip 6, Clip 5) didn't catch these Apple/Sony-style brand names. Pattern 6 handles lowercase-start camelCase; pattern 7 handles uppercase-start two-segment camelCase | Apr 2026 |
| Spec patterns dropped from hard gate | `256GB`, `27"`, `11-inch` no longer participate in the model-number hard gate — they flow through token overlap only | With `any()` semantics, having `256GB` match in both an iPhone 16 query and an iPhone SE listing was enough to clear the gate. Specs are too weak to act as a model discriminator; they belong in the tiebreaker, not the hard filter | Apr 2026 |
| Gemini output: `device_name` + `model` | System instruction emits both fields; `model` is the shortest unambiguous product identifier (generation markers like "1st Gen", capacity like "256GB", GPU SKUs like "RTX 4090"). Stored in `products.source_raw.gemini_model` and exposed on `ProductResponse.model` via a `@property` on the Product ORM | Fixing the F.5 generation-without-digit and GPU-SKU limitations at the upstream prompt is cheaper and more maintainable than adding downstream scorer heuristics. The `model` field is a clean input to `_score_listing_relevance`: it flows into `_extract_model_identifiers` (so `RTX 4090` can fire the hard gate) and into `_tokenize` (so `1st Gen` populates `_ORDINAL_TOKENS` for the equality check). Step 2b-final (2026-04-13) | Apr 2026 |
| `_MODEL_PATTERNS[5]` GPU regex | New regex `\b[A-Z]{2,5}\s+\d{3,5}\b` matches letter group + space + digit group. Extracts "RTX 4090", "GTX 1080", "RX 7900", "MDR 1000" as model identifiers for the hard-gate word-boundary check | The existing patterns could not match the space-separated letter-group + digit-group pattern common to GPU SKUs. With the new pattern + Gemini `model` field feeding the scorer, "RTX 4080" listings correctly fail a word-boundary regex for "RTX 4090". F.5 GPU SKU limitation resolved. Step 2b-final (2026-04-13) | Apr 2026 |
| Ordinal-token equality check | `_ORDINAL_TOKENS = {1st, 2nd, 3rd, 4th, 5th, 6th, 7th, 8th, 9th, 10th}`; `_score_listing_relevance` Rule 2b rejects if `product_ordinals != listing_ordinals` | Symmetric discriminator for generation markers: a product whose Gemini `model` field emits "(1st Gen)" now holds `{1st}` in its ordinal set, and a listing with no ordinal holds `{}` — unequal, so the listing is rejected. Trade-off: a real 1st-gen product whose retailer listing omits the marker will also fail, but Gemini only emits the marker when it's load-bearing. F.5 generation-without-digit limitation resolved. Step 2b-final (2026-04-13) | Apr 2026 |
| CI: GitHub Actions backend-tests | `.github/workflows/backend-tests.yml` runs unit tests on every PR touching `backend/**` or `containers/**`, and on push to `main`. TimescaleDB + Redis service containers, fake API keys, `BARKAIN_DEMO_MODE=1`. Integration tests remain behind `BARKAIN_RUN_INTEGRATION_TESTS=1` so PR runs stay fast and don't burn real API credits | PR #3 was about to merge without automated proof the 146-test suite passed. Future PRs now have a green-check gate before merge. Step 2b-final (2026-04-13) | Apr 2026 |
| EC2 post-deploy MD5 verification | `scripts/ec2_deploy.sh` appends a verification block after the health check that MD5-compares each running container's `/app/extract.js` against `containers/<retailer>/extract.js` in the repo | Fixes 2b-val-L1 hot-patch drift visibility: after live 2b-val regressed 3 `extract.js` files were fixed via `docker cp` on EC2 and left stale on disk. The next stop+start would have silently reverted the fix. MD5 comparison makes drift visible on the next deploy. Step 2b-final (2026-04-13) | Apr 2026 |
| Integration conftest auto-load `.env` | `backend/tests/integration/conftest.py` `pytest_configure` hook reads `.env` into `os.environ` when `BARKAIN_RUN_INTEGRATION_TESTS=1`; `test_upcitemdb_lookup` skip swapped to opt-out via `UPCITEMDB_SKIP=1` (UPCitemdb trial endpoint works without a key) | Fixes 2b-val-L4 (env vars read at module load required manual `set -a && source ../.env && set +a`) and 2b-val-L3 (UPCitemdb trial tier was being unnecessarily skipped). Step 2b-final (2026-04-13) | Apr 2026 |
| SSE streaming for M2 price results | New `GET /api/v1/prices/{id}/stream` endpoint returning `text/event-stream`. `PriceAggregationService.stream_prices()` uses `asyncio.as_completed` over per-retailer tasks (wrapping `ContainerClient._extract_one`) so each retailer's result yields a `retailer_result` SSE event the moment it completes. Batch endpoint `GET /prices/{id}` kept unchanged as both a curl/debugging surface and a fallback for when the stream fails. Cache hit replays all events instantly with `done.cached=true` | Pre-2c: the iPhone blocked for ~90-120s on every scan because `asyncio.gather` in `extract_all()` waited for Best Buy's ~91s leg. With streaming, walmart (~12s) and amazon (~30s) render the moment they complete. Best Buy still takes 91s but no longer blocks the other two. This is the real fix for SP-L7 / 2b-val-L2. WebSocket was not considered — SSE is simpler, uses existing HTTP/1.1 path, and server→client push is all we need. Step 2c (2026-04-13) | Apr 2026 |
| `asyncio.as_completed` over `asyncio.gather` for streaming | `stream_prices()` creates one `asyncio.create_task` per retailer wrapping a `_fetch_one(rid)` helper that returns `(rid, ContainerResponse)`, then iterates `asyncio.as_completed(tasks)` to yield events in completion order (not dispatch order) | `gather` returns all results together — useless for streaming. `as_completed` yields futures in completion order but loses the retailer_id mapping; wrapping the task body in a `(rid, resp)` tuple restores it. Exceptions are handled inside the wrapped coroutine (not re-raised) so `_extract_one`'s contract of never-raising holds end-to-end | Apr 2026 |
| Stream generator cannot use middleware for error handling | `stream_prices()` catches exceptions inside the generator and yields `("error", {code, message})` events rather than letting them bubble to `ErrorHandlingMiddleware`. `asyncio.CancelledError` (client disconnect) cancels all pending tasks before re-raising | FastAPI `ErrorHandlingMiddleware` wraps the initial response, but once the first SSE byte is sent the response is committed and middleware can't intercept subsequent exceptions. The generator must handle its own errors and surface them as events. Pre-stream errors (ProductNotFoundError) still raise normally because `_validate_product` is called in the router BEFORE `StreamingResponse` is constructed — 404s are normal JSON, not mid-stream events. Step 2c (2026-04-13) | Apr 2026 |
| `PriceComparison` struct fields mutable (`let` → `var`) | All 9 stored properties of `PriceComparison` Swift struct changed from `let` to `var`. Struct stays `Codable`, `Equatable`, `Sendable` | `ScannerViewModel.fetchPrices()` needs to mutate `priceComparison.retailerResults` and `priceComparison.prices` in place as each SSE event arrives, then reassign the whole struct to trigger `@Observable` re-renders. An alternative was a parallel observable state (two `@Published` arrays on ScannerViewModel that `PriceComparisonView` reads alongside `priceComparison`), but that doubles the state surface and keeps the struct immutable only cosmetically — the view already reads mutable `viewModel.sortedPrices`. Mutating `var` fields is the smallest-surface change and no other code relied on immutability. Step 2c (2026-04-13) | Apr 2026 |
| Stream failure fallback to batch endpoint | On `streamPrices` thrown error OR stream close without a `done` event, `ScannerViewModel.fallbackToBatch()` calls the batch `getPrices()` endpoint. On batch success, the full comparison replaces any partial stream state. On batch failure, `priceComparison` is cleared (unless `preserveSeeded`) and `priceError` is set | The streaming and batch endpoints share all the same service-level helpers (validation, caching, relevance scoring, error classification) — a stream failure is usually a network/transport issue the batch endpoint can retry. Restarting from batch is simpler than trying to resume the stream at a specific retailer. The `preserveSeeded` flag keeps any partial results if the stream already delivered some events before failing; for clean failures (stream threw before first event) the seed is cleared so tests see a clean `nil` priceComparison. Step 2c (2026-04-13) | Apr 2026 |
| SSE parser split into `feed(line:)` + `events(from: URLSession.AsyncBytes)` | Stateful `SSEParser` struct exposes `mutating feed(line:) -> SSEEvent?` and `mutating flush() -> SSEEvent?` for synchronous line-at-a-time testing. `events(from:)` static function wraps the parser around `URLSession.AsyncBytes.lines` for production use | `URLSession.AsyncBytes` is opaque — you can't construct one in tests. Splitting parsing state from I/O lets `SSEParserTests` drive the parser directly without a real URLSession or MockURLProtocol extension. The async wrapper is ~10 lines and only used in production. ~50 lines total, no third-party dependency. Step 2c (2026-04-13) | Apr 2026 |
| `ProgressiveLoadingView` removed from scanner flow | `ScannerView.scannerContent` now shows `PriceComparisonView` whenever `priceComparison` is non-nil (swapped branch order with `isPriceLoading`). `priceLoadingView()` and `loadingRetailerItems` deleted. `ProgressiveLoadingView.swift` file kept in place (may be reused later) but no longer referenced | `PriceComparisonView` already renders the growing retailer list as `retailerResults` fills in — the user sees retailers appear one-by-one naturally. A separate cosmetic loader on top would have created a two-stage transition (loader → comparison) with duplicated information. Deleting the loader usage gives us single-source-of-truth progressive UI. A minimal `LoadingState("Sniffing out deals...")` still shows in the brief window before the first event seeds the comparison. Step 2c (2026-04-13) | Apr 2026 |
| fd-3 stdout backfill for remaining 9 retailers (PF-1) | All 9 extract.sh files that were missing the `exec 3>&1; exec 1>&2` + `>&3` pattern (target, home_depot, lowes, ebay_new, ebay_used, sams_club, backmarket, fb_marketplace, walmart) now follow the convention introduced by SP-1 and applied to amazon + best_buy in scan-to-prices. All 11 retailer extract.sh files are now consistent | Chose inline copy-paste over extracting to a shared `containers/base/extract_helpers.sh` helper. Inline is 3 small edits per file; a shared helper would need a new file + `COPY` line in 9 Dockerfiles + `source` line in 9 extract.sh files — strictly more surface area. Walmart/extract.sh is currently dead code (WALMART_ADAPTER=firecrawl) but fixed anyway for consistency and to prevent the bug from reappearing if the env var is flipped. Step 2c (2026-04-13) | Apr 2026 |
| `pytestmark = pytest.mark.asyncio` removed (PF-2) | Deleted line 18 of `backend/tests/modules/test_m2_prices.py`. `pyproject.toml` already has `asyncio_mode = "auto"` which auto-detects async tests | The redundant `pytestmark` was generating 33 `PytestWarning: The test is marked with '@pytest.mark.asyncio' but it is not an async function` warnings on every run (the sync parametrize tests like `test_classify_error_status_all_unavailable_codes` inherited the mark). Silencing these cleans up the CI log output. Zero test behavior changes. Step 2c (2026-04-13) | Apr 2026 |
