import XCTest
@testable import Barkain

@MainActor
final class SearchViewModelTests: XCTestCase {

    // MARK: - Properties

    private var mockClient: MockAPIClient!
    private var testDefaults: UserDefaults!
    private var viewModel: SearchViewModel!

    // MARK: - Setup

    override func setUp() {
        super.setUp()
        mockClient = MockAPIClient()
        let suite = "test.search_vm.\(UUID().uuidString)"
        testDefaults = UserDefaults(suiteName: suite)!
        testDefaults.removePersistentDomain(forName: suite)
        let gate = FeatureGateService(proTierProvider: { false }, defaults: testDefaults, clock: Date.init)
        // 0-nanosecond debounce so tests don't wait the real 300ms.
        viewModel = SearchViewModel(
            apiClient: mockClient,
            featureGate: gate,
            userDefaults: testDefaults,
            debounceNanos: 0
        )
    }

    override func tearDown() {
        viewModel = nil
        mockClient = nil
        testDefaults = nil
        super.tearDown()
    }

    // MARK: - Debounce

    func test_search_debounces_rapid_input() async {
        // Given — a controllable clock lets us drive the debounce explicitly.
        let gate = FeatureGateService(proTierProvider: { false }, defaults: testDefaults, clock: Date.init)
        let releaseContinuation = AsyncStream<Void>.makeStream()
        let releaseIterator = SendableIterator(stream: releaseContinuation.stream)
        let clock: @Sendable () async throws -> Void = {
            try await releaseIterator.next()
        }
        let vm = SearchViewModel(
            apiClient: mockClient,
            featureGate: gate,
            userDefaults: testDefaults,
            debounceNanos: 1_000_000,
            clock: clock
        )

        // When — 5 rapid keystrokes. Each cancels the previous task before
        // the clock releases it, so only the final query fires.
        vm.queryChanged("s")
        vm.queryChanged("so")
        vm.queryChanged("son")
        vm.queryChanged("sony")
        vm.queryChanged("sony wh")

        // Release the debounce for any still-alive task.
        releaseContinuation.continuation.yield()
        releaseContinuation.continuation.yield()
        releaseContinuation.continuation.yield()
        releaseContinuation.continuation.yield()
        releaseContinuation.continuation.yield()
        releaseContinuation.continuation.finish()

        // Give the task scheduler a few ticks to settle.
        for _ in 0..<20 { await Task.yield() }

        // Then — only the FINAL query was actually searched.
        XCTAssertEqual(mockClient.searchProductsCallCount, 1)
        XCTAssertEqual(mockClient.searchProductsLastQuery, "sony wh")
    }

    // MARK: - Success path

