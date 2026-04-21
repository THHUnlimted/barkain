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
        mockClient.fetchRecommendationResult = .success(TestFixtures.sampleRecommendation)

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

    func test_recommendationInsufficientData_leavesHeroNilSilently() async {
        mockClient.streamPricesEvents = TestFixtures.successfulStreamEvents
        // 422 maps to a .success(nil) at the client boundary.
        mockClient.fetchRecommendationResult = .success(nil)

        await viewModel.handleBarcodeScan(upc: "012345678901")
        await viewModel._awaitRecommendationTaskForTesting()

        XCTAssertEqual(mockClient.fetchRecommendationCallCount, 1)
        XCTAssertNil(viewModel.recommendation)
        XCTAssertNil(viewModel.priceError)
    }

    func test_reset_clearsRecommendationAndSettleFlags() async {
        mockClient.streamPricesEvents = TestFixtures.successfulStreamEvents
        mockClient.fetchRecommendationResult = .success(TestFixtures.sampleRecommendation)

        await viewModel.handleBarcodeScan(upc: "012345678901")
        await viewModel._awaitRecommendationTaskForTesting()
        XCTAssertNotNil(viewModel.recommendation)

        viewModel.reset()

        XCTAssertNil(viewModel.recommendation)
        XCTAssertNil(viewModel.product)
    }

    func test_fetchPrices_refresh_refiresRecommendationOnce() async {
        mockClient.streamPricesEvents = TestFixtures.successfulStreamEvents
        mockClient.fetchRecommendationResult = .success(TestFixtures.sampleRecommendation)

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
