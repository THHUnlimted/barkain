# Barkain — Testing Reference

> Source: Architecture sessions, March–April 2026
> Scope: Backend (pytest) + iOS (XCTest) test conventions, CI configuration, coverage targets
> Last updated: April 2026 (v2.2 — 302 backend / 66 iOS at end of Step 2i-b; +1 test for migration 0006 `chk_subscription_tier`)

---

## Test Strategy Overview

| Platform | Framework | DB | Key Patterns |
|----------|-----------|----|----|
| Backend (Python) | pytest + pytest-asyncio | Docker PostgreSQL+TimescaleDB (**NOT SQLite**) | Async tests, fakeredis, mocked API adapters, fixture files |
| iOS (Swift) | XCTest | In-memory (no persistence in Phase 1) | Protocol-based mocks, @MainActor test methods, Given/When/Then |

**Target:** Backend tests run in <30s. iOS tests in <60s. Full suite <5min. CI must pass before merge.

---

## Backend Testing

### File Organization

```
backend/tests/
├── conftest.py                    # Shared fixtures: test DB, auth bypass, fakeredis
├── test_health.py                 # Health endpoint
├── test_auth.py                   # Clerk JWT validation
├── test_rate_limit.py             # Rate limiting
├── test_migrations.py             # All tables created successfully
├── modules/
│   ├── test_m1_product.py         # Product resolution
│   ├── test_m2_prices.py          # Price aggregation
│   ├── test_m5_identity.py        # Identity profile + card matching
│   └── ...
└── fixtures/
    ├── bestbuy_response.json      # Canned Best Buy API response
    ├── ebay_response.json         # Canned eBay Browse API response
    ├── keepa_response.json        # Canned Keepa API response
    ├── gemini_upc_response.json       # Canned Gemini UPC lookup response
    ├── upcitemdb_response.json        # Canned UPCitemdb backup response
    ├── container_extract_response.json # Canned container extraction response
    ├── amazon_extract_response.json   # Canned Amazon container response
    ├── walmart_extract_response.json  # Canned Walmart container response
    ├── target_extract_response.json   # Canned Target container response
    ├── sams_club_extract_response.json    # Canned Sam's Club container response
    ├── fb_marketplace_extract_response.json # Canned Facebook Marketplace response
    ├── best_buy_extract_response.json     # Canned Best Buy container response
    ├── home_depot_extract_response.json   # Canned Home Depot container response
    ├── lowes_extract_response.json        # Canned Lowe's container response
    ├── ebay_new_extract_response.json     # Canned eBay (new) container response
    ├── ebay_used_extract_response.json    # Canned eBay (used/refurb) container response
    └── backmarket_extract_response.json   # Canned BackMarket container response
```

### conftest.py Pattern

```python
import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from fakeredis import aioredis as fakeredis

from app.main import app
from app.dependencies import get_db, get_redis, get_current_user

# ── Test Database (Docker PostgreSQL+TimescaleDB) ─────────────
TEST_DATABASE_URL = "postgresql+asyncpg://app:test@localhost:5433/barkain_test"

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL)
    # Create all tables (or run alembic migrations)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest.fixture
async def db_session(test_engine):
    async_session = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()  # Clean up after each test

# ── Fake Redis ────────────────────────────────────────────────
@pytest.fixture
async def fake_redis():
    redis = fakeredis.FakeRedis()
    yield redis
    await redis.flushall()

# ── Auth Bypass ───────────────────────────────────────────────
@pytest.fixture
def mock_user_id():
    return "user_test_123"

@pytest.fixture
async def client(db_session, fake_redis, mock_user_id):
    """Async test client with dependency overrides."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_redis] = lambda: fake_redis
    app.dependency_overrides[get_current_user] = lambda: {"user_id": mock_user_id}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()

# ── Auth-Required Client (no user override) ───────────────────
@pytest.fixture
async def unauthed_client(db_session, fake_redis):
    """Client without auth — for testing 401 responses."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_redis] = lambda: fake_redis
    # No get_current_user override — auth middleware will reject

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
```

### Backend Test Conventions

**Naming:** `test_[function]_[scenario]_[expected]`
```python
async def test_resolve_product_valid_upc_returns_product(client):
async def test_resolve_product_unknown_upc_returns_404(client):
async def test_get_prices_cached_skips_api_calls(client, fake_redis):
```

**Structure:** Given / When / Then (comments for clarity)
```python
async def test_get_prices_returns_all_retailers(client):
    # Given: a product exists in the DB
    product = await create_test_product(db_session)

    # When: prices are requested
    response = await client.get(f"/api/v1/prices/{product.id}")

    # Then: all retailers are returned, sorted by price
    assert response.status_code == 200
    data = response.json()
    assert len(data["prices"]) == 3
    prices = [p["price"] for p in data["prices"]]
    assert prices == sorted(prices)
```

**Mocking retailer APIs:** Use `pytest-httpx` or `respx` to mock HTTP calls. Canned responses in `tests/fixtures/`:
```python
@pytest.fixture
def mock_bestbuy_response():
    with open("tests/fixtures/bestbuy_response.json") as f:
        return json.load(f)

async def test_bestbuy_adapter_parses_response(mock_bestbuy_response, respx_mock):
    respx_mock.get("https://api.bestbuy.com/v1/products(upc=...)")
        .respond(json=mock_bestbuy_response)

    adapter = BestBuyAdapter(api_key="test")
    result = await adapter.get_price(upc="012345678901")

    assert result.price == 499.99
    assert result.retailer_id == "best_buy"
```

