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
}
