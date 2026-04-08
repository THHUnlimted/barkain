import Foundation

// MARK: - PriceComparison

nonisolated struct PriceComparison: Codable, Equatable, Sendable {
    let productId: UUID
    let productName: String
    let prices: [RetailerPrice]
    let totalRetailers: Int
    let retailersSucceeded: Int
    let retailersFailed: Int
    let cached: Bool
    let fetchedAt: Date
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
    let condition: String
    let isAvailable: Bool
    let isOnSale: Bool
    let lastChecked: Date

    private enum CodingKeys: String, CodingKey {
        case retailerId, retailerName, price, originalPrice, currency
        case url, condition, isAvailable, isOnSale, lastChecked
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
