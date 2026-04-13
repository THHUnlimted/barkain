import XCTest
@testable import Barkain

@MainActor
final class ScannerViewModelTests: XCTestCase {

    // MARK: - Properties

    private var mockClient: MockAPIClient!
    private var viewModel: ScannerViewModel!

    // MARK: - Setup

    override func setUp() {
        super.setUp()
        mockClient = MockAPIClient()
        viewModel = ScannerViewModel(apiClient: mockClient)
    }

    override func tearDown() {
        viewModel = nil
        mockClient = nil
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
}
