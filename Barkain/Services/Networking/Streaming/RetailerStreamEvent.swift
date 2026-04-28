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
    /// Populated by the backend's price-stream backfill. Null when the stream
    /// found no listings carrying an image URL — fall back to whatever
    /// `Product.image_url` was at resolve-time (which may also be nil).
    let productImageUrl: String?
    let totalRetailers: Int
    let retailersSucceeded: Int
    let retailersFailed: Int
    let cached: Bool
    let fetchedAt: Date

    private enum CodingKeys: String, CodingKey {
        case productId, productName, productImageUrl, totalRetailers, retailersSucceeded
        case retailersFailed, cached, fetchedAt
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.productId = try c.decode(UUID.self, forKey: .productId)
        self.productName = try c.decode(String.self, forKey: .productName)
        self.productImageUrl = try c.decodeIfPresent(String.self, forKey: .productImageUrl)
        self.totalRetailers = try c.decode(Int.self, forKey: .totalRetailers)
        self.retailersSucceeded = try c.decode(Int.self, forKey: .retailersSucceeded)
        self.retailersFailed = try c.decode(Int.self, forKey: .retailersFailed)
        self.cached = try c.decode(Bool.self, forKey: .cached)
        self.fetchedAt = try c.decode(Date.self, forKey: .fetchedAt)
    }

    // The custom Decodable init above suppressed Swift's synthesized
    // memberwise initializer. Tests construct StreamSummary directly
    // (`ScannerViewModelTests.makeDoneSummary`), so retain a memberwise
    // form. `productImageUrl` defaults to nil for the legacy call sites
    // that pre-date the thumbnail-coverage field.
    init(
        productId: UUID,
        productName: String,
        productImageUrl: String? = nil,
        totalRetailers: Int,
        retailersSucceeded: Int,
        retailersFailed: Int,
        cached: Bool,
        fetchedAt: Date
    ) {
        self.productId = productId
        self.productName = productName
        self.productImageUrl = productImageUrl
        self.totalRetailers = totalRetailers
        self.retailersSucceeded = retailersSucceeded
        self.retailersFailed = retailersFailed
        self.cached = cached
        self.fetchedAt = fetchedAt
    }
}

// MARK: - StreamError

nonisolated struct StreamError: Decodable, Equatable, Sendable {
    let code: String
    let message: String
}
