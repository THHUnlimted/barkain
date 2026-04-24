import XCTest
@testable import Barkain

@MainActor
final class SearchViewModelTests: XCTestCase {

    // MARK: - Properties

    private var mockClient: MockAPIClient!
    private var mockAutocomplete: MockAutocompleteService!
    private var testDefaults: UserDefaults!
    private var recents: RecentSearches!
    private var viewModel: SearchViewModel!

    // MARK: - Setup

    override func setUp() {
        super.setUp()
        mockClient = MockAPIClient()
        mockAutocomplete = MockAutocompleteService()
        let suite = "test.search_vm.\(UUID().uuidString)"
        testDefaults = UserDefaults(suiteName: suite)!
        testDefaults.removePersistentDomain(forName: suite)
        recents = RecentSearches(defaults: testDefaults)
        let gate = FeatureGateService(proTierProvider: { false }, defaults: testDefaults, clock: Date.init)
        viewModel = SearchViewModel(
            apiClient: mockClient,
            featureGate: gate,
            autocompleteService: mockAutocomplete,
            recentSearches: recents
        )
    }

    override func tearDown() {
        viewModel = nil
        recents = nil
        mockAutocomplete = nil
        mockClient = nil
        testDefaults = nil
        super.tearDown()
    }

    // MARK: - Suggestions: empty + non-empty

    func test_onQueryChange_emptyQuery_setsSuggestionsToRecents() async {
        recents.add("iPhone 17 Pro")
        recents.add("AirPods Pro 2")
        // Re-init so the VM's mirror reflects the seeded recents.
        viewModel = SearchViewModel(
            apiClient: mockClient,
            autocompleteService: mockAutocomplete,
            recentSearches: recents
        )

        await viewModel.onQueryChange("")

        XCTAssertEqual(viewModel.suggestions, ["AirPods Pro 2", "iPhone 17 Pro"])
        XCTAssertEqual(mockAutocomplete.suggestionsCallCount, 0)
    }

    func test_onQueryChange_nonEmpty_callsAutocompleteWithLimit8() async {
        mockAutocomplete.suggestionsResult = ["iPhone 17 Pro Max", "iPhone 17 Pro"]
        await viewModel.onQueryChange("iph")
        XCTAssertEqual(mockAutocomplete.suggestionsCallCount, 1)
        XCTAssertEqual(mockAutocomplete.lastPrefix, "iph")
        XCTAssertEqual(mockAutocomplete.lastLimit, 8)
        XCTAssertEqual(viewModel.suggestions, ["iPhone 17 Pro Max", "iPhone 17 Pro"])
    }

    func test_onQueryChange_serviceUnavailable_returnsEmpty_noCrash() async {
        mockAutocomplete.suggestionsResult = []
        await viewModel.onQueryChange("zzz")
        XCTAssertTrue(viewModel.suggestions.isEmpty)
    }

    // MARK: - Suggestion taps + manual submits

    func test_onSuggestionTapped_setsQueryAndSearches_andRecordsRecent() async {
        let expected = [
            ProductSearchResult(
                deviceName: "iPhone 17 Pro Max",
                model: "iPhone 17 Pro Max",
                brand: "Apple",
                category: "phones",
                confidence: 0.95,
                primaryUpc: "1234567890123",
                source: .db,
                productId: UUID(),
                imageUrl: nil
            )
        ]
        mockClient.searchProductsResult = .success(
            ProductSearchResponse(
                query: "iPhone 17 Pro Max", results: expected, totalResults: 1, cached: false
            )
        )

        await viewModel.onSuggestionTapped("iPhone 17 Pro Max")

        XCTAssertEqual(viewModel.query, "iPhone 17 Pro Max")
        XCTAssertEqual(mockClient.searchProductsCallCount, 1)
        XCTAssertEqual(mockClient.searchProductsLastQuery, "iPhone 17 Pro Max")
        XCTAssertEqual(viewModel.recentSearches.first, "iPhone 17 Pro Max")
        XCTAssertEqual(recents.all().first, "iPhone 17 Pro Max")
    }

    func test_onSearchSubmitted_addsToRecents() async {
        mockClient.searchProductsResult = .success(
            ProductSearchResponse(query: "sony", results: [], totalResults: 0, cached: false)
        )
        await viewModel.onSearchSubmitted("sony wh-1000xm5")
        XCTAssertEqual(viewModel.recentSearches.first, "sony wh-1000xm5")
    }

