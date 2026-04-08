import Foundation
@testable import Barkain

// MARK: - MockAPIClient

final class MockAPIClient: APIClientProtocol, @unchecked Sendable {

    // MARK: - Configurable Results

    var resolveProductResult: Result<Product, APIError> = .success(TestFixtures.sampleProduct)
    var getPricesResult: Result<PriceComparison, APIError> = .success(TestFixtures.samplePriceComparison)

    // MARK: - Call Tracking

    var resolveProductCallCount = 0
    var resolveProductLastUPC: String?
    var getPricesCallCount = 0
    var getPricesLastProductId: UUID?

    // MARK: - Delay simulation

    var resolveProductDelay: TimeInterval = 0

    // MARK: - APIClientProtocol

    func resolveProduct(upc: String) async throws -> Product {
        resolveProductCallCount += 1
        resolveProductLastUPC = upc
        if resolveProductDelay > 0 {
            try await Task.sleep(for: .seconds(resolveProductDelay))
        }
        return try resolveProductResult.get()
    }

    func getPrices(productId: UUID, forceRefresh: Bool) async throws -> PriceComparison {
        getPricesCallCount += 1
        getPricesLastProductId = productId
        return try getPricesResult.get()
    }
}
