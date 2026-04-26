import XCTest
@testable import Barkain

// MARK: - RecommendationViewModelTests (Step 3e)
//
// Exercises the post-close settle-flag gate on `ScannerViewModel`. The
// hero must render only after SSE done + identity + cards all settle,
// and the fetch must fire exactly once per product lifecycle.

@MainActor
final class RecommendationViewModelTests: XCTestCase {

    // MARK: - Fixtures

    private var mockClient: MockAPIClient!
    private var viewModel: ScannerViewModel!
    private var testDefaults: UserDefaults!

    override func setUp() {
        super.setUp()
        IdentityCache.shared.invalidateAll()
        mockClient = MockAPIClient()
        let suite = "test.recommend_vm.\(UUID().uuidString)"
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

    func test_recommendationFires_afterAllThreeStreamsSettle() async {
        mockClient.streamPricesEvents = TestFixtures.successfulStreamEvents
        mockClient.fetchRecommendationResult = .success(.loaded(TestFixtures.sampleRecommendation))

        await viewModel.handleBarcodeScan(upc: "012345678901")
        await viewModel._awaitRecommendationTaskForTesting()

        XCTAssertEqual(mockClient.fetchRecommendationCallCount, 1,
                       "Hero fetch must fire exactly once per scan lifecycle")
        XCTAssertEqual(viewModel.recommendation?.winner.retailerId, "amazon")
        XCTAssertEqual(mockClient.fetchRecommendationLastProductId,
                       TestFixtures.sampleProductId)
    }

    func test_recommendationFailure_leavesHeroNilAndDoesNotAlert() async {
        mockClient.streamPricesEvents = TestFixtures.successfulStreamEvents
        mockClient.fetchRecommendationResult = .failure(.server("boom"))

        await viewModel.handleBarcodeScan(upc: "012345678901")
        await viewModel._awaitRecommendationTaskForTesting()

        // The hero stays nil and NO priceError is set — the retailer
        // list remains the primary UX.
        XCTAssertNil(viewModel.recommendation)
        XCTAssertNil(viewModel.priceError)
    }

    func test_recommendationInsufficientData_setsExplicitStateAndReason() async {
        // demo-prep-1 Item 1: 422 RECOMMEND_INSUFFICIENT_DATA must produce
        // an explicit `.insufficientData(reason:)` state so the view can
        // render a dedicated card — NOT a silent hero-is-missing state
        // (the L-perf-L4 F&F silent-handback failure mode).
        mockClient.streamPricesEvents = TestFixtures.successfulStreamEvents
        mockClient.fetchRecommendationResult = .success(
            .insufficientData(reason: "Only 1 usable prices for product abc")
        )

        await viewModel.handleBarcodeScan(upc: "012345678901")
        await viewModel._awaitRecommendationTaskForTesting()

        XCTAssertEqual(mockClient.fetchRecommendationCallCount, 1)
        XCTAssertNil(viewModel.recommendation,
                     ".recommendation (loaded-only view) must be nil")
        XCTAssertEqual(viewModel.insufficientDataReason,
                       "Only 1 usable prices for product abc",
                       "reason surfaces for logging/debug even though the view renders canned copy")
        XCTAssertEqual(viewModel.recommendationState,
                       .insufficientData(reason: "Only 1 usable prices for product abc"))
        // Retailer list must remain untouched — priceError stays nil so
        // the view keeps rendering the per-retailer grid below the card.
        XCTAssertNil(viewModel.priceError)
    }

    func test_insufficientData_keepsRetailerGridPopulated() async {
        // The retailer grid is driven by `priceComparison` (populated by the
        // SSE stream), NOT by `recommendation`. Insufficient-data on the
        // hero must NOT clear priceComparison — the user still needs to see
        // whatever retailer prices did arrive.
        mockClient.streamPricesEvents = TestFixtures.successfulStreamEvents
        mockClient.fetchRecommendationResult = .success(
            .insufficientData(reason: "Only 1 usable prices for product abc")
        )

        await viewModel.handleBarcodeScan(upc: "012345678901")
        await viewModel._awaitRecommendationTaskForTesting()

        XCTAssertNotNil(viewModel.priceComparison,
                        "priceComparison must stay populated so the retailer grid still renders")
        XCTAssertFalse(viewModel.priceComparison?.prices.isEmpty ?? true,
                       "at least one successful retailer row should remain visible")
        XCTAssertNotNil(viewModel.insufficientDataReason,
                        "the fallback card's state signal must be set")
    }

    func test_reset_clearsInsufficientDataState() async {
        // When a new scan follows an insufficient-data scan, state must
        // return to `.pending` so the next fetch re-gates cleanly.
        mockClient.streamPricesEvents = TestFixtures.successfulStreamEvents
        mockClient.fetchRecommendationResult = .success(
            .insufficientData(reason: "Only 0 usable prices")
        )

        await viewModel.handleBarcodeScan(upc: "012345678901")
        await viewModel._awaitRecommendationTaskForTesting()
        XCTAssertNotNil(viewModel.insufficientDataReason)

        viewModel.reset()

        XCTAssertNil(viewModel.insufficientDataReason)
        XCTAssertEqual(viewModel.recommendationState, .pending)
    }

    func test_reset_clearsRecommendationAndSettleFlags() async {
        mockClient.streamPricesEvents = TestFixtures.successfulStreamEvents
        mockClient.fetchRecommendationResult = .success(.loaded(TestFixtures.sampleRecommendation))

        await viewModel.handleBarcodeScan(upc: "012345678901")
        await viewModel._awaitRecommendationTaskForTesting()
        XCTAssertNotNil(viewModel.recommendation)

        viewModel.reset()

        XCTAssertNil(viewModel.recommendation)
        XCTAssertNil(viewModel.product)
    }

    func test_fetchPrices_refresh_refiresRecommendationOnce() async {
        mockClient.streamPricesEvents = TestFixtures.successfulStreamEvents
        mockClient.fetchRecommendationResult = .success(.loaded(TestFixtures.sampleRecommendation))

        await viewModel.handleBarcodeScan(upc: "012345678901")
        await viewModel._awaitRecommendationTaskForTesting()
        let firstCount = mockClient.fetchRecommendationCallCount
        XCTAssertEqual(firstCount, 1)

        await viewModel.fetchPrices(forceRefresh: true)
        await viewModel._awaitRecommendationTaskForTesting()

        XCTAssertEqual(mockClient.fetchRecommendationCallCount, firstCount + 1,
                       "A forced refresh should re-fire the hero fetch exactly once")
    }
}
