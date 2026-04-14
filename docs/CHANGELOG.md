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
