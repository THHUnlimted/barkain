import Foundation
@testable import Barkain

// MARK: - MockAPIClient

final class MockAPIClient: APIClientProtocol, @unchecked Sendable {

    // MARK: - Configurable Results

    var resolveProductResult: Result<Product, APIError> = .success(TestFixtures.sampleProduct)
    var getPricesResult: Result<PriceComparison, APIError> = .success(TestFixtures.samplePriceComparison)
    var getIdentityProfileResult: Result<IdentityProfile, APIError> = .success(TestFixtures.sampleIdentityProfile)
    var updateIdentityProfileResult: Result<IdentityProfile, APIError> = .success(TestFixtures.sampleIdentityProfile)
    var getEligibleDiscountsResult: Result<IdentityDiscountsResponse, APIError> = .success(
        TestFixtures.emptyIdentityDiscounts
    )

    // MARK: - Call Tracking

    var resolveProductCallCount = 0
    var resolveProductLastUPC: String?
    var getPricesCallCount = 0
    var getPricesLastProductId: UUID?
    var getPricesLastForceRefresh: Bool?
    var getIdentityProfileCallCount = 0
    var updateIdentityProfileCallCount = 0
    var updateIdentityProfileLastRequest: IdentityProfileRequest?
    var getEligibleDiscountsCallCount = 0
    var getEligibleDiscountsLastProductId: UUID??

    // MARK: - Delay simulation

    var resolveProductDelay: TimeInterval = 0
    var getPricesDelay: TimeInterval = 0

    // MARK: - Streaming (Step 2c)

    /// Events replayed by `streamPrices(productId:forceRefresh:)` in order.
    var streamPricesEvents: [RetailerStreamEvent] = []
    /// Per-event delay — simulates network-ordered SSE frames.
    var streamPricesPerEventDelay: TimeInterval = 0
    /// If non-nil, the stream finishes with this error after replaying events.
    var streamPricesError: APIError?

    var streamPricesCallCount = 0
    var streamPricesLastProductId: UUID?
    var streamPricesLastForceRefresh: Bool?

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
        getPricesLastForceRefresh = forceRefresh
        if getPricesDelay > 0 {
            try await Task.sleep(for: .seconds(getPricesDelay))
        }
        return try getPricesResult.get()
    }

    func getIdentityProfile() async throws -> IdentityProfile {
        getIdentityProfileCallCount += 1
        return try getIdentityProfileResult.get()
    }

    func updateIdentityProfile(_ request: IdentityProfileRequest) async throws -> IdentityProfile {
        updateIdentityProfileCallCount += 1
        updateIdentityProfileLastRequest = request
        return try updateIdentityProfileResult.get()
    }

    func getEligibleDiscounts(productId: UUID?) async throws -> IdentityDiscountsResponse {
        getEligibleDiscountsCallCount += 1
        getEligibleDiscountsLastProductId = productId
        return try getEligibleDiscountsResult.get()
    }

    func streamPrices(
        productId: UUID,
        forceRefresh: Bool
    ) -> AsyncThrowingStream<RetailerStreamEvent, Error> {
        streamPricesCallCount += 1
        streamPricesLastProductId = productId
        streamPricesLastForceRefresh = forceRefresh

        let events = streamPricesEvents
        let delay = streamPricesPerEventDelay
        let terminalError = streamPricesError

        return AsyncThrowingStream { continuation in
            Task {
                for event in events {
                    if delay > 0 {
                        try? await Task.sleep(for: .seconds(delay))
                    }
                    continuation.yield(event)
                }
                if let terminalError {
                    continuation.finish(throwing: terminalError)
                } else {
                    continuation.finish()
                }
            }
        }
    }
}
