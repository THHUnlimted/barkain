import XCTest
@testable import Barkain

@MainActor
final class OptimisticPriceVMTests: XCTestCase {

    // MARK: - Properties

    private var mockClient: MockAPIClient!
    private var featureGate: FeatureGateService!
    private var testDefaults: UserDefaults!

    private var sampleResultWithUPC: ProductSearchResult!
    private var sampleResultWithoutUPC: ProductSearchResult!

    // MARK: - Setup

    override func setUp() {
        super.setUp()
        IdentityCache.shared.invalidateAll()
        mockClient = MockAPIClient()
        let suite = "test.optimistic_vm.\(UUID().uuidString)"
        testDefaults = UserDefaults(suiteName: suite)!
        testDefaults.removePersistentDomain(forName: suite)
        featureGate = FeatureGateService(
            proTierProvider: { false },
            defaults: testDefaults,
            clock: Date.init
        )
        sampleResultWithUPC = ProductSearchResult(
            deviceName: "Sony WH-1000XM5",
            model: "WH-1000XM5",
            brand: "Sony",
            category: "headphones",
            confidence: 0.95,
            primaryUpc: "027242924864",
            source: .upcitemdb,
            productId: nil,
            imageUrl: "https://example.com/sony.jpg"
        )
        sampleResultWithoutUPC = ProductSearchResult(
            deviceName: "AirPods Pro 2",
            model: nil,
            brand: "Apple",
            category: "headphones",
            confidence: 0.7,
            primaryUpc: nil,
            source: .gemini,
            productId: nil,
            imageUrl: nil
        )
    }

    override func tearDown() {
        mockClient = nil
        featureGate = nil
        testDefaults = nil
        sampleResultWithUPC = nil
        sampleResultWithoutUPC = nil
        super.tearDown()
    }

    // MARK: - Init: synthetic product seeding

    func test_init_seedsSyntheticProductFromHint_soSkeletonRendersImmediately() {
        let vm = OptimisticPriceVM(
            result: sampleResultWithUPC,
            query: "sony headphones",
            apiClient: mockClient,
            featureGate: featureGate
        )

        // PriceComparisonView's pre-first-event branch needs both:
        XCTAssertNotNil(vm.product, "Skeleton needs a non-nil product to render")
        XCTAssertTrue(vm.isPriceLoading, "Skeleton needs isPriceLoading=true")

        // Synthetic product mirrors the row hint so the user sees the
        // product card with their chosen item, not a placeholder.
        XCTAssertEqual(vm.product?.name, "Sony WH-1000XM5")
        XCTAssertEqual(vm.product?.brand, "Sony")
        XCTAssertEqual(vm.product?.upc, "027242924864")
        XCTAssertEqual(vm.product?.imageUrl, "https://example.com/sony.jpg")
        XCTAssertEqual(vm.product?.source, "search_hint",
                       "Synthetic product is tagged so downstream code can detect it")
    }

    // MARK: - Resolve: UPC path

    func test_start_withUPC_callsResolveProduct_andSwapsToRealProduct() async {
        let realProduct = TestFixtures.sampleProduct
        mockClient.resolveProductResult = .success(realProduct)
        mockClient.streamPricesEvents = TestFixtures.successfulStreamEvents

        let vm = OptimisticPriceVM(
            result: sampleResultWithUPC,
            query: "sony",
            apiClient: mockClient,
            featureGate: featureGate
        )

        var reportedOutcome: OptimisticResolveOutcome?
        vm.onResolveOutcome = { reportedOutcome = $0 }
        await vm.start()

        XCTAssertEqual(mockClient.resolveProductCallCount, 1,
                       "UPC-bearing rows should hit /products/resolve directly")
        XCTAssertEqual(mockClient.resolveProductLastUPC, "027242924864")
        if case .success(let product) = reportedOutcome {
            XCTAssertEqual(product.id, realProduct.id)
        } else {
            XCTFail("Expected .success outcome, got \(String(describing: reportedOutcome))")
        }
        // Inner VM swapped the synthetic product for the real one.
        XCTAssertEqual(vm.product?.id, realProduct.id)
        XCTAssertEqual(vm.product?.source, "gemini_upc",
                       "Synthetic source should be replaced by the real Product's source")
    }

    func test_start_withUPC_404FallsThroughToDescriptionBasedResolve() async {
        mockClient.resolveProductResult = .failure(.notFound())
        mockClient.resolveFromSearchResult = .success(.loaded(TestFixtures.sampleProduct))
        mockClient.streamPricesEvents = TestFixtures.successfulStreamEvents

        let vm = OptimisticPriceVM(
            result: sampleResultWithUPC,
            query: "sony",
            apiClient: mockClient,
            featureGate: featureGate
        )

        var reportedOutcome: OptimisticResolveOutcome?
        vm.onResolveOutcome = { reportedOutcome = $0 }
        await vm.start()

        XCTAssertEqual(mockClient.resolveProductCallCount, 1, "UPC tried first")
        XCTAssertEqual(mockClient.resolveFromSearchCallCount, 1,
                       "Description-based resolve is the fallback after UPC 404")
        if case .success = reportedOutcome { /* ok */ } else {
            XCTFail("Expected .success after fallback resolved")
        }
    }

