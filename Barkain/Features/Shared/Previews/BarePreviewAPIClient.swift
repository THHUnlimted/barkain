import Foundation

// MARK: - BarePreviewAPIClient (Step 3f Pre-Fix #2)
//
// Every `#Preview` that needs an `APIClientProtocol` used to ship its own
// struct with 20+ fatalError-or-empty stubs. Adding a protocol method meant
// touching every one. Subclass this instead and override only what the
// preview actually calls. Unimplemented methods trap with a clear message
// pointing at the missing override.
//
// Internal access level (not `open`): the app module's DTOs are internal,
// so `open` would trip "method cannot be declared open because its result
// uses an internal type". Internal subclassing works fine within the module.

class BarePreviewAPIClient: APIClientProtocol, @unchecked Sendable {

    init() {}

    // MARK: - Product

    func resolveProduct(upc: String, fallbackImageURL: String?) async throws -> Product {
        previewUnimplemented()
    }

    func resolveProductFromSearch(
        deviceName: String,
        brand: String?,
        model: String?,
        confidence: Double?,
        fallbackImageURL: String?,
        query: String?
    ) async throws -> ResolveFromSearchOutcome {
        previewUnimplemented()
    }

    func resolveProductFromSearchConfirm(
        _ request: ResolveFromSearchConfirmRequest
    ) async throws -> ConfirmResolutionResponse {
        previewUnimplemented()
    }

    func searchProducts(
        query: String,
        maxResults: Int,
        forceGemini: Bool
    ) async throws -> ProductSearchResponse {
        ProductSearchResponse(query: query, results: [], totalResults: 0, cached: false)
    }

    // MARK: - Prices

    func getPrices(
        productId: UUID,
        forceRefresh: Bool
    ) async throws -> PriceComparison {
        previewUnimplemented()
    }

    func streamPrices(
        productId: UUID,
        forceRefresh: Bool,
        queryOverride: String?,
        fbLocationId: String?,
        fbRadiusMiles: Int?
    ) -> AsyncThrowingStream<RetailerStreamEvent, Error> {
        AsyncThrowingStream { $0.finish() }
    }

    // MARK: - FB Marketplace location (fb-marketplace-location-resolver)

    func resolveFbLocation(
        city: String,
        state: String
    ) async throws -> ResolvedFbLocation {
        ResolvedFbLocation(
            locationId: "108271525863730",
            canonicalName: "\(city), \(state)",
            verified: true,
            resolutionPath: "live"
        )
    }

    // MARK: - Identity (Step 2d)

    func getIdentityProfile() async throws -> IdentityProfile {
        previewUnimplemented()
    }

    func updateIdentityProfile(
        _ request: IdentityProfileRequest
    ) async throws -> IdentityProfile {
        previewUnimplemented()
    }

    func getEligibleDiscounts(
        productId: UUID?
    ) async throws -> IdentityDiscountsResponse {
        IdentityDiscountsResponse(eligibleDiscounts: [], identityGroupsActive: [])
    }

    // MARK: - Cards (Step 2e)

    func getCardCatalog() async throws -> [CardRewardProgram] { [] }

    func getUserCards() async throws -> [UserCardSummary] { [] }

    func addCard(
        _ request: AddCardRequest
    ) async throws -> UserCardSummary {
        previewUnimplemented()
    }

    func removeCard(userCardId: UUID) async throws {}

    func setPreferredCard(
        userCardId: UUID
    ) async throws -> UserCardSummary {
        previewUnimplemented()
    }

    func setCardCategories(
        userCardId: UUID,
        request: SetCategoriesRequest
    ) async throws {}

    func getCardRecommendations(
        productId: UUID
    ) async throws -> CardRecommendationsResponse {
        CardRecommendationsResponse(recommendations: [], userHasCards: false)
    }

    // MARK: - Billing (Step 2f)

    func getBillingStatus() async throws -> BillingStatus {
        BillingStatus(tier: "free", expiresAt: nil, isActive: false, entitlementId: nil)
    }

    // MARK: - Affiliate (Step 2g)

    func getAffiliateURL(
        productId: UUID?,
        retailerId: String,
        productURL: String,
        activationSkipped: Bool,
        portalEventType: String?,
        portalSource: String?
    ) async throws -> AffiliateURLResponse {
        AffiliateURLResponse(
            affiliateUrl: productURL,
            isAffiliated: false,
            network: nil,
            retailerId: retailerId
        )
    }

    func getAffiliateStats() async throws -> AffiliateStatsResponse {
        AffiliateStatsResponse(clicksByRetailer: [:], totalClicks: 0)
    }

    // MARK: - Recommendation (Step 3e)

    func fetchRecommendation(
        productId: UUID,
        forceRefresh: Bool,
        userMemberships: [String: Bool]?
    ) async throws -> RecommendationFetchOutcome {
        .insufficientData(reason: "Preview default — override in preview subclass")
    }

    // MARK: - Misc retailer (Step 3n)

    func getMiscRetailers(productId: UUID, query: String?) async throws -> [MiscMerchantRow] {
        []
    }

    // MARK: - Helpers

    private func previewUnimplemented(
        _ function: StaticString = #function,
        file: StaticString = #file,
        line: UInt = #line
    ) -> Never {
        fatalError(
            "BarePreviewAPIClient.\(function) invoked in a preview — override it in your preview subclass",
            file: file,
            line: line
        )
    }
}
