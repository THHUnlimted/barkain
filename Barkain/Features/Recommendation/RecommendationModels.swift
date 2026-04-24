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

    // Step 3g-B: actionable portal CTAs (member deeplink / signup referral
    // / guided-only). Only the winner carries CTAs; alternatives default to
    // []. Custom decoder uses decodeIfPresent so older v4-cached payloads
    // (no portal_ctas field) decode cleanly.
    //
    // NOTE: lowercase `portalCtas` (not `portalCTAs`) intentionally — Apple's
    // `.convertFromSnakeCase` strategy maps `portal_ctas` → `portalCtas` and
    // can't recover the all-caps `CTAs` acronym, so the property name follows
    // the same lowercase-acronym convention used elsewhere in the codebase
    // (`productUrl`, not `productURL`).
    let portalCtas: [PortalCTA]

    let condition: String
    let productUrl: String?

    // MARK: - Codable

    private enum CodingKeys: String, CodingKey {
        case retailerId, retailerName, basePrice, finalPrice, effectiveCost
        case totalSavings, identitySavings, identitySource, cardSavings, cardSource
        case portalSavings, portalSource, portalCtas, condition, productUrl
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        retailerId = try c.decode(String.self, forKey: .retailerId)
        retailerName = try c.decode(String.self, forKey: .retailerName)
        basePrice = try c.decode(Double.self, forKey: .basePrice)
        finalPrice = try c.decode(Double.self, forKey: .finalPrice)
        effectiveCost = try c.decode(Double.self, forKey: .effectiveCost)
        totalSavings = try c.decode(Double.self, forKey: .totalSavings)
        identitySavings = try c.decode(Double.self, forKey: .identitySavings)
        identitySource = try c.decodeIfPresent(String.self, forKey: .identitySource)
        cardSavings = try c.decode(Double.self, forKey: .cardSavings)
        cardSource = try c.decodeIfPresent(String.self, forKey: .cardSource)
        portalSavings = try c.decode(Double.self, forKey: .portalSavings)
        portalSource = try c.decodeIfPresent(String.self, forKey: .portalSource)
        portalCtas = try c.decodeIfPresent([PortalCTA].self, forKey: .portalCtas) ?? []
        condition = try c.decode(String.self, forKey: .condition)
        productUrl = try c.decodeIfPresent(String.self, forKey: .productUrl)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(retailerId, forKey: .retailerId)
        try c.encode(retailerName, forKey: .retailerName)
        try c.encode(basePrice, forKey: .basePrice)
        try c.encode(finalPrice, forKey: .finalPrice)
        try c.encode(effectiveCost, forKey: .effectiveCost)
        try c.encode(totalSavings, forKey: .totalSavings)
        try c.encode(identitySavings, forKey: .identitySavings)
        try c.encodeIfPresent(identitySource, forKey: .identitySource)
        try c.encode(cardSavings, forKey: .cardSavings)
        try c.encodeIfPresent(cardSource, forKey: .cardSource)
        try c.encode(portalSavings, forKey: .portalSavings)
        try c.encodeIfPresent(portalSource, forKey: .portalSource)
        try c.encode(portalCtas, forKey: .portalCtas)
        try c.encode(condition, forKey: .condition)
        try c.encodeIfPresent(productUrl, forKey: .productUrl)
    }

    // Memberwise init kept for tests + previews.
    init(
        retailerId: String,
        retailerName: String,
        basePrice: Double,
        finalPrice: Double,
        effectiveCost: Double,
        totalSavings: Double,
        identitySavings: Double = 0,
        identitySource: String? = nil,
        cardSavings: Double = 0,
        cardSource: String? = nil,
        portalSavings: Double = 0,
        portalSource: String? = nil,
        portalCtas: [PortalCTA] = [],
        condition: String = "new",
        productUrl: String? = nil
    ) {
        self.retailerId = retailerId
        self.retailerName = retailerName
        self.basePrice = basePrice
        self.finalPrice = finalPrice
        self.effectiveCost = effectiveCost
        self.totalSavings = totalSavings
        self.identitySavings = identitySavings
        self.identitySource = identitySource
        self.cardSavings = cardSavings
        self.cardSource = cardSource
        self.portalSavings = portalSavings
        self.portalSource = portalSource
        self.portalCtas = portalCtas
        self.condition = condition
        self.productUrl = productUrl
    }
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

// MARK: - RecommendationState (demo-prep-1 Item 1)

/// Three-way recommendation state used by `ScannerViewModel` and
/// `PriceComparisonView`. Replaces the old `recommendation: Recommendation?`
/// optional which couldn't distinguish "still loading" from "server said no"
/// — a silent-hero UX that looked indistinguishable from a broken app
/// during F&F demos.
///
/// - `.pending`: settle-flag gate not yet open, or fetch in flight, or
///   fetch threw a non-422 error (silent-fail contract preserved).
/// - `.loaded(Recommendation)`: happy path.
/// - `.insufficientData(reason:)`: backend returned 422
///   `RECOMMEND_INSUFFICIENT_DATA`. Reason is the backend message for
///   logging/debug; the view renders its own localized copy.
enum RecommendationState: Equatable, Sendable {
    case pending
    case loaded(Recommendation)
    case insufficientData(reason: String)
}

/// API-layer outcome — distinct from the VM state so the APIClient doesn't
/// leak VM concepts (`.pending` is a VM state, not a wire state).
enum RecommendationFetchOutcome: Equatable, Sendable {
    case loaded(Recommendation)
    case insufficientData(reason: String)
}

// MARK: - Request

nonisolated struct RecommendationRequest: Codable, Equatable, Sendable {
    let productId: UUID
    let forceRefresh: Bool
    /// Step 3g-B — sparse map of portal_source → true for portals the user
    /// reports being a member of. Backend folds this into the cache-key
    /// hash so toggles bust stale recs immediately. Omitted (encodes as
    /// `null`) when the user hasn't opted into any portals; backend
    /// defaults missing/null to {}.
    let userMemberships: [String: Bool]?

    init(
        productId: UUID,
        forceRefresh: Bool = false,
        userMemberships: [String: Bool]? = nil
    ) {
        self.productId = productId
        self.forceRefresh = forceRefresh
        self.userMemberships = userMemberships
    }
}
