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
        IdentityCache.shared.invalidateAll()
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

    /// 3o-C-rustoleum-ux-L1 regression: a fresh `performSearch` submit
    /// must dismiss any prior `presentedProductViewModel`. Without this,
    /// a user who navigates to product X (via a recent-search resolve)
    /// and then searches for unrelated query Y sees Y's results layered
    /// behind X's still-presented PriceComparisonView, creating "I
    /// searched X but got Y" misattribution.
    func test_performSearch_dismissesStalePresentedProductViewModel() async {
        // Step 1: navigate to a product so `presentedProductViewModel`
        // is non-nil — mirrors the user tapping a DB-source recent.
        let firstProductId = UUID()
        let firstResult = ProductSearchResult(
            deviceName: "L'Oreal Paris Excellence Creme",
            model: nil, brand: "L'Oreal", category: "beauty",
            confidence: 0.92, primaryUpc: "071249305423",
            source: .db, productId: firstProductId, imageUrl: nil
        )
        await viewModel.handleResultTap(firstResult)
        XCTAssertNotNil(viewModel.presentedProductViewModel,
                        "precondition: tap must navigate so we have a stale view to dismiss")

        // Step 2: submit a fresh search for an unrelated query.
        let freshResults = [
            ProductSearchResult(
                deviceName: "Rust-Oleum Stops Rust Spray Paint",
                model: nil, brand: "Rust-Oleum", category: "home",
                confidence: 0.85, primaryUpc: nil,
                source: .gemini, productId: nil, imageUrl: nil
            )
        ]
        mockClient.searchProductsResult = .success(
            ProductSearchResponse(query: "rustoleum paint",
                                  results: freshResults,
                                  totalResults: 1, cached: false)
        )

        await viewModel.performSearch("rustoleum paint")

        // Step 3: stale L'Oreal view must be gone, fresh results populated.
        XCTAssertNil(viewModel.presentedProductViewModel,
                     "fresh performSearch must dismiss the prior product page")
        XCTAssertEqual(viewModel.results.count, 1)
        XCTAssertEqual(viewModel.results.first?.deviceName,
                       "Rust-Oleum Stops Rust Spray Paint")
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
        mockClient.resolveFromSearchResult = .failure(.notFound())
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
        mockClient.resolveFromSearchResult = .failure(.notFound())
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

    // MARK: - demo-prep-1 Item 3: Low-confidence confirmation

    func test_handleResultTap_low_confidence_setsPendingConfirmation() async {
        // Backend returns 409 RESOLUTION_NEEDS_CONFIRMATION → VM sets
        // pendingConfirmation with primary + up to 2 alternatives from the
        // in-memory results list, and does NOT present a product.
        let primary = ProductSearchResult(
            deviceName: "Mystery Gadget Pro", model: nil, brand: "Mystery",
            category: nil, confidence: 0.42, primaryUpc: nil,
            source: .gemini, productId: nil, imageUrl: nil
        )
        let alt1 = ProductSearchResult(
            deviceName: "Mystery Gadget Plus", model: nil, brand: "Mystery",
            category: nil, confidence: 0.35, primaryUpc: nil,
            source: .gemini, productId: nil, imageUrl: nil
        )
        let alt2 = ProductSearchResult(
            deviceName: "Mystery Gadget", model: nil, brand: "Mystery",
            category: nil, confidence: 0.30, primaryUpc: nil,
            source: .gemini, productId: nil, imageUrl: nil
        )
        viewModel.results = [primary, alt1, alt2]
        mockClient.resolveFromSearchResult = .success(
            .needsConfirmation(
                candidate: LowConfidenceCandidate(
                    deviceName: primary.deviceName,
                    brand: primary.brand,
                    model: primary.model,
                    confidence: 0.42,
                    threshold: 0.70
                )
            )
        )

        await viewModel.handleResultTap(primary)

        XCTAssertNotNil(viewModel.pendingConfirmation,
                        "low-confidence tap must set pendingConfirmation so SearchView presents the sheet")
        XCTAssertEqual(viewModel.pendingConfirmation?.primary.deviceName, "Mystery Gadget Pro")
        XCTAssertEqual(viewModel.pendingConfirmation?.alternatives.count, 2,
                       "alternatives are pulled from the VM's current results list")
        XCTAssertEqual(viewModel.pendingConfirmation?.threshold, 0.70)
        XCTAssertNil(viewModel.presentedProductViewModel,
                     "no product should be presented before the user confirms")
        // Confidence must be forwarded to the backend so the gate can fire.
        XCTAssertEqual(mockClient.resolveFromSearchLastConfidence, 0.42)
    }

    func test_confirmResolution_callsConfirmEndpoint_andPresentsProduct() async {
        // After the user taps "Yes, that's it" the VM must call the /confirm
        // endpoint with user_confirmed=true and present the returned product.
        let pick = ProductSearchResult(
            deviceName: "Mystery Gadget Pro", model: nil, brand: "Mystery",
            category: nil, confidence: 0.42, primaryUpc: nil,
            source: .gemini, productId: nil, imageUrl: nil
        )
        viewModel.query = "mystery"
        viewModel.pendingConfirmation = SearchViewModel.PendingConfirmation(
            primary: pick, alternatives: [], threshold: 0.70
        )
        mockClient.resolveFromSearchConfirmResult = .success(
            ConfirmResolutionResponse(product: TestFixtures.sampleProduct, logged: true)
        )

        await viewModel.confirmResolution(for: pick)

        XCTAssertEqual(mockClient.resolveFromSearchConfirmCallCount, 1)
        XCTAssertEqual(mockClient.resolveFromSearchConfirmLastRequest?.userConfirmed, true)
        XCTAssertEqual(mockClient.resolveFromSearchConfirmLastRequest?.deviceName, "Mystery Gadget Pro")
        XCTAssertEqual(mockClient.resolveFromSearchConfirmLastRequest?.query, "mystery",
                       "query passes through for server-side telemetry")
        XCTAssertNil(viewModel.pendingConfirmation,
                     "sheet must be dismissed after commit")
        XCTAssertNotNil(viewModel.presentedProductViewModel,
                        "confirmed product flows into the ScannerViewModel presentation")
    }

    func test_rejectResolution_logsRejection_andClearsState() async {
        // "Not quite — let me search again" → call /confirm with
        // user_confirmed=false for telemetry, clear pendingConfirmation.
        let primary = ProductSearchResult(
            deviceName: "Mystery Gadget Pro", model: nil, brand: "Mystery",
            category: nil, confidence: 0.42, primaryUpc: nil,
            source: .gemini, productId: nil, imageUrl: nil
        )
        viewModel.query = "mystery"
        viewModel.pendingConfirmation = SearchViewModel.PendingConfirmation(
            primary: primary, alternatives: [], threshold: 0.70
        )

        await viewModel.rejectResolution()

        XCTAssertEqual(mockClient.resolveFromSearchConfirmCallCount, 1)
        XCTAssertEqual(mockClient.resolveFromSearchConfirmLastRequest?.userConfirmed, false,
                       "rejection must still fire the endpoint so threshold-tuning telemetry lands")
        XCTAssertNil(viewModel.pendingConfirmation)
        XCTAssertNil(viewModel.presentedProductViewModel)
    }

    // MARK: - PR-2: Optimistic search-tap (experiment flag)

    /// Helper that flips the optimistic-search-tap flag for THIS test's
    /// scoped UserDefaults suite. The VM's featureGate reads the flag
    /// lazily, so flipping after construction is fine.
    private func enableOptimisticSearchTap() {
        testDefaults.set(true, forKey: FeatureGateService.optimisticSearchTapKey)
    }

    func test_optimisticTap_dbRow_stillUsesLegacyPath() async {
        // DB rows already have the productId — the optimistic flow only
        // helps when /resolve-from-search is on the critical path. DB rows
        // skip optimistic and go straight to presentProduct unchanged.
        enableOptimisticSearchTap()
        let productId = UUID()
        let result = ProductSearchResult(
            deviceName: "Sony WH-1000XM5", model: "WH-1000XM5", brand: "Sony",
            category: "headphones", confidence: 0.92, primaryUpc: "027242924864",
            source: .db, productId: productId, imageUrl: nil
        )

        await viewModel.handleResultTap(result)

        XCTAssertNotNil(viewModel.presentedProductViewModel)
        XCTAssertEqual(viewModel.presentedProductViewModel?.product?.id, productId)
        // DB path doesn't construct an OptimisticPriceVM, so it doesn't
        // call resolveProduct or resolveProductFromSearch.
        XCTAssertEqual(mockClient.resolveProductCallCount, 0)
        XCTAssertEqual(mockClient.resolveFromSearchCallCount, 0)
    }

    func test_optimisticTap_nonDB_success_constructsOptimisticVMAndStreams() async {
        enableOptimisticSearchTap()
        mockClient.resolveProductResult = .success(TestFixtures.sampleProduct)
        mockClient.streamPricesEvents = TestFixtures.successfulStreamEvents
        let result = ProductSearchResult(
            deviceName: "Apple AirPods Pro 2", model: "AirPods Pro 2", brand: "Apple",
            category: "earbuds", confidence: 0.88, primaryUpc: "195949046674",
            source: .gemini, productId: nil, imageUrl: nil
        )

        await viewModel.handleResultTap(result)

        XCTAssertNotNil(viewModel.presentedProductViewModel,
                        "Optimistic path navigates immediately, presentedVM stays alive on success")
        XCTAssertEqual(mockClient.resolveProductCallCount, 1, "UPC path used inside OptimisticVM")
        XCTAssertEqual(mockClient.streamPricesCallCount, 1,
                       "SSE stream fires after the resolve swap")
        XCTAssertNil(viewModel.pendingConfirmation)
        XCTAssertFalse(viewModel.unresolvedAfterTap)
        XCTAssertNil(viewModel.error)
    }

    func test_optimisticTap_nonDB_409_tearsDownVMAndPresentsConfirmationSheet() async {
        enableOptimisticSearchTap()
        let primary = ProductSearchResult(
            deviceName: "Mystery Gadget Pro", model: nil, brand: "Mystery",
            category: nil, confidence: 0.42, primaryUpc: nil,
            source: .gemini, productId: nil, imageUrl: nil
        )
        let alt = ProductSearchResult(
            deviceName: "Mystery Gadget Plus", model: nil, brand: "Mystery",
            category: nil, confidence: 0.35, primaryUpc: nil,
            source: .gemini, productId: nil, imageUrl: nil
        )
        viewModel.results = [primary, alt]
        mockClient.resolveFromSearchResult = .success(
            .needsConfirmation(
                candidate: LowConfidenceCandidate(
                    deviceName: primary.deviceName,
                    brand: primary.brand,
                    model: primary.model,
                    confidence: 0.42,
                    threshold: 0.70
                )
            )
        )

        await viewModel.handleResultTap(primary)

        XCTAssertNil(viewModel.presentedProductViewModel,
                     "Optimistic skeleton must tear down so the confirmation sheet renders")
        XCTAssertNotNil(viewModel.pendingConfirmation,
                        "Routes through the existing confirmation flow on the SearchVM")
        XCTAssertEqual(viewModel.pendingConfirmation?.primary.deviceName, "Mystery Gadget Pro")
        XCTAssertEqual(viewModel.pendingConfirmation?.threshold, 0.70)
    }

    func test_optimisticTap_nonDB_404_tearsDownVMAndSetsUnresolvedAfterTap() async {
        enableOptimisticSearchTap()
        mockClient.resolveFromSearchResult = .failure(.notFound())
        let result = ProductSearchResult(
            deviceName: "Unknown Mystery Gadget", model: nil, brand: nil,
            category: nil, confidence: 0.3, primaryUpc: nil,
            source: .gemini, productId: nil, imageUrl: nil
        )

        await viewModel.handleResultTap(result)

        XCTAssertNil(viewModel.presentedProductViewModel,
                     "Optimistic skeleton must tear down so UnresolvedProductView renders")
        XCTAssertTrue(viewModel.unresolvedAfterTap,
                      "Routes through the existing unresolved flow on the SearchVM")
    }

    func test_optimisticTap_nonDB_serverError_tearsDownVMAndSetsError() async {
        enableOptimisticSearchTap()
        mockClient.resolveFromSearchResult = .failure(.server("500 internal"))
        let result = ProductSearchResult(
            deviceName: "Some Product", model: nil, brand: nil,
            category: nil, confidence: 0.5, primaryUpc: nil,
            source: .gemini, productId: nil, imageUrl: nil
        )

        await viewModel.handleResultTap(result)

        XCTAssertNil(viewModel.presentedProductViewModel)
        XCTAssertNotNil(viewModel.error)
        if case .server(let msg) = viewModel.error {
            XCTAssertEqual(msg, "500 internal")
        } else {
            XCTFail("Expected .server error, got \(String(describing: viewModel.error))")
        }
    }

    func test_optimisticTap_disabledByDefault_routesThroughLegacyPath() async {
        // No `enableOptimisticSearchTap()` call — default is OFF.
        mockClient.resolveProductResult = .success(TestFixtures.sampleProduct)
        mockClient.streamPricesEvents = TestFixtures.successfulStreamEvents
        let result = ProductSearchResult(
            deviceName: "Apple AirPods Pro 2", model: "AirPods Pro 2", brand: "Apple",
            category: "earbuds", confidence: 0.88, primaryUpc: "195949046674",
            source: .gemini, productId: nil, imageUrl: nil
        )

        await viewModel.handleResultTap(result)

        // Both paths end up presenting a VM with prices, but the legacy
        // path's distinguishing behavior is that it sets `isLoading = true`
        // during the await, then back to false. The optimistic path never
        // touches `isLoading` — it sets `presentedProductViewModel` first.
        XCTAssertNotNil(viewModel.presentedProductViewModel)
        XCTAssertFalse(viewModel.isLoading,
                       "Legacy path resets isLoading via defer before returning")
    }

    // MARK: - Clear

    func test_clearRecentSearches_emptiesMirrorAndStorage() async {
        await viewModel.onSearchSubmitted("iPhone 17 Pro")
        viewModel.clearRecentSearches()
        XCTAssertTrue(viewModel.recentSearches.isEmpty)
        XCTAssertTrue(recents.all().isEmpty)
    }
}
