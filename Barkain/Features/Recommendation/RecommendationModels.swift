import Foundation

// MARK: - Recommendation DTOs (Step 3e)
//
// Mirrors `backend/modules/m6_recommend/schemas.py`. Snake-case keys are
// handled by `APIClient.decoder.keyDecodingStrategy = .convertFromSnakeCase`
// — no CodingKeys needed on these structs because every server field is a
// straight snake→camel mapping with no acronym quirks (`discount_value`,
// `brand_direct_callout`, etc.).

// MARK: - StackedPath

nonisolated struct StackedPath: Codable, Equatable, Sendable, Identifiable, Hashable {
    var id: String { retailerId }

    let retailerId: String
    let retailerName: String
    let basePrice: Double
    let finalPrice: Double
    let effectiveCost: Double
    let totalSavings: Double

    let identitySavings: Double
    let identitySource: String?
    let cardSavings: Double
    let cardSource: String?
    let portalSavings: Double
    let portalSource: String?

    let condition: String
    let productUrl: String?
}

// MARK: - BrandDirectCallout

nonisolated struct BrandDirectCallout: Codable, Equatable, Sendable, Hashable {
    let retailerId: String
    let retailerName: String
    let programName: String
    let discountValue: Double
    let discountType: String
    let purchaseUrlTemplate: String?
}

// MARK: - Recommendation

nonisolated struct Recommendation: Codable, Equatable, Sendable, Hashable {
    let productId: UUID
    let productName: String
    let winner: StackedPath
    let headline: String
    let why: String
    let alternatives: [StackedPath]
    let brandDirectCallout: BrandDirectCallout?
    let hasStackableValue: Bool
    let computeMs: Int
    let cached: Bool
}

// MARK: - Request

nonisolated struct RecommendationRequest: Codable, Equatable, Sendable {
    let productId: UUID
    let forceRefresh: Bool

    init(productId: UUID, forceRefresh: Bool = false) {
        self.productId = productId
        self.forceRefresh = forceRefresh
    }
}
