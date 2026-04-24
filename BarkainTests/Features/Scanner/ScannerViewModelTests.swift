import XCTest
@testable import Barkain

@MainActor
final class ScannerViewModelTests: XCTestCase {

    // MARK: - Properties

    private var mockClient: MockAPIClient!
    private var viewModel: ScannerViewModel!
    private var testDefaults: UserDefaults!

    // MARK: - Setup

    override func setUp() {
        super.setUp()
        mockClient = MockAPIClient()
        // Step 2f: each test gets a private UserDefaults suite for the
        // feature gate so daily scan counts don't leak across tests.
        // Without this, tests run sequentially and accumulate scans on
        // `UserDefaults.standard`, eventually hitting the 10/day cap
        // mid-suite and silently breaking unrelated tests.
        let suite = "test.scanner_vm.\(UUID().uuidString)"
        testDefaults = UserDefaults(suiteName: suite)!
        testDefaults.removePersistentDomain(forName: suite)
        let gate = FeatureGateService(
            proTierProvider: { false },
            defaults: testDefaults,
            clock: Date.init
        )
        viewModel = ScannerViewModel(apiClient: mockClient, featureGate: gate)
    }

    override func tearDown() {
        viewModel = nil
        mockClient = nil
        testDefaults = nil
        super.tearDown()
    }

    // MARK: - Tests

    func test_handleBarcodeScan_validUPC_resolvesProduct() async {
        // Given
        let expectedProduct = TestFixtures.sampleProduct

        // When
        await viewModel.handleBarcodeScan(upc: "012345678901")

        // Then
        XCTAssertEqual(viewModel.product, expectedProduct)
        XCTAssertEqual(viewModel.scannedUPC, "012345678901")
        XCTAssertNil(viewModel.error)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertEqual(mockClient.resolveProductCallCount, 1)
        XCTAssertEqual(mockClient.resolveProductLastUPC, "012345678901")
        XCTAssertNotNil(viewModel.priceComparison)
        XCTAssertEqual(mockClient.getPricesCallCount, 1)
    }

    func test_handleBarcodeScan_networkError_setsError() async {
        // Given
        mockClient.resolveProductResult = .failure(.network(URLError(.notConnectedToInternet)))

        // When
        await viewModel.handleBarcodeScan(upc: "012345678901")

        // Then
        XCTAssertNil(viewModel.product)
        XCTAssertNotNil(viewModel.error)
        XCTAssertEqual(viewModel.error, .network(URLError(.notConnectedToInternet)))
        XCTAssertFalse(viewModel.isLoading)
    }

    func test_handleBarcodeScan_setsLoadingState() async {
        // Given
        mockClient.resolveProductDelay = 0.1

        // When — start the scan
        let task = Task {
            await viewModel.handleBarcodeScan(upc: "012345678901")
        }

        // Then — after completion, loading is false
        await task.value
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNotNil(viewModel.product)
    }

    func test_handleBarcodeScan_clearsOldProduct() async {
        // Given — first scan succeeds
        await viewModel.handleBarcodeScan(upc: "012345678901")
        XCTAssertNotNil(viewModel.product)

        // When — second scan with different UPC (fails)
        mockClient.resolveProductResult = .failure(.notFound)
        await viewModel.handleBarcodeScan(upc: "999999999999")

        // Then — old product is cleared
        XCTAssertNil(viewModel.product)
        XCTAssertEqual(viewModel.scannedUPC, "999999999999")
        XCTAssertNotNil(viewModel.error)
    }

