import Foundation

// MARK: - AffiliateClickRequest
//
// Body for POST /api/v1/affiliate/click. Encoded with .convertToSnakeCase
// so `productId` → `product_id`, `productUrl` → `product_url`, etc.

nonisolated struct AffiliateClickRequest: Codable, Sendable, Equatable {
    let productId: UUID?
    let retailerId: String
    let productUrl: String
    // Step 3f — telemetry only. True when the purchase interstitial's
    // Continue button was tapped without first visiting the card
    // issuer's activation URL. Backend persists to
    // `affiliate_clicks.metadata` for post-demo analytics.
    let activationSkipped: Bool

    init(
        productId: UUID?,
        retailerId: String,
        productUrl: String,
        activationSkipped: Bool = false
    ) {
        self.productId = productId
        self.retailerId = retailerId
        self.productUrl = productUrl
        self.activationSkipped = activationSkipped
    }
}

// MARK: - AffiliateURLResponse
//
// Response from POST /api/v1/affiliate/click. Decoded via
// `.convertFromSnakeCase` so `affiliate_url` → `affiliateUrl`, etc.

nonisolated struct AffiliateURLResponse: Codable, Sendable, Equatable {
    let affiliateUrl: String
    let isAffiliated: Bool
    let network: String?
    let retailerId: String
}

// MARK: - AffiliateStatsResponse

nonisolated struct AffiliateStatsResponse: Codable, Sendable, Equatable {
    let clicksByRetailer: [String: Int]
    let totalClicks: Int
}