### Backend Test Requirements

- **Docker PostgreSQL+TimescaleDB required** — NEVER use SQLite (TimescaleDB features, generated columns, and array types require PostgreSQL)
- Every step includes tests — not a separate step
- All existing tests must pass after every step
- `ruff check` must pass (lint)
- Mock all external dependencies (retailer APIs, Clerk, etc.)
- One logical assertion per test (but multiple `assert` checking one outcome is fine)

---

## iOS Testing

### File Organization

```
BarkainTests/
├── Features/
│   ├── Scanner/
│   │   └── ScannerViewModelTests.swift
│   ├── Search/
│   │   └── SearchViewModelTests.swift
│   └── Recommendation/
│       └── RecommendationViewModelTests.swift
├── Services/
│   ├── APIClientTests.swift
│   └── AuthServiceTests.swift
├── Helpers/
│   ├── TestFixtures.swift         # Shared mock data
│   ├── MockAPIClient.swift        # Protocol-based mock
│   └── XCTestCase+Extensions.swift
└── Snapshots/                     # Phase 3+
    └── __Snapshots__/

BarkainUITests/
├── Screens/                       # Page object pattern
│   ├── ScannerScreen.swift
│   └── SearchScreen.swift
└── Flows/
    └── ScanFlowTests.swift
```

### ViewModel Test Pattern

```swift
final class ScannerViewModelTests: XCTestCase {
    var sut: ScannerViewModel!
    var mockAPIClient: MockAPIClient!

    @MainActor
    override func setUp() {
        mockAPIClient = MockAPIClient()
        sut = ScannerViewModel(apiClient: mockAPIClient)
    }

    override func tearDown() {
        sut = nil
        mockAPIClient = nil
    }

    @MainActor
    func test_onBarcodeScan_resolvesProduct() async {
        // Given
        mockAPIClient.resolveProductResult = .success(TestFixtures.sampleProduct)

        // When
        await sut.handleBarcodeScan(upc: "012345678901")

        // Then
        XCTAssertNotNil(sut.product)
        XCTAssertEqual(sut.product?.name, "Sony WH-1000XM5")
        XCTAssertFalse(sut.isLoading)
    }

    @MainActor
    func test_onBarcodeScan_networkError_showsError() async {
        // Given
        mockAPIClient.resolveProductResult = .failure(.network(.noConnection))

        // When
        await sut.handleBarcodeScan(upc: "012345678901")

        // Then
        XCTAssertNil(sut.product)
        XCTAssertNotNil(sut.error)
    }
}
```

### Mock Pattern

```swift
protocol APIClientProtocol {
    func resolveProduct(upc: String) async throws -> Product
    func getPrices(productId: UUID) async throws -> PriceComparison
}

final class MockAPIClient: APIClientProtocol {
    var resolveProductResult: Result<Product, AppError> = .success(TestFixtures.sampleProduct)
    var getPricesResult: Result<PriceComparison, AppError> = .success(TestFixtures.samplePrices)

    func resolveProduct(upc: String) async throws -> Product {
        try resolveProductResult.get()
    }

    func getPrices(productId: UUID) async throws -> PriceComparison {
        try getPricesResult.get()
    }
}
```

### iOS Test Conventions

