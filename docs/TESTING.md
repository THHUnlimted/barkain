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
| Step 2a | 104 | 21 | 0 | 0 | 20 (ai_abstraction×4, health_monitor×5, watchdog×8, pre_fix_verifications×3) |
| Walmart adapter routing (post-2a) | 128 | 21 | 0 | 0 | 24 (walmart_http×15: proxy URL builder×4, happy path×2, challenge retry×2, http/parse/timeout/missing-creds errors×4, parser edge cases×3 + walmart_firecrawl×9: happy path×1, request shape×1, 6 error surfaces, + 2 existing fixture updates) |
| Scan-to-Prices Live Demo (2026-04-10) | 128 | 21 | 0 | 0 | **0 new** — live validation session, not a code-gen step. 7 live-run bugs fixed but no tests added; test gap documented below and deferred to Step 2b |
| Step 2b | 152 | 21 | 0 | 0 | 24 (cross_validation×6: gemini→upcitemdb second-opinion, confidence scoring, category mismatch detection, fallback trigger, cache invalidation on correction, wrong-product rejection + relevance_scoring×8: model_number_hard_gate×2, brand_match×2, token_overlap×2, threshold_filter×1, pick_best_with_scoring×1 + walmart_first_party×4: first_party_filter×2, sponsored_exclusion×1, seller_name_extraction×1) + 6 integration tests with skip guard |
| Step 2b-val Live Validation (2026-04-12) | 152 | 21 | 0 | 0 | **0 new** — live validation session, 3 extract.js + regex fixes landed without new tests. See `Barkain Prompts/Step_2b_val_Results.md`. Same gap as Scan-to-Prices Live Demo; real-API smoke tests deferred to a dedicated CI step |
| Post-2b-val Hardening (2026-04-12) | 152 | 21 | 0 | 0 | **0 new**, 1 existing test updated (`test_walmart_http_adapter::test_fetch_walmart_success_returns_listings` now asserts `Restored → refurbished` instead of `used`). Session added: per-retailer status system, sub-variant hard gate, Amazon refurb + installment fixes, supplier-code cleanup, accessory filter, manual UPC entry — all live-validated against real Amazon/Walmart/Best Buy but not unit-tested. Test-debt paid down in Step 2b-final. See CLAUDE.md § "Post-2b-val hardening COMPLETE" |
| Step 2b-final (2026-04-13) | 181 | 21 | 0 | 0 | 35 new: M1 model-field×2 (resolve_exposes_gemini_model + resolve_handles_null_gemini_model), M2 gemini_model relevance×5 (generation_marker×2, gpu_model×2, backward_compat×1), hardening×24 (clean_product_name×4, is_accessory×4, ident_to_regex×3, variant_equality×2, classify_error×2 + 8-code parametrize, retailer_results_e2e×1), carrier-listing×4. Paid down the "most load-bearing test-debt item" from post-2b-val. `_MODEL_PATTERNS[5]` + `_ORDINAL_TOKENS` added for GPU + generation-marker scoring. |
| **Total** | **181** | **21** | **0** | **0** | |

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

- **Every PR** touching `backend/**` or `containers/**` runs unit tests via `.github/workflows/backend-tests.yml` (added Step 2b-final). TimescaleDB + Redis service containers, fake API keys, `BARKAIN_DEMO_MODE=1`.
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
