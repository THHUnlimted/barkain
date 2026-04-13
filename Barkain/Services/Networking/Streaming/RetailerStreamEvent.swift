import Foundation

// MARK: - RetailerStreamEvent

/// Typed SSE events emitted by `GET /api/v1/prices/{id}/stream`.
///
/// `retailerResult` lands the moment one retailer (out of 11) completes its
/// extraction. `done` closes the stream with an aggregate summary. `error`
/// signals a pipeline failure that the client should fall back from.
nonisolated enum RetailerStreamEvent: Equatable, Sendable {
    case retailerResult(RetailerResultUpdate)
    case done(StreamSummary)
    case error(StreamError)
}

// MARK: - RetailerResultUpdate

nonisolated struct RetailerResultUpdate: Decodable, Equatable, Sendable {
    let retailerId: String
    let retailerName: String
    let status: RetailerResult.Status
    let price: RetailerPrice?

    private enum CodingKeys: String, CodingKey {
        case retailerId, retailerName, status, price
    }
}

// MARK: - StreamSummary

nonisolated struct StreamSummary: Decodable, Equatable, Sendable {
    let productId: UUID
    let productName: String
    let totalRetailers: Int
    let retailersSucceeded: Int
    let retailersFailed: Int
    let cached: Bool
    let fetchedAt: Date

    private enum CodingKeys: String, CodingKey {
        case productId, productName, totalRetailers, retailersSucceeded
        case retailersFailed, cached, fetchedAt
    }
}

// MARK: - StreamError

nonisolated struct StreamError: Decodable, Equatable, Sendable {
    let code: String
    let message: String
}
