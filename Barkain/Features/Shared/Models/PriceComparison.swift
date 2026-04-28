import Foundation

// MARK: - PriceComparison

nonisolated struct PriceComparison: Codable, Equatable, Sendable {
    // Step 2c: mutable so ScannerViewModel can mutate in place as SSE events
    // arrive. SwiftUI @Observable triggers a re-render on each reassignment of
    // the whole struct on the parent model.
    var productId: UUID
    var productName: String
    /// Hero thumbnail. Backend backfills this from the first scraper that
    /// returns an image URL, so it can be nil at resolve-time but populated
    /// by the time `done` arrives — refresh the hero when it transitions.
    var productImageUrl: String?
    var prices: [RetailerPrice]
    var retailerResults: [RetailerResult]
    var totalRetailers: Int
    var retailersSucceeded: Int
    var retailersFailed: Int
    var cached: Bool
    var fetchedAt: Date

    private enum CodingKeys: String, CodingKey {
        case productId, productName, productImageUrl, prices, retailerResults
        case totalRetailers, retailersSucceeded, retailersFailed, cached, fetchedAt
    }

    init(
        productId: UUID,
        productName: String,
        productImageUrl: String? = nil,
        prices: [RetailerPrice],
        retailerResults: [RetailerResult] = [],
        totalRetailers: Int,
        retailersSucceeded: Int,
        retailersFailed: Int,
        cached: Bool,
        fetchedAt: Date
    ) {
        self.productId = productId
        self.productName = productName
        self.productImageUrl = productImageUrl
        self.prices = prices
        self.retailerResults = retailerResults
        self.totalRetailers = totalRetailers
        self.retailersSucceeded = retailersSucceeded
        self.retailersFailed = retailersFailed
        self.cached = cached
        self.fetchedAt = fetchedAt
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.productId = try c.decode(UUID.self, forKey: .productId)
        self.productName = try c.decode(String.self, forKey: .productName)
        self.productImageUrl = try c.decodeIfPresent(String.self, forKey: .productImageUrl)
        self.prices = try c.decode([RetailerPrice].self, forKey: .prices)
        // retailerResults is optional for graceful upgrade — old Redis cache entries
        // written before the schema change won't have it.
        self.retailerResults = try c.decodeIfPresent([RetailerResult].self, forKey: .retailerResults) ?? []
        self.totalRetailers = try c.decode(Int.self, forKey: .totalRetailers)
        self.retailersSucceeded = try c.decode(Int.self, forKey: .retailersSucceeded)
        self.retailersFailed = try c.decode(Int.self, forKey: .retailersFailed)
        self.cached = try c.decode(Bool.self, forKey: .cached)
        self.fetchedAt = try c.decode(Date.self, forKey: .fetchedAt)
    }
}

// MARK: - RetailerResult

nonisolated struct RetailerResult: Codable, Equatable, Sendable, Identifiable {
    var id: String { retailerId }

    let retailerId: String
    let retailerName: String
    let status: Status

    enum Status: String, Codable, Sendable {
        case success
        case noMatch = "no_match"
        case unavailable
    }

    private enum CodingKeys: String, CodingKey {
        case retailerId, retailerName, status
    }
}

// MARK: - RetailerPrice

nonisolated struct RetailerPrice: Codable, Identifiable, Equatable, Sendable {
    var id: String { retailerId + condition }

    let retailerId: String
    let retailerName: String
    let price: Double
    let originalPrice: Double?
    let currency: String
    let url: String?
    let imageUrl: String?
    let condition: String
    let isAvailable: Bool
    let isOnSale: Bool
    let lastChecked: Date
    /// Set ONLY on the fb_marketplace row, ONLY when the user has not
    /// saved a Marketplace location (so the container fell back to the
    /// baked `sanfrancisco` default). Drives the "Using SF default —
    /// set your city in Profile" pill in `PriceRow`. Optional + decoded
    /// via `decodeIfPresent` so other retailers' payloads are unaffected
    /// and pre-followup cache entries decode cleanly.
    let locationDefaultUsed: Bool?

    private enum CodingKeys: String, CodingKey {
        case retailerId, retailerName, price, originalPrice, currency
        case url, imageUrl, condition, isAvailable, isOnSale, lastChecked
        case locationDefaultUsed
    }

    init(
        retailerId: String,
        retailerName: String,
        price: Double,
        originalPrice: Double? = nil,
        currency: String = "USD",
        url: String? = nil,
        imageUrl: String? = nil,
        condition: String = "new",
        isAvailable: Bool = true,
        isOnSale: Bool = false,
        lastChecked: Date,
        locationDefaultUsed: Bool? = nil
    ) {
        self.retailerId = retailerId
        self.retailerName = retailerName
        self.price = price
        self.originalPrice = originalPrice
        self.currency = currency
        self.url = url
        self.imageUrl = imageUrl
        self.condition = condition
        self.isAvailable = isAvailable
        self.isOnSale = isOnSale
        self.lastChecked = lastChecked
        self.locationDefaultUsed = locationDefaultUsed
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.retailerId = try c.decode(String.self, forKey: .retailerId)
        self.retailerName = try c.decode(String.self, forKey: .retailerName)
        self.price = try c.decode(Double.self, forKey: .price)
        self.originalPrice = try c.decodeIfPresent(Double.self, forKey: .originalPrice)
        self.currency = try c.decode(String.self, forKey: .currency)
        self.url = try c.decodeIfPresent(String.self, forKey: .url)
        self.imageUrl = try c.decodeIfPresent(String.self, forKey: .imageUrl)
        self.condition = try c.decode(String.self, forKey: .condition)
        self.isAvailable = try c.decode(Bool.self, forKey: .isAvailable)
        self.isOnSale = try c.decode(Bool.self, forKey: .isOnSale)
        self.lastChecked = try c.decode(Date.self, forKey: .lastChecked)
        self.locationDefaultUsed = try c.decodeIfPresent(Bool.self, forKey: .locationDefaultUsed)
    }
}

// MARK: - API Error Response

nonisolated struct APIErrorResponse: Codable, Sendable {
    let error: APIErrorDetail
}

nonisolated struct APIErrorDetail: Codable, Sendable {
    let code: String
    let message: String
    let details: [String: String]?
}
