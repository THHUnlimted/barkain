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
}