    func test_onSearchSubmitted_under3Chars_noSearch_noRecent() async {
        await viewModel.onSearchSubmitted("ab")
        XCTAssertEqual(mockClient.searchProductsCallCount, 0)
        XCTAssertTrue(viewModel.recentSearches.isEmpty)
    }

    // MARK: - Direct API calls

    func test_performSearch_populatesResults_onSuccess() async {
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

        await viewModel.performSearch("sony")

        XCTAssertEqual(viewModel.results.count, 1)
        XCTAssertEqual(viewModel.results.first?.deviceName, "Sony WH-1000XM5")
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    func test_performSearch_setsError_onAPIFailure() async {
        mockClient.searchProductsResult = .failure(.network(URLError(.notConnectedToInternet)))

        await viewModel.performSearch("sony")

        XCTAssertTrue(viewModel.results.isEmpty)
        XCTAssertNotNil(viewModel.error)
        if case .network = viewModel.error! { /* ok */ }
        else { XCTFail("Expected .network, got \(String(describing: viewModel.error))") }
        XCTAssertFalse(viewModel.isLoading)
    }

    // MARK: - Deep search hint + force_gemini

    func test_showDeepSearchHint_alwaysTrueWhen3PlusChars() async {
        let result = ProductSearchResult(
            deviceName: "Sony WH-1000XM5", model: "WH-1000XM5", brand: "Sony",
            category: nil, confidence: 0.5, primaryUpc: nil, source: .gemini,
            productId: nil, imageUrl: nil
        )
        mockClient.searchProductsResult = .success(
            ProductSearchResponse(query: "sony", results: [result], totalResults: 1, cached: false)
        )
        await viewModel.onQueryChange("sony")
        await viewModel.performSearch("sony")
        XCTAssertTrue(viewModel.showDeepSearchHint)
    }

    func test_showDeepSearchHint_falseForEmptyOrShortQuery() async {
        XCTAssertFalse(viewModel.showDeepSearchHint)
        await viewModel.onQueryChange("ab")
        XCTAssertFalse(viewModel.showDeepSearchHint)
    }

    func test_deepSearch_callsAPIWithForceGemini() async {
        mockClient.searchProductsResult = .success(
            ProductSearchResponse(query: "obscure", results: [], totalResults: 0, cached: false)
        )
        await viewModel.onQueryChange("obscure thing")
        await viewModel.deepSearch()

        XCTAssertEqual(mockClient.searchProductsLastQuery, "obscure thing")
        XCTAssertEqual(mockClient.searchProductsLastForceGemini, true)
    }

    // MARK: - Recent searches persistence + cap

    func test_recentSearches_persistAndCapAt10() async {
        XCTAssertTrue(viewModel.recentSearches.isEmpty)
        for i in 0..<12 {
            await viewModel.onSearchSubmitted("query_\(i)")
        }
        XCTAssertEqual(viewModel.recentSearches.count, 10)
        XCTAssertEqual(viewModel.recentSearches.first, "query_11")
        XCTAssertFalse(viewModel.recentSearches.contains("query_0"))

        let freshRecents = RecentSearches(defaults: testDefaults)
        let fresh = SearchViewModel(
            apiClient: mockClient,
            autocompleteService: mockAutocomplete,
            recentSearches: freshRecents
        )
        XCTAssertEqual(fresh.recentSearches, viewModel.recentSearches)
    }

    // MARK: - Tap handling — DB source

    func test_handleResultTap_dbSource_navigatesImmediately() async {
        let productId = UUID()
        let result = ProductSearchResult(
            deviceName: "Sony WH-1000XM5", model: "WH-1000XM5", brand: "Sony",
            category: "headphones", confidence: 0.92, primaryUpc: "027242924864",
            source: .db, productId: productId, imageUrl: nil
        )

        await viewModel.handleResultTap(result)

        XCTAssertEqual(mockClient.resolveProductCallCount, 0)
        XCTAssertNotNil(viewModel.presentedProductViewModel)
        XCTAssertEqual(viewModel.presentedProductViewModel?.product?.id, productId)
        XCTAssertEqual(mockClient.getPricesCallCount, 1)
        XCTAssertEqual(mockClient.getEligibleDiscountsCallCount, 1)
        XCTAssertEqual(mockClient.getCardRecommendationsCallCount, 1)
        XCTAssertEqual(mockClient.getEligibleDiscountsLastProductId, productId)
    }

    // MARK: - Tap handling — Gemini source (with + without UPC)

    func test_handleResultTap_geminiSource_callsResolveWithUPC() async {
        let result = ProductSearchResult(
            deviceName: "Apple AirPods Pro 2", model: "AirPods Pro 2", brand: "Apple",
            category: "earbuds", confidence: 0.88, primaryUpc: "195949046674",
            source: .gemini, productId: nil, imageUrl: nil
        )

        await viewModel.handleResultTap(result)

        XCTAssertEqual(mockClient.resolveProductCallCount, 1)
        XCTAssertEqual(mockClient.resolveProductLastUPC, "195949046674")
        XCTAssertNotNil(viewModel.presentedProductViewModel)
    }

    func test_handleResultTap_geminiSource_noUPC_callsResolveFromSearch() async {
        let result = ProductSearchResult(
            deviceName: "Apple iPhone 8 (64GB)", model: "iPhone 8", brand: "Apple",
            category: "phones", confidence: 0.6, primaryUpc: nil,
            source: .gemini, productId: nil, imageUrl: nil
        )

        await viewModel.handleResultTap(result)

        XCTAssertEqual(mockClient.resolveFromSearchCallCount, 1)
        XCTAssertEqual(mockClient.resolveFromSearchLastDeviceName, "Apple iPhone 8 (64GB)")
        XCTAssertEqual(mockClient.resolveProductCallCount, 0)
        XCTAssertNil(viewModel.resolveFailureMessage)
    }

    func test_handleResultTap_geminiSource_noUPC_backend404_setsUnresolvedInline() async {
        // demo-prep-1 Item 2: 404 on resolve-from-search now routes to the
        // dedicated inline `UnresolvedProductView` via `unresolvedAfterTap`,
        // replacing the former alert-toast path (which dismissed back to
        // the same search-results state with no next step). The alert
        // branch remains for structural failures (e.g. DB row missing
        // productId) — only clean backend 404s land here.
        mockClient.resolveFromSearchResult = .failure(.notFound)
        let result = ProductSearchResult(
            deviceName: "Unknown Mystery Gadget", model: nil, brand: nil,
            category: nil, confidence: 0.3, primaryUpc: nil,
            source: .gemini, productId: nil, imageUrl: nil
        )

        await viewModel.handleResultTap(result)

        XCTAssertEqual(mockClient.resolveFromSearchCallCount, 1)
        XCTAssertTrue(viewModel.unresolvedAfterTap,
                      "404 on resolve-from-search must set unresolvedAfterTap so SearchView renders the inline UnresolvedProductView")
        XCTAssertNil(viewModel.resolveFailureMessage,
                     "legacy toast message must stay nil — that path is reserved for structural failures only")
        XCTAssertNil(viewModel.presentedProductViewModel)
    }

    func test_dismissUnresolvedAfterTap_clearsStateForRetry() async {
        // demo-prep-1 Item 2: the "Try a different search" CTA must clear
        // the unresolved state so the user can refine their query and
        // see search results again.
        mockClient.resolveFromSearchResult = .failure(.notFound)
        let result = ProductSearchResult(
            deviceName: "Unknown Mystery Gadget", model: nil, brand: nil,
            category: nil, confidence: 0.3, primaryUpc: nil,
            source: .gemini, productId: nil, imageUrl: nil
        )
        await viewModel.handleResultTap(result)
        XCTAssertTrue(viewModel.unresolvedAfterTap)

        viewModel.dismissUnresolvedAfterTap()

        XCTAssertFalse(viewModel.unresolvedAfterTap)
    }

    // MARK: - Clear

    func test_clearRecentSearches_emptiesMirrorAndStorage() async {
        await viewModel.onSearchSubmitted("iPhone 17 Pro")
        viewModel.clearRecentSearches()
        XCTAssertTrue(viewModel.recentSearches.isEmpty)
        XCTAssertTrue(recents.all().isEmpty)
    }
}
