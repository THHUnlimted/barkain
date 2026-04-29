import XCTest
@testable import Barkain

final class APIClientTests: XCTestCase {

    // MARK: - Properties

    private var client: APIClient!
    private var session: URLSession!

    // MARK: - Setup

    override func setUp() {
        super.setUp()
        MockURLProtocol.reset()
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        session = URLSession(configuration: config)
        client = APIClient(
            session: session,
            baseURL: URL(string: "http://test.local")!
        )
    }

    override func tearDown() {
        MockURLProtocol.reset()
        client = nil
        session = nil
        super.tearDown()
    }

    // MARK: - Tests

    func test_resolveProduct_validResponse_decodesProduct() async throws {
        // Given
        MockURLProtocol.mockResponses["/api/v1/products/resolve"] = (
            data: TestFixtures.productJSON,
            statusCode: 200
        )

        // When
        let product = try await client.resolveProduct(upc: "012345678901")

        // Then
        XCTAssertEqual(product.id, TestFixtures.sampleProductId)
        XCTAssertEqual(product.name, "Sony WH-1000XM5")
        XCTAssertEqual(product.brand, "Sony")
        XCTAssertEqual(product.upc, "012345678901")
        XCTAssertEqual(product.source, "gemini_upc")
        XCTAssertEqual(product.imageUrl, "https://example.com/image.jpg")
    }

    func test_resolveProduct_404_throwsNotFoundError() async {
        // Given
        MockURLProtocol.mockResponses["/api/v1/products/resolve"] = (
            data: TestFixtures.notFoundErrorJSON,
            statusCode: 404
        )

        // When / Then
        do {
            _ = try await client.resolveProduct(upc: "000000000000")
            XCTFail("Expected notFound error")
        } catch let error as APIError {
            XCTAssertEqual(error, .notFound())
        } catch {
            XCTFail("Unexpected error type: \(error)")
        }
    }

    func test_getPrices_validResponse_decodesPriceComparison() async throws {
        // Given
        let productId = TestFixtures.sampleProductId
        MockURLProtocol.mockResponses["/api/v1/prices/\(productId.uuidString)"] = (
            data: TestFixtures.priceComparisonJSON,
            statusCode: 200
        )

        // When
        let comparison = try await client.getPrices(productId: productId)

        // Then — verifies snake_case → camelCase mapping
        XCTAssertEqual(comparison.productId, productId)
        XCTAssertEqual(comparison.productName, "Sony WH-1000XM5")
        XCTAssertEqual(comparison.prices.count, 1)
        XCTAssertEqual(comparison.totalRetailers, 11)
        XCTAssertEqual(comparison.retailersSucceeded, 1)
        XCTAssertFalse(comparison.cached)

        let amazonPrice = comparison.prices[0]
        XCTAssertEqual(amazonPrice.retailerId, "amazon")
        XCTAssertEqual(amazonPrice.retailerName, "Amazon")
        XCTAssertEqual(amazonPrice.price, 298.00)
        XCTAssertEqual(amazonPrice.originalPrice, 349.99)
        XCTAssertTrue(amazonPrice.isOnSale)
        XCTAssertTrue(amazonPrice.isAvailable)
    }
}