    func test_search_populatesResults_onSuccess() async {
        // Given
        let expected = [
            ProductSearchResult(
                deviceName: "Sony WH-1000XM5",
                model: "WH-1000XM5",
                brand: "Sony",
                category: "headphones",
                confidence: 0.95,
                primaryUpc: "027242924864",
                source: .db,
                productId: UUID(),
                imageUrl: nil
            )
        ]
        mockClient.searchProductsResult = .success(
            ProductSearchResponse(query: "sony", results: expected, totalResults: 1, cached: false)
        )

        // When
        await viewModel.performSearch("sony")

        // Then
        XCTAssertEqual(viewModel.results.count, 1)
        XCTAssertEqual(viewModel.results.first?.deviceName, "Sony WH-1000XM5")
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    // MARK: - Error path

    func test_search_setsError_onAPIFailure() async {
        // Given
        mockClient.searchProductsResult = .failure(.network(URLError(.notConnectedToInternet)))

        // When
        await viewModel.performSearch("sony")

        // Then
        XCTAssertTrue(viewModel.results.isEmpty)
        XCTAssertNotNil(viewModel.error)
        if case .network = viewModel.error! {
            // correct case
        } else {
            XCTFail("Expected .network, got \(String(describing: viewModel.error))")
        }
        XCTAssertFalse(viewModel.isLoading)
    }

    // MARK: - Deep search hint + force_gemini

    private func makeResult(_ name: String, brand: String? = nil, model: String? = nil) -> ProductSearchResult {
        ProductSearchResult(
            deviceName: name,
            model: model,
            brand: brand,
            category: nil,
            confidence: 0.5,
            primaryUpc: nil,
            source: .gemini,
            productId: nil,
            imageUrl: nil
        )
    }

    func test_showDeepSearchHint_alwaysTrueWhen3PlusChars() async {
        // Hint is always available past the 3-char threshold — even when the
        // current results look right, a closer match might be one deep
        // search away.
        let result = makeResult("Sony WH-1000XM5", brand: "Sony", model: "WH-1000XM5")
        mockClient.searchProductsResult = .success(
            ProductSearchResponse(query: "sony", results: [result], totalResults: 1, cached: false)
        )
        viewModel.queryChanged("sony")
        await viewModel.performSearch("sony")
        XCTAssertTrue(viewModel.showDeepSearchHint)
    }

    func test_showDeepSearchHint_falseForEmptyOrShortQuery() async {
        XCTAssertFalse(viewModel.showDeepSearchHint)  // empty
        viewModel.queryChanged("ab")
        XCTAssertFalse(viewModel.showDeepSearchHint)  // <3 chars
    }

    func test_showDeepSearchHint_trueWhileTyping3PlusCharsBeforeResults() async {
        // No results yet, query >= 3 chars → hint shown so the "hit return"
        // affordance is visible from the moment the user has typed enough
        // for a search to fire.
        viewModel.queryChanged("widget")
        XCTAssertTrue(viewModel.showDeepSearchHint)
    }

    func test_deepSearch_callsAPIWithForceGemini() async {
        mockClient.searchProductsResult = .success(
            ProductSearchResponse(query: "obscure", results: [], totalResults: 0, cached: false)
        )
        viewModel.queryChanged("obscure thing")
        await viewModel.deepSearch()

        XCTAssertEqual(mockClient.searchProductsLastQuery, "obscure thing")
        XCTAssertEqual(mockClient.searchProductsLastForceGemini, true)
    }

    // MARK: - Recent searches persistence + cap

    func test_recentSearches_persistAndCapAt10() {
        // Given — start from zero
        XCTAssertTrue(viewModel.recentSearches.isEmpty)

        // When — 12 distinct queries are added
        for i in 0..<12 {
            viewModel.addToRecentSearches("query_\(i)")
        }

        // Then — only the 10 most recent are retained (newest first)
        XCTAssertEqual(viewModel.recentSearches.count, 10)
        XCTAssertEqual(viewModel.recentSearches.first, "query_11")
        XCTAssertFalse(viewModel.recentSearches.contains("query_0"))
        XCTAssertFalse(viewModel.recentSearches.contains("query_1"))

        // And — persisted across a fresh ViewModel instance backed by the same suite
        let gate = FeatureGateService(proTierProvider: { false }, defaults: testDefaults, clock: Date.init)
        let fresh = SearchViewModel(
            apiClient: mockClient,
            featureGate: gate,
            userDefaults: testDefaults,
            debounceNanos: 0
        )
        XCTAssertEqual(fresh.recentSearches, viewModel.recentSearches)
    }

    // MARK: - Tap handling — DB source

    func test_handleResultTap_dbSource_navigatesImmediately() async {
        // Given — a DB-sourced result tap should NOT call /products/resolve.
        let productId = UUID()
        let result = ProductSearchResult(
            deviceName: "Sony WH-1000XM5",
            model: "WH-1000XM5",
            brand: "Sony",
            category: "headphones",
            confidence: 0.92,
            primaryUpc: "027242924864",
            source: .db,
            productId: productId,
            imageUrl: nil
        )

        // When
        await viewModel.handleResultTap(result)

        // Then — NO resolveProduct call; price fetch did run on the presented VM.
        XCTAssertEqual(mockClient.resolveProductCallCount, 0)
        XCTAssertNotNil(viewModel.presentedProductViewModel)
        XCTAssertEqual(viewModel.presentedProductViewModel?.product?.id, productId)
        XCTAssertEqual(mockClient.getPricesCallCount, 1)
        // Identity + card chain fires after the price batch completes so the
        // Search flow renders the SAME ancillary data the Scanner flow does.
        XCTAssertEqual(mockClient.getEligibleDiscountsCallCount, 1)
        XCTAssertEqual(mockClient.getCardRecommendationsCallCount, 1)
        XCTAssertEqual(mockClient.getEligibleDiscountsLastProductId, productId)
    }

    // MARK: - Tap handling — Gemini source

    func test_handleResultTap_geminiSource_callsResolveWithUPC() async {
        // Given — a Gemini row with a UPC should route through /products/resolve.
        let result = ProductSearchResult(
            deviceName: "Apple AirPods Pro 2",
            model: "AirPods Pro 2",
            brand: "Apple",
            category: "earbuds",
            confidence: 0.88,
            primaryUpc: "195949046674",
            source: .gemini,
            productId: nil,
            imageUrl: nil
        )

        // When
        await viewModel.handleResultTap(result)

        // Then — resolveProduct was called with the UPC; price fetch followed.
        XCTAssertEqual(mockClient.resolveProductCallCount, 1)
        XCTAssertEqual(mockClient.resolveProductLastUPC, "195949046674")
        XCTAssertNotNil(viewModel.presentedProductViewModel)
        XCTAssertEqual(mockClient.getPricesCallCount, 1)
        XCTAssertEqual(mockClient.getEligibleDiscountsCallCount, 1)
        XCTAssertEqual(mockClient.getCardRecommendationsCallCount, 1)
    }

    func test_handleResultTap_geminiSource_noUPC_callsResolveFromSearch() async {
        // Given — a Gemini row WITHOUT a UPC (common for older / discontinued
        // SKUs like iPhone 8) should fall through to /products/resolve-from-search,
        // not surface a failure alert.
        let result = ProductSearchResult(
            deviceName: "Apple iPhone 8 (64GB)",
            model: "iPhone 8",
            brand: "Apple",
            category: "phones",
            confidence: 0.6,
            primaryUpc: nil,
            source: .gemini,
            productId: nil,
            imageUrl: nil
        )

        // When
        await viewModel.handleResultTap(result)

        // Then — the fallback endpoint fired and resolveProduct(upc:) did NOT.
        XCTAssertEqual(mockClient.resolveFromSearchCallCount, 1)
        XCTAssertEqual(mockClient.resolveFromSearchLastDeviceName, "Apple iPhone 8 (64GB)")
        XCTAssertEqual(mockClient.resolveFromSearchLastBrand, "Apple")
        XCTAssertEqual(mockClient.resolveFromSearchLastModel, "iPhone 8")
        XCTAssertEqual(mockClient.resolveProductCallCount, 0)
        XCTAssertNil(viewModel.resolveFailureMessage)
        XCTAssertNotNil(viewModel.presentedProductViewModel)
        XCTAssertEqual(mockClient.getPricesCallCount, 1)
        XCTAssertEqual(mockClient.getEligibleDiscountsCallCount, 1)
        XCTAssertEqual(mockClient.getCardRecommendationsCallCount, 1)
    }

    func test_handleResultTap_geminiSource_noUPC_backend404_showsToast() async {
        // Given — backend returns 404 (UPC_NOT_FOUND_FOR_PRODUCT) → toast.
        mockClient.resolveFromSearchResult = .failure(.notFound)
        let result = ProductSearchResult(
            deviceName: "Unknown Mystery Gadget",
            model: nil,
            brand: nil,
            category: nil,
            confidence: 0.3,
            primaryUpc: nil,
            source: .gemini,
            productId: nil,
            imageUrl: nil
        )

        // When
        await viewModel.handleResultTap(result)

        // Then — toast set; no product presented.
        XCTAssertEqual(mockClient.resolveFromSearchCallCount, 1)
        XCTAssertNotNil(viewModel.resolveFailureMessage)
        XCTAssertNil(viewModel.presentedProductViewModel)
    }
}

// MARK: - Helpers

/// Tiny helper that wraps an AsyncStream iterator in a Sendable box so a
/// `@Sendable` closure can call `.next()` from the main-actor context.
private actor SendableIterator {
    private var iterator: AsyncStream<Void>.Iterator
    init(stream: AsyncStream<Void>) { self.iterator = stream.makeAsyncIterator() }
    func next() async throws {
        var local = iterator
        _ = await local.next()
        iterator = local
    }
}