    func test_reset_clearsAllState() async {
        // Given — scan has completed
        await viewModel.handleBarcodeScan(upc: "012345678901")
        XCTAssertNotNil(viewModel.product)

        // When
        viewModel.reset()

        // Then
        XCTAssertNil(viewModel.scannedUPC)
        XCTAssertNil(viewModel.product)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    // MARK: - Price Comparison Tests

    func test_handleBarcodeScan_success_triggersResolveAndPrices() async {
        // When
        await viewModel.handleBarcodeScan(upc: "012345678901")

        // Then — both calls made in sequence
        XCTAssertEqual(mockClient.resolveProductCallCount, 1)
        XCTAssertEqual(mockClient.getPricesCallCount, 1)
        XCTAssertEqual(mockClient.getPricesLastProductId, TestFixtures.sampleProductId)
        XCTAssertNotNil(viewModel.priceComparison)
        XCTAssertFalse(viewModel.isPriceLoading)
    }

    func test_handleBarcodeScan_setsLoadingStatesThenPriceLoading() async {
        // Given
        mockClient.resolveProductDelay = 0.05

        // When
        await viewModel.handleBarcodeScan(upc: "012345678901")

        // Then — after completion both phases are done
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertFalse(viewModel.isPriceLoading)
        XCTAssertNotNil(viewModel.product)
        XCTAssertNotNil(viewModel.priceComparison)
    }

    func test_handleBarcodeScan_priceError_keepsProductAndSetsError() async {
        // Given
        mockClient.getPricesResult = .failure(.server("container timeout"))

        // When
        await viewModel.handleBarcodeScan(upc: "012345678901")

        // Then — product is kept, price error is set
        XCTAssertNotNil(viewModel.product)
        XCTAssertNil(viewModel.priceComparison)
        XCTAssertEqual(viewModel.priceError, .server("container timeout"))
        XCTAssertFalse(viewModel.isPriceLoading)
    }

    func test_fetchPrices_forceRefresh_passesFlag() async {
        // Given — first scan to establish product
        await viewModel.handleBarcodeScan(upc: "012345678901")
        let initialCount = mockClient.getPricesCallCount

        // When
        await viewModel.fetchPrices(forceRefresh: true)

        // Then
        XCTAssertEqual(mockClient.getPricesCallCount, initialCount + 1)
        XCTAssertEqual(mockClient.getPricesLastForceRefresh, true)
    }

    func test_handleBarcodeScan_partialResults_showsAvailablePrices() async {
        // Given
        mockClient.getPricesResult = .success(TestFixtures.partialPriceComparison)

        // When
        await viewModel.handleBarcodeScan(upc: "012345678901")

        // Then
        XCTAssertEqual(viewModel.sortedPrices.count, 1)
        XCTAssertEqual(viewModel.priceComparison?.retailersFailed, 5)
    }

    func test_maxSavings_calculatesSpreadBetweenHighestAndLowest() async {
        // When — sample has Amazon $298, Walmart $299.99, BestBuy $329.99
        await viewModel.handleBarcodeScan(upc: "012345678901")

        // Then
        XCTAssertNotNil(viewModel.maxSavings)
        XCTAssertEqual(viewModel.maxSavings!, 31.99, accuracy: 0.01)
    }

    func test_bestPrice_returnsLowestAvailablePrice() async {
        // When
        await viewModel.handleBarcodeScan(upc: "012345678901")

        // Then
        XCTAssertEqual(viewModel.bestPrice?.retailerId, "amazon")
        XCTAssertEqual(viewModel.bestPrice?.price, 298.00)
    }

    func test_reset_clearsPriceState() async {
        // Given
        await viewModel.handleBarcodeScan(upc: "012345678901")
        XCTAssertNotNil(viewModel.priceComparison)

        // When
        viewModel.reset()

        // Then
        XCTAssertNil(viewModel.priceComparison)
        XCTAssertFalse(viewModel.isPriceLoading)
        XCTAssertNil(viewModel.priceError)
    }

    func test_handleBarcodeScan_resolveFailure_doesNotFetchPrices() async {
        // Given
        mockClient.resolveProductResult = .failure(.notFound)

        // When
        await viewModel.handleBarcodeScan(upc: "000000000000")

        // Then
        XCTAssertEqual(mockClient.getPricesCallCount, 0)
        XCTAssertNil(viewModel.priceComparison)
    }

    func test_handleBarcodeScan_notFound_setsNotFoundErrorForUnresolvedView() async {
        // demo-prep-1 Item 2: ScannerView branches on `error == .notFound`
        // to render `UnresolvedProductView` instead of the generic error
        // card. Verify the VM actually preserves the `.notFound` variant
        // (previous silent-handback bug was generic .validation("...")
        // wrapping lossy envelope decoding, so this is the load-bearing
        // precondition for the graceful 404 UX).
        mockClient.resolveProductResult = .failure(.notFound)

        await viewModel.handleBarcodeScan(upc: "000000000000")

        XCTAssertEqual(viewModel.error, .notFound,
                       "error must be exactly .notFound so ScannerView renders UnresolvedProductView")
        XCTAssertNil(viewModel.product,
                     "no product should be set when resolve fails")
        XCTAssertFalse(viewModel.isLoading,
                       "loading must settle so the VM transitions into the error branch")
    }

    // MARK: - Streaming Tests (Step 2c)

    private func makePriceUpdate(
        retailerId: String,
        retailerName: String,
        price: Double,
        status: RetailerResult.Status = .success
    ) -> RetailerStreamEvent {
        let priceObj: RetailerPrice? = status == .success
            ? RetailerPrice(
                retailerId: retailerId,
                retailerName: retailerName,
                price: price,
                originalPrice: nil,
                currency: "USD",
                url: "https://\(retailerId).com/p",
                condition: "new",
                isAvailable: true,
                isOnSale: false,
                lastChecked: Date()
            )
            : nil
        return .retailerResult(RetailerResultUpdate(
            retailerId: retailerId,
            retailerName: retailerName,
            status: status,
            price: priceObj
        ))
    }

    private func makeDoneSummary(
        total: Int = 3,
        succeeded: Int = 3,
        failed: Int = 0,
        cached: Bool = false
    ) -> RetailerStreamEvent {
        .done(StreamSummary(
            productId: TestFixtures.sampleProductId,
            productName: "Sony WH-1000XM5",
            totalRetailers: total,
            retailersSucceeded: succeeded,
            retailersFailed: failed,
            cached: cached,
            fetchedAt: Date()
        ))
    }

    func test_fetchPrices_streams_results_incrementally() async {
        // Given — prefetch product and configure stream events
        await viewModel.handleBarcodeScan(upc: "012345678901")
        mockClient.streamPricesEvents = [
            makePriceUpdate(retailerId: "walmart", retailerName: "Walmart", price: 289.99),
            makePriceUpdate(retailerId: "amazon", retailerName: "Amazon", price: 298.00),
            makePriceUpdate(retailerId: "best_buy", retailerName: "Best Buy", price: 329.99),
            makeDoneSummary(total: 3, succeeded: 3, failed: 0),
        ]

        // When
        await viewModel.fetchPrices()

        // Then — all three retailers landed + done applied
        XCTAssertEqual(viewModel.priceComparison?.retailerResults.count, 3)
        XCTAssertEqual(viewModel.priceComparison?.prices.count, 3)
        XCTAssertEqual(viewModel.priceComparison?.retailersSucceeded, 3)
        XCTAssertEqual(viewModel.priceComparison?.cached, false)
        XCTAssertFalse(viewModel.isPriceLoading)
        // Stream was consumed (in addition to the original handleBarcodeScan fetch)
        XCTAssertGreaterThanOrEqual(mockClient.streamPricesCallCount, 1)
    }

    func test_fetchPrices_stream_updates_sortedPrices_live() async {
        // Given
        await viewModel.handleBarcodeScan(upc: "012345678901")
        mockClient.streamPricesEvents = [
            makePriceUpdate(retailerId: "amazon", retailerName: "Amazon", price: 350.00),
            makePriceUpdate(retailerId: "walmart", retailerName: "Walmart", price: 289.99),
            makeDoneSummary(total: 2, succeeded: 2),
        ]

        // When
        await viewModel.fetchPrices()

        // Then — cheapest (walmart) is first
        XCTAssertEqual(viewModel.sortedPrices.first?.retailerId, "walmart")
        XCTAssertEqual(viewModel.bestPrice?.retailerId, "walmart")
        XCTAssertEqual(viewModel.bestPrice?.price, 289.99)
    }

    func test_fetchPrices_error_event_sets_priceError_and_clears_comparison() async {
        // Given
        await viewModel.handleBarcodeScan(upc: "012345678901")
        mockClient.streamPricesEvents = [
            makePriceUpdate(retailerId: "amazon", retailerName: "Amazon", price: 298.00),
            .error(StreamError(code: "STREAM_ERROR", message: "pipeline failed")),
        ]

        // When
        await viewModel.fetchPrices()

        // Then
        XCTAssertNil(viewModel.priceComparison)
        XCTAssertEqual(viewModel.priceError, .server("pipeline failed"))
        XCTAssertFalse(viewModel.isPriceLoading)
    }

    func test_fetchPrices_stream_thrown_error_falls_back_to_batch() async {
        // Given — stream finishes with a network error, batch endpoint returns success
        await viewModel.handleBarcodeScan(upc: "012345678901")
        let getPricesCountBefore = mockClient.getPricesCallCount
        mockClient.streamPricesEvents = []
        mockClient.streamPricesError = .network(URLError(.timedOut))
        mockClient.getPricesResult = .success(TestFixtures.samplePriceComparison)

        // When
        await viewModel.fetchPrices()

        // Then — fallback hit the batch endpoint and result replaced any stream state
        XCTAssertEqual(mockClient.getPricesCallCount, getPricesCountBefore + 1)
        XCTAssertNotNil(viewModel.priceComparison)
        XCTAssertEqual(viewModel.priceComparison?.prices.count, 3)
        XCTAssertNil(viewModel.priceError)
        XCTAssertFalse(viewModel.isPriceLoading)
    }

    func test_fetchPrices_stream_closes_without_done_falls_back() async {
        // Given — stream yields no events and closes cleanly (no done event)
        await viewModel.handleBarcodeScan(upc: "012345678901")
        let getPricesCountBefore = mockClient.getPricesCallCount
        mockClient.streamPricesEvents = []
        mockClient.streamPricesError = nil
        mockClient.getPricesResult = .success(TestFixtures.samplePriceComparison)

        // When
        await viewModel.fetchPrices()

        // Then — fallback was triggered because no done event arrived
        XCTAssertEqual(mockClient.getPricesCallCount, getPricesCountBefore + 1)
        XCTAssertNotNil(viewModel.priceComparison)
    }

    func test_fetchPrices_bestPrice_updates_when_cheaper_retailer_arrives() async {
        // Given
        await viewModel.handleBarcodeScan(upc: "012345678901")
        mockClient.streamPricesEvents = [
            makePriceUpdate(retailerId: "amazon", retailerName: "Amazon", price: 399.00),
            makePriceUpdate(retailerId: "best_buy", retailerName: "Best Buy", price: 349.99),
            makePriceUpdate(retailerId: "walmart", retailerName: "Walmart", price: 289.99),
            makeDoneSummary(total: 3, succeeded: 3),
        ]

        // When
        await viewModel.fetchPrices()

        // Then — the final best_price is the cheapest one
        XCTAssertEqual(viewModel.bestPrice?.retailerId, "walmart")
        XCTAssertEqual(viewModel.bestPrice?.price, 289.99)
        XCTAssertNotNil(viewModel.maxSavings)
        // maxSavings == highest - lowest == 399 - 289.99
        XCTAssertEqual(viewModel.maxSavings!, 109.01, accuracy: 0.01)
    }

    // MARK: - Step 2d: Identity Discounts

    func test_fetchIdentityDiscounts_firesAfterStreamDone() async {
        // Given — price stream succeeds end-to-end with a done event
        mockClient.streamPricesEvents = [
            makePriceUpdate(retailerId: "walmart", retailerName: "Walmart", price: 289.99),
            makeDoneSummary(total: 1, succeeded: 1),
        ]
        mockClient.getEligibleDiscountsResult = .success(TestFixtures.sampleIdentityDiscountsResponse)

        // When — full scan triggers both resolveProduct and fetchPrices
        await viewModel.handleBarcodeScan(upc: "012345678901")

        // Then — identity discounts landed
        XCTAssertEqual(viewModel.identityDiscounts.count, 2)
        XCTAssertEqual(viewModel.identityDiscounts.first?.retailerId, "samsung_direct")
        XCTAssertEqual(mockClient.getEligibleDiscountsCallCount, 1)
        // Product id must be forwarded so estimated_savings can be computed
        XCTAssertEqual(mockClient.getEligibleDiscountsLastProductId, TestFixtures.sampleProductId)
        // Price list still rendered correctly — identity discounts didn't disrupt it
        XCTAssertEqual(viewModel.priceComparison?.prices.count, 1)
        XCTAssertNil(viewModel.priceError)
    }

    func test_fetchIdentityDiscounts_emptyOnFailure_doesNotSetPriceError() async {
        // Given — stream succeeds but identity endpoint fails
        mockClient.streamPricesEvents = [
            makePriceUpdate(retailerId: "walmart", retailerName: "Walmart", price: 289.99),
            makeDoneSummary(total: 1, succeeded: 1),
        ]
        mockClient.getEligibleDiscountsResult = .failure(.server("identity unavailable"))

        // When
        await viewModel.handleBarcodeScan(upc: "012345678901")

        // Then — discounts empty but priceError still nil (non-fatal)
        XCTAssertTrue(viewModel.identityDiscounts.isEmpty)
        XCTAssertNil(viewModel.priceError)
        XCTAssertEqual(viewModel.priceComparison?.prices.count, 1)
        XCTAssertEqual(mockClient.getEligibleDiscountsCallCount, 1)
    }

    func test_fetchIdentityDiscounts_clearedOnNewScan() async {
        // Given — first scan loads discounts
        mockClient.streamPricesEvents = [
            makePriceUpdate(retailerId: "walmart", retailerName: "Walmart", price: 289.99),
            makeDoneSummary(total: 1, succeeded: 1),
        ]
        mockClient.getEligibleDiscountsResult = .success(TestFixtures.sampleIdentityDiscountsResponse)
        await viewModel.handleBarcodeScan(upc: "012345678901")
        XCTAssertEqual(viewModel.identityDiscounts.count, 2)

        // When — second scan starts with a new resolveProduct failure path
        mockClient.resolveProductResult = .failure(.notFound)
        await viewModel.handleBarcodeScan(upc: "999999999999")

        // Then — discounts cleared at the start of the second scan
        XCTAssertTrue(viewModel.identityDiscounts.isEmpty)
    }

    // MARK: - Step 2e: Card Recommendations

    func test_fetchCardRecommendations_firesAfterIdentityDiscounts() async {
        mockClient.streamPricesEvents = [
            makePriceUpdate(retailerId: "walmart", retailerName: "Walmart", price: 289.99),
            makeDoneSummary(total: 1, succeeded: 1),
        ]
        mockClient.getEligibleDiscountsResult = .success(TestFixtures.emptyIdentityDiscounts)
        mockClient.getCardRecommendationsResult = .success(TestFixtures.sampleCardRecommendationsResponse)

        await viewModel.handleBarcodeScan(upc: "012345678901")

        XCTAssertEqual(viewModel.cardRecommendations.count, 1)
        XCTAssertEqual(viewModel.cardRecommendations.first?.cardDisplayName, "Chase Freedom Flex")
        XCTAssertTrue(viewModel.userHasCards)
        XCTAssertEqual(mockClient.getCardRecommendationsCallCount, 1)
        XCTAssertEqual(mockClient.getCardRecommendationsLastProductId, TestFixtures.sampleProductId)
        XCTAssertEqual(mockClient.getEligibleDiscountsCallCount, 1, "identity fires before cards")
        XCTAssertNil(viewModel.priceError)
    }

    func test_fetchCardRecommendations_emptyOnFailure_doesNotSetPriceError() async {
        mockClient.streamPricesEvents = [
            makePriceUpdate(retailerId: "walmart", retailerName: "Walmart", price: 289.99),
            makeDoneSummary(total: 1, succeeded: 1),
        ]
        mockClient.getEligibleDiscountsResult = .success(TestFixtures.emptyIdentityDiscounts)
        mockClient.getCardRecommendationsResult = .failure(.server("cards unavailable"))

        await viewModel.handleBarcodeScan(upc: "012345678901")

        XCTAssertTrue(viewModel.cardRecommendations.isEmpty)
        XCTAssertNil(viewModel.priceError)
        XCTAssertEqual(viewModel.priceComparison?.prices.count, 1)
        XCTAssertEqual(mockClient.getCardRecommendationsCallCount, 1)
    }

    func test_cardRecommendations_clearedOnNewScan() async {
        mockClient.streamPricesEvents = [
            makePriceUpdate(retailerId: "walmart", retailerName: "Walmart", price: 289.99),
            makeDoneSummary(total: 1, succeeded: 1),
        ]
        mockClient.getCardRecommendationsResult = .success(TestFixtures.sampleCardRecommendationsResponse)
        await viewModel.handleBarcodeScan(upc: "012345678901")
        XCTAssertEqual(viewModel.cardRecommendations.count, 1)
        XCTAssertTrue(viewModel.userHasCards)

        mockClient.resolveProductResult = .failure(.notFound)
        await viewModel.handleBarcodeScan(upc: "999999999999")

        XCTAssertTrue(viewModel.cardRecommendations.isEmpty)
    }

    // MARK: - Step 2f: Paywall gate tests

    func test_scanLimit_triggersPaywall_blocksFetchPrices() async {
        // Given a free gate already at the daily limit.
        let defaults = UserDefaults(suiteName: "test.gate.\(UUID().uuidString)")!
        defaults.removePersistentDomain(forName: "test.gate.\(UUID().uuidString)")
        let gate = FeatureGateService(
            proTierProvider: { false },
            defaults: defaults,
            clock: Date.init
        )
        for _ in 0..<FeatureGateService.freeDailyScanLimit {
            gate.recordScan()
        }
        XCTAssertTrue(gate.scanLimitReached)

        let limitedViewModel = ScannerViewModel(apiClient: mockClient, featureGate: gate)

        // When the user attempts another scan.
        await limitedViewModel.handleBarcodeScan(upc: "012345678901")

        // Then the product resolved BUT prices were not fetched and the
        // paywall flag is set so the view can present.
        XCTAssertNotNil(limitedViewModel.product)
        XCTAssertTrue(limitedViewModel.showPaywall)
        XCTAssertNil(limitedViewModel.priceComparison)
        XCTAssertEqual(mockClient.getPricesCallCount, 0)
        XCTAssertEqual(mockClient.streamPricesCallCount, 0)
    }

    func test_scanQuota_consumedOnlyOnSuccessfulResolve() async {
        // Given a free gate at zero quota.
        let defaults = UserDefaults(suiteName: "test.gate.\(UUID().uuidString)")!
        defaults.removePersistentDomain(forName: "test.gate.\(UUID().uuidString)")
        let gate = FeatureGateService(
            proTierProvider: { false },
            defaults: defaults,
            clock: Date.init
        )
        XCTAssertEqual(gate.dailyScanCount, 0)

        let testViewModel = ScannerViewModel(apiClient: mockClient, featureGate: gate)

        // When resolveProduct fails (e.g. Gemini timeout, unknown UPC).
        mockClient.resolveProductResult = .failure(.notFound)
        await testViewModel.handleBarcodeScan(upc: "999999999999")

        // Then no quota was burned — the user can retry without losing a scan.
        XCTAssertEqual(gate.dailyScanCount, 0)
        XCTAssertFalse(testViewModel.showPaywall)

        // And on a successful resolve, the quota IS consumed.
        mockClient.resolveProductResult = .success(TestFixtures.sampleProduct)
        await testViewModel.handleBarcodeScan(upc: "012345678901")
        XCTAssertEqual(gate.dailyScanCount, 1)
    }

    // MARK: - fb-marketplace-location

    func test_fetchPrices_noStoredLocation_passesNilSlugAndRadius() async {
        // Given a scan with no saved LocationPreferences.
        let defaults = makeIsolatedDefaults()
        let locationPrefs = LocationPreferences(defaults: defaults)
        let vm = ScannerViewModel(
            apiClient: mockClient,
            featureGate: FeatureGateService(
                proTierProvider: { false },
                defaults: defaults,
                clock: Date.init
            ),
            locationPreferences: locationPrefs
        )

        // When the price stream fires.
        await vm.handleBarcodeScan(upc: "012345678901")

        // Then APIClient saw nil id / nil radius — backend falls back
        // to the container's env-default sanfrancisco bucket.
        XCTAssertGreaterThanOrEqual(mockClient.streamPricesCallCount, 1)
        XCTAssertNil(mockClient.streamPricesLastFbLocationId)
        XCTAssertNil(mockClient.streamPricesLastFbRadiusMiles)
    }

    func test_fetchPrices_withStoredLocation_forwardsIdAndRadius() async {
        // Given a saved location with an FB numeric Marketplace Page ID.
        let defaults = makeIsolatedDefaults()
        let locationPrefs = LocationPreferences(defaults: defaults)
        locationPrefs.save(
            LocationPreferences.Stored(
                latitude: 40.6782,
                longitude: -73.9442,
                displayLabel: "Brooklyn, NY",
                fbLocationId: "112111905481230",
                radiusMiles: 25
            )
        )
        let vm = ScannerViewModel(
            apiClient: mockClient,
            featureGate: FeatureGateService(
                proTierProvider: { false },
                defaults: defaults,
                clock: Date.init
            ),
            locationPreferences: locationPrefs
        )

        // When the stream fires.
        await vm.handleBarcodeScan(upc: "012345678901")

        // Then id + radius reach the APIClient.
        XCTAssertEqual(mockClient.streamPricesLastFbLocationId, "112111905481230")
        XCTAssertEqual(mockClient.streamPricesLastFbRadiusMiles, 25)
    }

    // MARK: - Helpers

    private func makeIsolatedDefaults() -> UserDefaults {
        let suite = "test.scanner_vm_loc.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defaults.removePersistentDomain(forName: suite)
        return defaults
    }

    // MARK: - Step 2g: resolveAffiliateURL

    func test_resolveAffiliateURL_returnsTaggedURLOnSuccess() async {
        // Given — scan a product so priceComparison is populated with a productId.
        await viewModel.handleBarcodeScan(upc: "012345678901")
        let retailerPrice = TestFixtures.samplePriceComparison.prices[0] // Amazon

        // Backend returns a tagged URL.
        let tagged = "https://amazon.com/dp/B0BSHF7WHN?tag=barkain-20"
        mockClient.getAffiliateURLResult = .success(
            AffiliateURLResponse(
                affiliateUrl: tagged,
                isAffiliated: true,
                network: "amazon_associates",
                retailerId: "amazon"
            )
        )

        // When
        let resolved = await viewModel.resolveAffiliateURL(for: retailerPrice)

        // Then — tagged URL is surfaced.
        XCTAssertNotNil(resolved)
        XCTAssertEqual(resolved?.absoluteString, tagged)
        XCTAssertEqual(mockClient.getAffiliateURLCallCount, 1)
    }

    func test_resolveAffiliateURL_fallsBackOnAPIError() async {
        // Given — scan a product so priceComparison is populated.
        await viewModel.handleBarcodeScan(upc: "012345678901")
        let retailerPrice = TestFixtures.samplePriceComparison.prices[0] // Amazon

        // Backend throws.
        mockClient.getAffiliateURLResult = .failure(
            .network(URLError(.notConnectedToInternet))
        )

        // When
        let resolved = await viewModel.resolveAffiliateURL(for: retailerPrice)

        // Then — fallback URL is the original product URL, not nil.
        XCTAssertNotNil(resolved)
        XCTAssertEqual(
            resolved?.absoluteString,
            "https://amazon.com/dp/B0BSHF7WHN"
        )
        // The helper was called before the throw — verify wire-up.
        XCTAssertEqual(mockClient.getAffiliateURLCallCount, 1)
    }

    func test_resolveAffiliateURL_passesCorrectArguments() async {
        // Given — scan a product so priceComparison is populated.
        await viewModel.handleBarcodeScan(upc: "012345678901")
        let retailerPrice = TestFixtures.samplePriceComparison.prices[1] // Best Buy

        // When
        _ = await viewModel.resolveAffiliateURL(for: retailerPrice)

        // Then — the helper forwarded the retailer, URL, and product id
        // from the current comparison to the API.
        XCTAssertEqual(mockClient.getAffiliateURLCallCount, 1)
        XCTAssertEqual(mockClient.getAffiliateURLLastRetailerId, "best_buy")
        XCTAssertEqual(
            mockClient.getAffiliateURLLastProductURL,
            "https://bestbuy.com/site/123"
        )
        XCTAssertEqual(
            mockClient.getAffiliateURLLastProductId,
            TestFixtures.samplePriceComparison.productId
        )
    }
}
