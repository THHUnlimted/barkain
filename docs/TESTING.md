# Barkain — Testing Reference

> Source: Architecture sessions, March–April 2026
> Scope: Backend (pytest) + iOS (XCTest) test conventions, CI configuration, coverage targets
> Last updated: April 2026 (v2 — complete rewrite: dual backend + iOS strategy, Docker test DB, mock patterns)

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
| **Total** | **84** | **21** | **0** | **0** | |

---

## Testing Principles

1. **Every step includes tests** — tests are part of the step, not a separate step
2. **Test behavior, not implementation** — assert outcomes, not internal calls
3. **Fast tests** — mock all external dependencies (APIs, auth, Redis)
4. **Deterministic** — no flaky tests, no time-dependent assertions without control
5. **Docker PostgreSQL for backend** — never SQLite. TimescaleDB features require real PostgreSQL
6. **Preview providers count as tests** — if it compiles in Preview, the view renders
7. **Fixture files for canned API responses** — `tests/fixtures/*.json`, not inline strings