- **Naming:** `test_[methodName]_[expectedBehavior]`
- **Structure:** Given / When / Then with comments
- **@MainActor** required on all ViewModel test methods
- **Protocol-first:** Every service has a protocol; mock via conformance
- **Accessibility identifiers:** `enum AccessibilityID { static let scanButton = "scan_button" }`
- **No force unwraps** except in test setup
- **Per-test UserDefaults isolation (Step 2f learning):** any test that touches a service persisting to `UserDefaults` (e.g. `FeatureGateService`'s daily scan counter) must inject a fresh `UserDefaults(suiteName:)` keyed by a UUID in `setUp`. Without isolation, tests share `UserDefaults.standard`, accumulate persisted state across the suite, and eventually trip gates that were never meant to fire in unrelated tests (the 2f tests break `test_reset_clearsPriceState` once cumulative scans hit the daily cap). The `makeDefaults()` helper in `FeatureGateServiceTests.swift` and `ScannerViewModelTests.swift` is the reference implementation.

---

## UI Tests (Phase 2+)

### Page Object Pattern

```swift
struct ScannerScreen {
    let app: XCUIApplication

    var scanButton: XCUIElement { app.buttons["scan_button"] }
    var resultLabel: XCUIElement { app.staticTexts["product_name"] }

    func tapScan() -> RecommendationScreen {
        scanButton.tap()
        return RecommendationScreen(app: app)
    }
}
```

---

## CI Test Configuration

### Backend (GitHub Actions)

```yaml
services:
  postgres:
    image: timescale/timescaledb:latest-pg16
    env:
      POSTGRES_DB: barkain_test
      POSTGRES_USER: app
      POSTGRES_PASSWORD: test
    ports:
      - 5432:5432
    options: >-
      --health-cmd "pg_isready -U app"
      --health-interval 5s
      --health-timeout 3s
      --health-retries 5
  redis:
    image: redis:7-alpine
    ports:
      - 6379:6379

steps:
  - uses: actions/setup-python@v5
    with: { python-version: "3.12" }
  - run: pip install -r requirements.txt -r requirements-test.txt
  - run: alembic upgrade head
    env:
      DATABASE_URL: postgresql+asyncpg://app:test@localhost:5432/barkain_test
  - run: pytest --tb=short -q --cov=app
  - run: ruff check .
```

### iOS (GitHub Actions)

```yaml
steps:
  - uses: actions/checkout@v4
  - run: sudo xcode-select -s /Applications/Xcode_16.app
  - run: |
      xcodebuild test \
        -scheme Barkain \
        -destination 'platform=iOS Simulator,name=iPhone 16,OS=18.0' \
        -resultBundlePath TestResults.xcresult \
        -enableCodeCoverage YES
  - run: swiftlint
```

---

## Test Inventory

Update this table after every step:

| Phase/Step | Backend | iOS Unit | iOS UI | Snapshot | New This Step |
|-----------|---------|----------|--------|----------|---------------|
| Step 1a | 14 | 0 | 0 | 0 | 14 (health×4, auth×3, rate_limit×3, migrations×2, seed×2) |
| Step 1b | 26 | 0 | 0 | 0 | 12 (validation×3, auth×1, redis_cache×1, postgres×1, gemini×1, upcitemdb×1, 404×1, response_shape×1, ean13×1, idempotency×1) |
| Step 1c | 40 | 0 | 0 | 0 | 14 (url_resolution×2, extract_success×1, extract_timeout×1, extract_conn_error×1, extract_http500×1, extract_retry×1, extract_all_succeed×1, extract_all_partial×1, extract_all_fail×1, extract_all_specific×1, health_healthy×1, health_timeout×1, response_normalization×1) |
| Step 1d | 50 | 0 | 0 | 0 | 10 (parse_amazon×1, parse_walmart×1, parse_target_sale×1, parse_sams_club×1, parse_fb_used×1, extract_all_5×1, mixed_success_failure×1, correct_retailer_ids×1, amazon_metadata×1, fb_sellers×1) |
| Step 1e | 59 | 0 | 0 | 0 | 9 (parse_best_buy×1, parse_home_depot×1, parse_lowes×1, parse_ebay_new_condition×1, parse_ebay_used_conditions×1, parse_backmarket_refurb×1, extract_all_6_batch2×1, batch2_partial_failure×1, ebay_new_sellers×1) |
| Step 1f | 72 | 0 | 0 | 0 | 13 (cache_miss×1, redis_hit×1, db_hit×1, force_refresh×1, sorted×1, partial_fail×1, all_fail×1, history×1, upsert×1, is_on_sale×1, 404×1, 422×1, auth×1) |
| Step 1g | 72 | 9 | 0 | 0 | 9 iOS (scan_resolve×1, scan_network_error×1, scan_loading×1, scan_clear_old×1, scan_reset×1, api_decode_product×1, api_404×1, api_decode_prices×1, placeholder×1) |
| Step 1h | 72 | 21 | 0 | 0 | 9 iOS (resolve_and_prices×1, loading_states×1, price_error×1, force_refresh×1, partial_results×1, savings_calc×1, best_price×1, reset_price_state×1, resolve_fail_skips_prices×1) + existing test updated |
| Step 1i | 84 | 21 | 0 | 0 | 12 backend integration (full_flow×7, error_format×5) |
| Step 2a | 104 | 21 | 0 | 0 | 20 (ai_abstraction×4, health_monitor×5, watchdog×8, pre_fix_verifications×3) |
| Walmart adapter routing (post-2a) | 128 | 21 | 0 | 0 | 24 (walmart_http×15: proxy URL builder×4, happy path×2, challenge retry×2, http/parse/timeout/missing-creds errors×4, parser edge cases×3 + walmart_firecrawl×9: happy path×1, request shape×1, 6 error surfaces, + 2 existing fixture updates) |
| Scan-to-Prices Live Demo (2026-04-10) | 128 | 21 | 0 | 0 | **0 new** — live validation session, not a code-gen step. 7 live-run bugs fixed but no tests added; test gap documented below and deferred to Step 2b |
| Step 2b | 152 | 21 | 0 | 0 | 24 (cross_validation×6: gemini→upcitemdb second-opinion, confidence scoring, category mismatch detection, fallback trigger, cache invalidation on correction, wrong-product rejection + relevance_scoring×8: model_number_hard_gate×2, brand_match×2, token_overlap×2, threshold_filter×1, pick_best_with_scoring×1 + walmart_first_party×4: first_party_filter×2, sponsored_exclusion×1, seller_name_extraction×1) + 6 integration tests with skip guard |
| Step 2b-val Live Validation (2026-04-12) | 152 | 21 | 0 | 0 | **0 new** — live validation session, 3 extract.js + regex fixes landed without new tests. See `Barkain Prompts/Step_2b_val_Results.md`. Same gap as Scan-to-Prices Live Demo; real-API smoke tests deferred to a dedicated CI step |
| Post-2b-val Hardening (2026-04-12) | 152 | 21 | 0 | 0 | **0 new**, 1 existing test updated (`test_walmart_http_adapter::test_fetch_walmart_success_returns_listings` now asserts `Restored → refurbished` instead of `used`). Session added: per-retailer status system, sub-variant hard gate, Amazon refurb + installment fixes, supplier-code cleanup, accessory filter, manual UPC entry — all live-validated against real Amazon/Walmart/Best Buy but not unit-tested. Test-debt paid down in Step 2b-final. See CLAUDE.md § "Post-2b-val hardening COMPLETE" |
| Step 2b-final (2026-04-13) | 181 | 21 | 0 | 0 | 35 new: M1 model-field×2 (resolve_exposes_gemini_model + resolve_handles_null_gemini_model), M2 gemini_model relevance×5 (generation_marker×2, gpu_model×2, backward_compat×1), hardening×24 (clean_product_name×4, is_accessory×4, ident_to_regex×3, variant_equality×2, classify_error×2 + 8-code parametrize, retailer_results_e2e×1), carrier-listing×4. Paid down the "most load-bearing test-debt item" from post-2b-val. `_MODEL_PATTERNS[5]` + `_ORDINAL_TOKENS` added for GPU + generation-marker scoring. |
| Step 2c (2026-04-13) | 192 | 32 | 0 | 0 | 22 new: backend stream×11 (`test_m2_prices_stream.py` — as_completed completion order, success/no_match/unavailable event payloads, Redis cache short-circuit, DB cache short-circuit, force_refresh bypass, SSE content-type, 404-before-stream-opens, end-to-end wire parsing, unknown product raises) + iOS SSE parser×5 (`SSEParserTests.swift` — single event, multiple events, multi-line data, trailing flush, comment/unknown lines ignored) + iOS scanner stream×6 (`ScannerViewModelTests.swift` — incremental retailerResults mutation, sortedPrices re-sorts as events arrive, `.error` event clears comparison, thrown-error falls back to batch, closed-without-done falls back, bestPrice tracks cheaper retailer). PF-2 eliminated 33 pytest warnings by removing redundant `pytestmark = pytest.mark.asyncio` (asyncio_mode=auto is set in pyproject.toml). Streaming tests drive the generator directly via an injected `_FakeContainerClient` for the service-level assertions, and use `httpx.AsyncClient.stream()` + an `_collect_sse()` line parser for the endpoint-level assertions. |
| Step 2c-fix (2026-04-13) | 192 | 36 | 0 | 0 | 4 new byte-level SSE parser tests (`SSEParserTests.swift` — `test_byte_level_splits_on_LF`, `test_byte_level_handles_CRLF_line_endings`, `test_byte_level_flushes_partial_trailing_event_without_final_blank_line`, `test_byte_level_no_spurious_events_from_partial_lines`). Driven through a new test-visible `SSEParser.parse(bytes:)` entry point that accepts any `AsyncSequence<UInt8>`, over a hand-rolled `ByteStream` fixture that yields bytes one at a time with `Task.yield()` between each — simulating wire-level delivery. **These tests would not have caught 2c-val-L6** (the root cause was `URLSession.AsyncBytes.lines` buffering, which is specific to the real URLSession pipeline and impossible to reproduce in a unit test without a real TCP connection). They guard against regressions in the manual byte splitter — the buffering bug itself is guarded by the os_log instrumentation which makes any future regression observable in a single sim run. Live-backend XCUITest deferred to Step 2g. |
| Step 2d (2026-04-14) | 222 | 43 | 0 | 0 | 37 new: **backend 30** — `test_m5_identity.py`×18 (profile CRUD×4: get-default-if-none, get-existing, create-via-post, update-full-replace; matching×5: no-flags-empty, military-union, multi-group union, Samsung-9-row dedup, inactive-excluded; savings math×5: percentage $1500×30%=$450, cap $10000×10% → $400, fixed_amount, no-product-id null, no-prices null; endpoints×3: /discounts empty-for-new-user, /discounts end-to-end-after-POST, /discounts/all excludes-inactive; performance×1: seed 66 programs, median of 5 runs < 150ms) + `test_discount_catalog_seed.py`×12 (pure-Python lint: unique ids, _direct suffix, count==8, known retailers, eligibility vocabulary matches `ELIGIBILITY_TYPES`, verification_method whitelist, discount_type whitelist, program_type whitelist, no duplicate tuples, percentage values in (0,100], non-negative max_value, military covers samsung/apple/hp regression guard). **iOS 7** — `IdentityOnboardingViewModelTests.swift`×4 (save_callsAPI_withCorrectFlags, skip_callsAPI_withAllFalse, saveFailure_setsError, editFlow_preservesInitialProfile) + `ScannerViewModelTests.swift`×3 (fetchIdentityDiscounts_firesAfterStreamDone, fetchIdentityDiscounts_emptyOnFailure_doesNotSetPriceError, fetchIdentityDiscounts_clearedOnNewScan). Both backend test files use helper functions `_seed_user/_seed_retailer/_seed_program/_seed_product_with_price` for consistency with `test_m2_prices.py` style. The performance gate runs 5 queries with `time.perf_counter()`, takes the median to smooth CI variance, and asserts < 150ms (50ms local-dev target; 150ms upper bound for GitHub Actions cold-Postgres). |
| Step 2e (2026-04-14) | 252 | 53 | 0 | 0 | 40 new: **backend 30** — `test_m5_cards.py`×22 (catalog×3: empty, active-only filter, 30-active; portfolio CRUD×6: add + list, add unknown → 404, re-activate soft-deleted, set preferred unsets others, user categories upsert, reject unknown user-picked category; matching×8: rotating 5x > CSP 1x at Amazon + dollar math, static bonus wins at online_shopping, user-selected Cash+ 5x at best_buy, no-cards → `user_has_cards: false`, expired rotating ignored, activation flag propagates, one-rec-per-retailer for 3-retailer product, ≤150ms perf gate with 5 cards; infra×2: users-row upsert on first add_card, `_quarter_to_dates` helper unit test; error surfaces×3: INVALID_CATEGORY_SELECTION 400, CARD_NOT_FOUND 404). `test_card_catalog_seed.py`×8 (pure-Python lint: card_count==30, issuers match vocab, currencies match vocab, no-duplicate-tuples, display names unique, category_bonuses shape + user_selected requires non-empty allowed, all 8 Tier 1 issuers represented, base rates positive, points cards carry conservative cpp, rotating references valid cards, rotating categories non-empty, Q2 2026 dates, Cash+/Customized Cash excluded from rotating). **iOS 10** — `CardSelectionViewModelTests.swift`×7 (load populates catalog + user cards, filteredGroups alphabetical with `US Bank` special-case, addCard calls API and updates portfolio, addCard user_selected card opens category sheet, removeCard soft-deletes locally, togglePreferred unsets others, setCategories calls API with quarter + clears pending sheet) + `ScannerViewModelTests.swift`×3 (fetchCardRecommendations_firesAfterIdentityDiscounts, emptyOnFailure_doesNotSetPriceError, clearedOnNewScan). TestFixtures + MockAPIClient extended with `sampleCardProgram`/`sampleUserCardSummary`/`sampleCardRecommendationsResponse` + 7 call-tracking properties. Removed `test_recommendations_lowest_price_per_retailer` — the composite UNIQUE constraint on `(product_id, retailer_id, condition)` prevents seeding multiple prices at the same retailer, making the dedup branch unreachable from tests. |
| Step 2f (2026-04-14) | 266 | 63 | 0 | 0 | 24 new: **backend 14** — `test_m11_billing.py`×14 (webhook×8: initial_purchase_sets_pro, renewal_sets_new_expiration with SET-not-delta assertion, non_renewing_lifetime → expires_at NULL, cancellation_keeps_pro_until_expiration, expiration_downgrades_to_free, invalid_auth_returns_401 with WEBHOOK_AUTH_FAILED code, unknown_event_acknowledged with no-DB-write assertion, idempotency_same_event_id → action=duplicate; status×3: free_user, pro_user_with_expiration, expired_pro_downgrades_in_response with DB-row-unchanged assertion; rate limiter×2: free_user_uses_base_limit (3/min cap → 4th 429), pro_user_doubled (6 succeed, 7th 429); migration×1: migration_0004_index_exists queries pg_indexes for indexdef containing UNIQUE/card_issuer/card_product). Helpers `_seed_user(...arbitrary fields)`, `_build_event`, `_webhook_headers(secret)`, `_future_ms/_past_ms` for expiration math. Webhook tests use `monkeypatch.setattr(settings, "REVENUECAT_WEBHOOK_SECRET", "test_secret")`. **iOS 10** — `FeatureGateServiceTests.swift`×8 (free_hits_limit_at_10, pro_unlimited, daily_rollover_with_mutable_clock_closure, canAccess_fullIdentityDiscounts_false_for_free, canAccess_cardRecommendations_false_for_free, canAccess_all_features_true_for_pro_iterates_ProFeature_allCases, remainingScans_nil_for_pro, hydrate_restores_persisted_count). Each test uses a fresh UUID-suffixed `UserDefaults(suiteName:)` via `makeDefaults()` helper to prevent quota leakage. `ScannerViewModelTests.swift`×2 (scanLimit_triggersPaywall_blocksFetchPrices: gate pre-loaded to limit, scan resolves product but skips prices, showPaywall flipped, getPricesCallCount stays 0; scanQuota_consumedOnlyOnSuccessfulResolve: failing resolve does NOT increment dailyScanCount, subsequent successful resolve does). `setUp` updated to inject a per-test UUID-suffixed UserDefaults suite + FeatureGateService — without this, all ScannerViewModelTests share UserDefaults.standard and accumulate scans, causing `test_reset_clearsPriceState` to silently break mid-suite once cumulative scans hit the 10/day cap. |
| Step 2h (2026-04-14) | 301 | 66 | 0 | 0 | 21 new backend — **`backend/tests/workers/`** new package. `test_queue_client.py`×4 (send_message_round_trip, receive_empty_queue, delete_message_removes, get_queue_url_caches) — all wrapped in `with mock_aws():` from `moto[sqs]` 5.x so the tests run hermetic with no LocalStack container. `test_price_ingestion.py`×4 (enqueue_stale_products_sends_one_per_stale_product: seeds 3 products with stale/fresh `last_checked`, asserts SQS receives exactly the 2 stale IDs; enqueue_skips_products_without_prices: 0-price product → 0 messages; process_queue_calls_price_service_with_force_refresh: monkeypatches `PriceAggregationService.get_prices` to count `force_refresh=True` calls, confirms message is ack+deleted after success; process_queue_skips_unknown_product: random UUID in body → ack+delete without calling the service). `test_portal_rates.py`×6 (parse_rakuten_extracts_phase1_retailers + parse_topcashback_... + parse_befrugal_at_least_two: load `backend/tests/fixtures/portal_rates/{rakuten,topcashback,befrugal}.html` captured from live probes on 2026-04-14, parser returns `PortalRate` list, assert ≥3/≥3/≥2 Phase-1 retailers + Decimal rates; normalize_retailer_aliases: `"Best Buy"`/`"Lowe's"`/curly `U+2019` apostrophe/`"The Home Depot"` all resolve, `"Unknown Store"`→None; upsert_portal_bonus_seeds_baseline_on_first_write: normal_value == bonus_value on first observation, `is_elevated` reads back False; upsert_portal_bonus_detects_spike_via_generated_column: second scrape at 10 with preserved baseline 5 → `bonus_value=10`, `normal_value=5` preserved, `is_elevated=True` from the Postgres GENERATED column). `test_discount_verification.py`×7 (verify_active_program_updates_last_verified: 200 + program name in body → `consecutive_failures=0`, `last_verified` set; flagged_missing_mention_does_not_increment: 200 but body missing name → `flagged` counter +1, `consecutive_failures` stays 0, `is_active=True`; 404_increments_failure_counter; network_error_increments_failure_counter (respx `side_effect=httpx.ConnectError`); three_consecutive_failures_deactivates: seed `consecutive_failures=2`, 500 response → 3, `is_active=False`; successful_verification_resets_failure_counter: seed 2 → 200+mention → 0; skips_programs_without_verification_url). All discount verification tests use `respx.mock` to intercept `httpx.AsyncClient.get`. **Test isolation bug fix:** initially used `await db_session.refresh(program)` after the worker mutated in-memory state — `refresh()` does not autoflush, so it re-read the stale pre-mutation row and caused 6 false failures. Removed all `refresh()` calls; the in-memory instance is mutated in place so direct attribute inspection works. Documented in 2h learnings. **SQSClient endpoint sentinel fix:** initial constructor `endpoint_url or settings.SQS_ENDPOINT_URL or None` couldn't distinguish "explicit None override" from "use settings fallback" — `None or "http://localhost:4566" or None` → `"http://localhost:4566"`. Replaced with a `_UNSET = object()` sentinel so tests can pass `endpoint_url=None` to force default boto3 resolution (compatible with `moto.mock_aws`). iOS untouched — 0 new iOS tests. |
| Step 2i-b (2026-04-15) | 302 | 66 | 0 | 0 | **+1 backend** — `test_m11_billing.py::test_migration_0006_subscription_tier_constraint` verifies `chk_subscription_tier` exists in `pg_constraint` and rejects a subscription_tier outside `{'free','pro'}`. The bad-value UPDATE is wrapped in `db_session.begin_nested()` (a SAVEPOINT) so the IntegrityError rolls back only the savepoint and leaves the outer fixture transaction intact for teardown — this fixed a `SAWarning: transaction already deassociated from connection` that the first cut produced when it called `db_session.rollback()` directly. iOS untouched. **Refactor coverage:** `_classify_retailer_result` extraction in `m2_prices/service.py` is exercised end-to-end by the existing 11 stream tests + 12 batch tests + 12 integration tests, all unchanged. |
| Step 2g (2026-04-14) | 280 | 66 | 0 | 0 | 20 new: **backend 14** — `test_m12_affiliate.py`×14 (pure URL construction×9: amazon_tag_appended_no_existing_params (asserts `?tag=barkain-20` suffix), amazon_tag_appended_with_existing_params (asserts `&tag=` branch + `?psc=1` preserved + single `?`), amazon_untagged_when_env_empty (passthrough with `is_affiliated=false`, `network=None`), ebay_new_rover_redirect_encodes_url (asserts rover skeleton + `campid=5339148665` + `toolid=10001` + percent-encoded `mpre=https%3A%2F%2Fwww.ebay.com%2Fitm%2F12345%3Fvar%3D99`), ebay_used_uses_same_network (same rover shape via `EBAY_RETAILERS` frozenset), walmart_tagged_when_env_set (monkeypatches `WALMART_AFFILIATE_ID=test-wmt-id`, asserts `goto.walmart.com/c/test-wmt-id/1/4/mp?u=<encoded>`), walmart_passthrough_when_env_empty, best_buy_passthrough (denied network), home_depot_passthrough (unaffiliated); click endpoint×3: click_endpoint_logs_row_and_returns_tagged_url (asserts `SELECT affiliate_network, click_url FROM affiliate_clicks WHERE user_id=...` returns `amazon_associates` + `tag=barkain-20`), click_endpoint_passthrough_logs_sentinel (asserts `affiliate_network='passthrough'` NOT NULL sentinel for Best Buy), stats_endpoint_groups_by_retailer (logs 2 amazon + 1 best_buy, asserts `{clicks_by_retailer: {amazon: 2, best_buy: 1}, total_clicks: 3}`); conversion webhook×2: conversion_webhook_permissive_without_secret (empty env → 200 no-auth), conversion_webhook_bearer_required_when_secret_set (401 for missing + wrong bearer, 200 for correct)). New `_seed_retailer(db_session, retailer_id)` helper inserts a minimal retailers row (only NOT NULL columns) so `affiliate_clicks.retailer_id` FK lands. 9 of 14 are pure-function tests — no DB fixture required — using `monkeypatch.setattr(settings, "AMAZON_ASSOCIATE_TAG", "barkain-20")` against the `@staticmethod AffiliateService.build_affiliate_url`. **iOS 6** — `ScannerViewModelTests.swift`×3 (`test_resolveAffiliateURL_returnsTaggedURLOnSuccess`: stubs `MockAPIClient.getAffiliateURLResult` with Amazon-tagged URL, calls helper after `handleBarcodeScan`, asserts tagged URL + call count; `test_resolveAffiliateURL_fallsBackOnAPIError`: stubs `.failure(.network(URLError(.notConnectedToInternet)))`, asserts original `retailerPrice.url` comes back wrapped in a URL, NOT nil, and that the helper tried the API before falling back; `test_resolveAffiliateURL_passesCorrectArguments`: validates `getAffiliateURLLastRetailerId == "best_buy"`, `...LastProductURL == "https://bestbuy.com/site/123"`, `...LastProductId == samplePriceComparison.productId`). `IdentityDiscountCardTests.swift`×3 (`test_resolvedURL_prefersVerificationURL` when both fields set, `test_resolvedURL_fallsBackToURLWhenVerificationMissing` when only `url` set, `test_resolvedURL_returnsNilWhenBothMissing`). `IdentityDiscountCard.resolvedURL` is exposed as a new testable computed property (prefers `verificationUrl`, falls back to `url`, nil when both missing). `makeDiscount(verificationUrl:url:)` factory avoids boilerplate per test. |
| **Total** | **302** | **66** | **0** | **0** | |

---

## Integration Tests (Step 2b+)

### Pattern: `@pytest.mark.integration` with skip guard

Integration tests live in `backend/tests/integration/test_real_api_contracts.py` and hit real external APIs (Firecrawl, Decodo, Gemini, UPCitemdb, retailer containers). They are **not** run on every push — they require explicit opt-in via environment variable:

```bash
# Run integration tests manually
BARKAIN_RUN_INTEGRATION_TESTS=1 pytest -m integration --tb=short -q

# Run only unit tests (default CI behavior)
pytest --tb=short -q
```

Every integration test is decorated with:
```python
@pytest.mark.integration
```

The marker is registered in `backend/pyproject.toml` via `[tool.pytest.ini_options]` → `markers`. The individual skip guard lives on `test_real_api_contracts.py` itself as a module-level `pytestmark` check for `BARKAIN_RUN_INTEGRATION_TESTS`.

`backend/tests/integration/conftest.py` (added in Step 2b-final) auto-loads `.env` into `os.environ` when `BARKAIN_RUN_INTEGRATION_TESTS=1`, so developers no longer need `set -a && source ../.env && set +a` before every run:

```python
def pytest_configure(config):
    if os.environ.get("BARKAIN_RUN_INTEGRATION_TESTS") != "1":
        return
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
```

### Why separate from unit tests

- **Cost:** Each integration test makes real API calls (Firecrawl credits, proxy bandwidth, Gemini tokens).
- **Rate limits:** Vendors throttle aggressive testing.
- **Flakiness:** Real endpoints have transient failures that would break CI if run on every push.
- **Speed:** Integration tests take 10-60s each vs <100ms for mocked unit tests.

Integration tests complement the respx-mocked unit tests by catching the schema drift and environmental regressions that mocks cannot see (see "Real-API smoke tests" section below for the full rationale from the 2026-04-10 live run).

---

## Testing Principles

1. **Every step includes tests** — tests are part of the step, not a separate step
2. **Test behavior, not implementation** — assert outcomes, not internal calls
3. **Fast tests** — mock all external dependencies (APIs, auth, Redis)
4. **Deterministic** — no flaky tests, no time-dependent assertions without control
5. **Docker PostgreSQL for backend** — never SQLite. TimescaleDB features require real PostgreSQL
6. **Preview providers count as tests** — if it compiles in Preview, the view renders
7. **Fixture files for canned API responses** — `tests/fixtures/*.json`, not inline strings
8. **Mocks are not contracts** — respx + MockAPIClient catch logic bugs but do not validate vendor API schema drift or real subprocess boundaries. Every vendor adapter and every scraper container must ALSO have a real-API smoke test (see next principle).

---

## Real-API smoke tests (added 2026-04-10 after first live run exposed the gap)

> The first-ever live 3-retailer run on 2026-04-10 surfaced 7 bugs that all 128 respx-mocked backend tests and 21 MockAPIClient-backed iOS tests were blind to. The root cause is the same in every case: the unit tests mock the boundary between our code and the outside world, so schema drift / subprocess / stdout / Chromium issues are invisible until something real runs through. Full postmortem: `Barkain Prompts/Error_Report_Scan_to_Prices_Deployment.md` (SP-1 through SP-9).

### Required coverage (Step 2b pre-fix block)

Every adapter and every retailer container must have a companion real-API smoke test:

| Component | Current test coverage | Real-API smoke test required |
|-----------|----------------------|------------------------------|
| `walmart_firecrawl.py` adapter | 7 respx-mocked tests (schema drift invisible) | Nightly GET against real Firecrawl v2 `/scrape` endpoint with a known Walmart URL; assert non-zero listings with non-zero prices |
| `walmart_http.py` (Decodo) adapter | 15 respx-mocked tests | Nightly GET against Walmart via real Decodo proxy; assert non-zero listings |
| `containers/{amazon,best_buy,…}/extract.sh` | 10-14 respx-mocked tests per retailer | Nightly real `POST /extract` against each retailer container; assert `success=true`, `listings|length > 0`, first listing `price > 0`. Reuses `scripts/ec2_test_extractions.sh` as the reference implementation |
| Future Keepa adapter | n/a | Nightly GET against real Keepa API |
| Future UPCitemdb fallback | n/a | Nightly GET against real UPCitemdb API |

**Step 2b-final partial paydown (2026-04-13):** `_clean_product_name`, `_is_accessory_listing`, `_ident_to_regex`, `_classify_error_status`, `retailer_results` construction, `_is_carrier_listing`, and the new `gemini_model` relevance path all now have dedicated unit coverage in `test_m2_prices.py` and `test_walmart_firecrawl_adapter.py`. The real-API smoke tests in `test_real_api_contracts.py` remain the definitive check against schema drift and real subprocess boundaries.

### Cadence and enforcement

- **Every PR** touching `backend/**` or `containers/**` runs unit tests via `.github/workflows/backend-tests.yml` (added Step 2b-final). TimescaleDB + Redis service containers, fake API keys. Note: `DEMO_MODE` is intentionally **not** set in CI — the test client overrides `get_current_user` directly. (Renamed from `BARKAIN_DEMO_MODE` in 2i-b.)
- **Nightly** in CI against the real endpoints, not every push (cost + rate limits). Still to wire up.
- Alert on failure via Slack / email / PagerDuty.
- A smoke test failure is **not a build break** but creates a P1 issue for the next morning.
- These tests do **not** replace the respx unit tests — unit tests stay fast and run on every push. Smoke tests catch schema drift and environmental regressions the unit tests can't see.

### Counter-examples: bugs that respx + MockAPIClient missed on 2026-04-10

- **SP-1** — `agent-browser` writes progress lines to stdout, polluting `json.loads`. Invisible because the container client tests (`test_container_client.py`) mock HTTP responses and never invoke the real subprocess.
- **SP-4** — Firecrawl v2 renamed `country` → `location.country`. Invisible because `test_walmart_firecrawl_adapter.py` uses respx and doesn't validate request body shape.
- **SP-2, SP-3** — `EXTRACT_TIMEOUT=60s` too short and `/tmp/.X99-lock` blocks Xvfb on restart. Invisible because tests never actually run Chromium.
- **SP-5, SP-6** — `.env` overrides for `CONTAINER_URL_PATTERN` and `CONTAINER_TIMEOUT_SECONDS` silently rotted. Invisible because tests don't read `.env`.
- **SP-7** — Zero-price listings dominated `_pick_best_listing`. Invisible because respx fixtures don't mirror real-world extract.js parse failures.
- **SP-8** — iOS URLSession 60 s default timed out before 90 s backend round trip. Invisible because `MockAPIClient` returns synchronously.

All seven of these were one-line or small fixes once discovered. The lesson isn't "write more unit tests" — it's "the mocking boundary is a blind spot, and the blind spot must have its own test discipline."

**Step 2c-val added one more to this list:**

- **2c-val-L6** — `URLSession.AsyncBytes.lines` buffers aggressively for small SSE payloads. The iOS SSE parser's 5 unit tests + ScannerViewModel's 6 stream tests all passed because they inject an `AsyncThrowingStream<RetailerStreamEvent, Error>` above the `URLSession.bytes(for:)` layer, never exercising the real `AsyncBytes.lines` iterator. The bug only surfaced when a real TCP connection delivered events seconds apart — at which point `lines` held them back until stream close, `sawDone` never flipped, and `fallbackToBatch()` fired on every call. Fix: replace `bytes.lines` with a manual byte-level splitter (Step 2c-fix). Same lesson: the mocking boundary was above the actual buffering layer. See also the SSE debugging section below.

---

## SSE debugging (Step 2c-fix)

The iOS SSE consumer emits structured os_log events on the `com.barkain.app` subsystem, category `SSE`. These cover the full pipeline: stream connection opened / HTTP status, each raw line received from the byte splitter, each parsed `SSEEvent`, each decoded `RetailerStreamEvent`, `sawDone` transitions, fallback triggers, stream end / error. os_log is lazy-evaluated and costs nothing in Release builds.

**Watch a live session from the host:**

```bash
xcrun simctl spawn booted log stream \
  --level debug \
  --predicate 'subsystem == "com.barkain.app" AND category == "SSE"' \
  --style compact
```

**Expected happy-path signature:**

```
SSE stream opening for product <uuid> forceRefresh=false
SSE stream opened HTTP 200
SSE raw line: event: retailer_result
SSE raw line: data: {"retailer_id": "amazon", ...}
SSE raw line:
SSE parsed event: retailer_result dataLen=882
SSE decoded: retailerResult(...)
fetchPrices: received event retailerResult(...)
… (repeat for each retailer)
SSE parsed event: done dataLen=292
fetchPrices: sawDone=true succeeded=N failed=M cached=X
SSE stream ended normally
fetchPrices: stream completed successfully
```

**Failure-mode fingerprinting matrix** — read the log, not the stack trace:

| Observation | Root cause |
|---|---|
| `raw line` entries arrive all at once at stream close | Byte splitter regression (buffering returned) |
| `raw line` arrives incrementally but no `parsed event` | Parser state-machine regression |
| `parsed event` fires but no `decoded` | Swift JSON decode mismatch — check the error log line for the field name, inspect the `payload=...` attachment |
| `decoded` fires but no `received event` in ScannerViewModel | VM-level routing regression |
| `sawDone=true` never logs even though `done` arrives | `apply(_:for:)` or `sawDone` state-machine bug |
| `falling back to batch` fires on a healthy backend | Upstream error in one of the above; read the `warning` log line for `sawDone=...` state |

**Live-backend XCUITest:** deferred to Step 2g. The repo has zero UI tests today, and standing up a BarkainUITests target + uvicorn lifecycle + launch-argument plumbing exceeded the Step 2c-fix time budget. The os_log category above is the interim substitute — any regression is observable in one session by running the predicate above during a manual scan flow. When Step 2g adds the UITest, it should:

1. Launch the app with a `BARKAIN_E2E_BASE_URL=http://127.0.0.1:8000` launch argument that overrides `AppConfig.apiBaseURL`.
2. Require `DEMO_MODE=1 uvicorn app.main:app` to be running on `127.0.0.1:8000` (document as a pre-test precondition; fail fast if `/api/v1/health` isn't reachable).
3. Drive the manual UPC entry sheet → type `027242923232` → tap Resolve.
4. Assert within 30s that ≥1 `PriceRow` is visible (proves the stream rendered something before batch would have returned).
5. Assert that NO `XCUIElement` matching "Sniffing out deals..." is visible while prices are rendering (proves stream-driven transition, not batch-driven).
6. Wait for final state, assert ≥1 retailer with a non-nil price when `cached=true`.
