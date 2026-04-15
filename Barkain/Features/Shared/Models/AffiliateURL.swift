import Foundation

// MARK: - AffiliateClickRequest
//
// Body for POST /api/v1/affiliate/click. Encoded with .convertToSnakeCase
// so `productId` → `product_id`, `productUrl` → `product_url`, etc.

nonisolated struct AffiliateClickRequest: Codable, Sendable, Equatable {
    let productId: UUID?
    let retailerId: String
    let productUrl: String
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
