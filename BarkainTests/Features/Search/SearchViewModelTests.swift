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