    // MARK: - Resolve: description-based path

    func test_start_withoutUPC_skipsUPCPathAndResolvesByDescription() async {
        mockClient.resolveFromSearchResult = .success(.loaded(TestFixtures.sampleProduct))
        mockClient.streamPricesEvents = TestFixtures.successfulStreamEvents

        let vm = OptimisticPriceVM(
            result: sampleResultWithoutUPC,
            query: "airpods",
            apiClient: mockClient,
            featureGate: featureGate
        )

        var reportedOutcome: OptimisticResolveOutcome?
        vm.onResolveOutcome = { reportedOutcome = $0 }
        await vm.start()

        XCTAssertEqual(mockClient.resolveProductCallCount, 0,
                       "UPC path skipped when primaryUpc is nil")
        XCTAssertEqual(mockClient.resolveFromSearchCallCount, 1)
        XCTAssertEqual(mockClient.resolveFromSearchLastDeviceName, "AirPods Pro 2")
        XCTAssertEqual(mockClient.resolveFromSearchLastBrand, "Apple")
        if case .success = reportedOutcome { /* ok */ } else {
            XCTFail("Expected .success outcome")
        }
    }

    // MARK: - Resolve outcomes

    func test_start_with409_reportsNeedsConfirmation_andDoesNotFireFetchPrices() async {
        let candidate = LowConfidenceCandidate(
            deviceName: "AirPods Pro 2",
            brand: "Apple",
            model: nil,
            confidence: 0.55,
            threshold: 0.70
        )
        mockClient.resolveFromSearchResult = .success(.needsConfirmation(candidate: candidate))

        let vm = OptimisticPriceVM(
            result: sampleResultWithoutUPC,
            query: "airpods",
            apiClient: mockClient,
            featureGate: featureGate
        )

        var reportedOutcome: OptimisticResolveOutcome?
        vm.onResolveOutcome = { reportedOutcome = $0 }
        await vm.start()

        if case .needsConfirmation(let reportedCandidate) = reportedOutcome {
            XCTAssertEqual(reportedCandidate.threshold, 0.70)
            XCTAssertEqual(reportedCandidate.confidence, 0.55)
        } else {
            XCTFail("Expected .needsConfirmation, got \(String(describing: reportedOutcome))")
        }
        XCTAssertEqual(mockClient.getPricesCallCount, 0,
                       "Stream must NOT fire when confirmation is needed")
    }

    func test_start_with404_reportsUnresolved_andClearsLoadingState() async {
        mockClient.resolveFromSearchResult = .failure(.notFound())

        let vm = OptimisticPriceVM(
            result: sampleResultWithoutUPC,
            query: "airpods",
            apiClient: mockClient,
            featureGate: featureGate
        )

        var reportedOutcome: OptimisticResolveOutcome?
        vm.onResolveOutcome = { reportedOutcome = $0 }
        await vm.start()

        if case .unresolved = reportedOutcome { /* ok */ } else {
            XCTFail("Expected .unresolved, got \(String(describing: reportedOutcome))")
        }
        XCTAssertFalse(vm.isPriceLoading,
                       "Skeleton should stop spinning so the unresolved view replaces it cleanly")
    }

    func test_start_withServerError_reportsFailed() async {
        mockClient.resolveFromSearchResult = .failure(.server("500 internal"))

        let vm = OptimisticPriceVM(
            result: sampleResultWithoutUPC,
            query: "airpods",
            apiClient: mockClient,
            featureGate: featureGate
        )

        var reportedOutcome: OptimisticResolveOutcome?
        vm.onResolveOutcome = { reportedOutcome = $0 }
        await vm.start()

        if case .failed(let err) = reportedOutcome {
            if case .server(let msg) = err {
                XCTAssertEqual(msg, "500 internal")
            } else {
                XCTFail("Expected .server error, got \(err)")
            }
        } else {
            XCTFail("Expected .failed outcome, got \(String(describing: reportedOutcome))")
        }
    }

    // MARK: - Idempotency

    func test_start_calledTwice_secondCallIsNoOp() async {
        mockClient.resolveProductResult = .success(TestFixtures.sampleProduct)
        mockClient.streamPricesEvents = TestFixtures.successfulStreamEvents

        let vm = OptimisticPriceVM(
            result: sampleResultWithUPC,
            query: "sony",
            apiClient: mockClient,
            featureGate: featureGate
        )

        await vm.start()
        let firstResolveCount = mockClient.resolveProductCallCount
        await vm.start()  // second call

        XCTAssertEqual(mockClient.resolveProductCallCount, firstResolveCount,
                       "Second start() must be a no-op so the resolve doesn't fire twice")
    }
}
