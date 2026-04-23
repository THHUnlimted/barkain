import Foundation
@testable import Barkain

// MARK: - MockAPIClient

final class MockAPIClient: APIClientProtocol, @unchecked Sendable {

    // MARK: - Configurable Results

    var resolveProductResult: Result<Product, APIError> = .success(TestFixtures.sampleProduct)
    var resolveFromSearchResult: Result<Product, APIError> = .success(TestFixtures.sampleProduct)
    var searchProductsResult: Result<ProductSearchResponse, APIError> = .success(
        ProductSearchResponse(query: "", results: [], totalResults: 0, cached: false)
    )
    var getPricesResult: Result<PriceComparison, APIError> = .success(TestFixtures.samplePriceComparison)
    var getIdentityProfileResult: Result<IdentityProfile, APIError> = .success(TestFixtures.sampleIdentityProfile)
    var updateIdentityProfileResult: Result<IdentityProfile, APIError> = .success(TestFixtures.sampleIdentityProfile)
    var getEligibleDiscountsResult: Result<IdentityDiscountsResponse, APIError> = .success(
        TestFixtures.emptyIdentityDiscounts
    )

    // MARK: - Call Tracking

    var resolveProductCallCount = 0
    var resolveProductLastUPC: String?
    var resolveFromSearchCallCount = 0
    var resolveFromSearchLastDeviceName: String?
    var resolveFromSearchLastBrand: String?
    var resolveFromSearchLastModel: String?
    var searchProductsCallCount = 0
    var searchProductsLastQuery: String?
    var searchProductsLastMaxResults: Int?
    var searchProductsLastForceGemini: Bool?
    var searchProductsDelay: TimeInterval = 0
    var getPricesCallCount = 0
    var getPricesLastProductId: UUID?
    var getPricesLastForceRefresh: Bool?
    var getIdentityProfileCallCount = 0
    var updateIdentityProfileCallCount = 0
    var updateIdentityProfileLastRequest: IdentityProfileRequest?
    var getEligibleDiscountsCallCount = 0
    var getEligibleDiscountsLastProductId: UUID??

    // MARK: - Cards (Step 2e)

    var getCardCatalogResult: Result<[CardRewardProgram], APIError> = .success([])
    var getUserCardsResult: Result<[UserCardSummary], APIError> = .success([])
    var addCardResult: Result<UserCardSummary, APIError> = .success(TestFixtures.sampleUserCardSummary)
    var removeCardResult: Result<Void, APIError> = .success(())
    var setPreferredCardResult: Result<UserCardSummary, APIError> = .success(TestFixtures.sampleUserCardSummary)
    var setCardCategoriesResult: Result<Void, APIError> = .success(())
    var getCardRecommendationsResult: Result<CardRecommendationsResponse, APIError> = .success(
        TestFixtures.emptyCardRecommendations
    )

    var getCardCatalogCallCount = 0
    var getUserCardsCallCount = 0
    var addCardCallCount = 0
    var addCardLastRequest: AddCardRequest?
    var removeCardCallCount = 0
    var removeCardLastId: UUID?
    var setPreferredCardCallCount = 0
    var setPreferredCardLastId: UUID?
    var setCardCategoriesCallCount = 0
    var setCardCategoriesLastId: UUID?
    var setCardCategoriesLastRequest: SetCategoriesRequest?
    var getCardRecommendationsCallCount = 0
    var getCardRecommendationsLastProductId: UUID?

    // MARK: - Billing (Step 2f)

    var getBillingStatusResult: Result<BillingStatus, APIError> = .success(
        BillingStatus(tier: "free", expiresAt: nil, isActive: false, entitlementId: nil)
    )
    var getBillingStatusCallCount = 0

    // MARK: - Affiliate (Step 2g)

    var getAffiliateURLResult: Result<AffiliateURLResponse, APIError> = .success(
        AffiliateURLResponse(
            affiliateUrl: "https://example.com",
            isAffiliated: false,
            network: nil,
            retailerId: "mock"
        )
    )
    var getAffiliateStatsResult: Result<AffiliateStatsResponse, APIError> = .success(
        AffiliateStatsResponse(clicksByRetailer: [:], totalClicks: 0)
    )
    var getAffiliateURLCallCount = 0
    var getAffiliateURLLastProductId: UUID?
    var getAffiliateURLLastRetailerId: String?
    var getAffiliateURLLastProductURL: String?
    var getAffiliateURLLastActivationSkipped: Bool?
    var getAffiliateURLLastPortalEventType: String?
    var getAffiliateURLLastPortalSource: String?
    var getAffiliateStatsCallCount = 0

    // MARK: - Recommendation (Step 3e)

    /// `.success(nil)` mirrors the 422 `RECOMMEND_INSUFFICIENT_DATA`
    /// branch — the APIClient maps that status to a nil return so the
    /// ViewModel leaves the hero unrendered. Real errors are surfaced
    /// as `.failure`.
    var fetchRecommendationResult: Result<Recommendation?, APIError> = .success(nil)
    var fetchRecommendationCallCount = 0
    var fetchRecommendationLastProductId: UUID?
    var fetchRecommendationLastForceRefresh: Bool?
    var fetchRecommendationLastUserMemberships: [String: Bool]?
    /// Optional delay so tests can verify the fetch fires AFTER all three
    /// settle flags have flipped.
    var fetchRecommendationDelay: TimeInterval = 0

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

    func resolveProductFromSearch(
        deviceName: String,
        brand: String?,
        model: String?
    ) async throws -> Product {
        resolveFromSearchCallCount += 1
        resolveFromSearchLastDeviceName = deviceName
        resolveFromSearchLastBrand = brand
        resolveFromSearchLastModel = model
        return try resolveFromSearchResult.get()
    }

    func searchProducts(query: String, maxResults: Int, forceGemini: Bool) async throws -> ProductSearchResponse {
        searchProductsCallCount += 1
        searchProductsLastQuery = query
        searchProductsLastMaxResults = maxResults
        searchProductsLastForceGemini = forceGemini
        if searchProductsDelay > 0 {
            try await Task.sleep(for: .seconds(searchProductsDelay))
        }
        return try searchProductsResult.get()
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

    // MARK: - Cards (Step 2e)

    func getCardCatalog() async throws -> [CardRewardProgram] {
        getCardCatalogCallCount += 1
        return try getCardCatalogResult.get()
    }

    func getUserCards() async throws -> [UserCardSummary] {
        getUserCardsCallCount += 1
        return try getUserCardsResult.get()
    }

    func addCard(_ request: AddCardRequest) async throws -> UserCardSummary {
        addCardCallCount += 1
        addCardLastRequest = request
        return try addCardResult.get()
    }

    func removeCard(userCardId: UUID) async throws {
        removeCardCallCount += 1
        removeCardLastId = userCardId
        _ = try removeCardResult.get()
    }

    func setPreferredCard(userCardId: UUID) async throws -> UserCardSummary {
        setPreferredCardCallCount += 1
        setPreferredCardLastId = userCardId
        return try setPreferredCardResult.get()
    }

    func setCardCategories(userCardId: UUID, request: SetCategoriesRequest) async throws {
        setCardCategoriesCallCount += 1
        setCardCategoriesLastId = userCardId
        setCardCategoriesLastRequest = request
        _ = try setCardCategoriesResult.get()
    }

    func getCardRecommendations(productId: UUID) async throws -> CardRecommendationsResponse {
        getCardRecommendationsCallCount += 1
        getCardRecommendationsLastProductId = productId
        return try getCardRecommendationsResult.get()
    }

    // MARK: - Billing (Step 2f)

    func getBillingStatus() async throws -> BillingStatus {
        getBillingStatusCallCount += 1
        return try getBillingStatusResult.get()
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
        getAffiliateURLCallCount += 1
        getAffiliateURLLastProductId = productId
        getAffiliateURLLastRetailerId = retailerId
        getAffiliateURLLastProductURL = productURL
        getAffiliateURLLastActivationSkipped = activationSkipped
        getAffiliateURLLastPortalEventType = portalEventType
        getAffiliateURLLastPortalSource = portalSource
        return try getAffiliateURLResult.get()
    }

    func getAffiliateStats() async throws -> AffiliateStatsResponse {
        getAffiliateStatsCallCount += 1
        return try getAffiliateStatsResult.get()
    }

    func fetchRecommendation(
        productId: UUID,
        forceRefresh: Bool,
        userMemberships: [String: Bool]?
    ) async throws -> Recommendation? {
        fetchRecommendationCallCount += 1
        fetchRecommendationLastProductId = productId
        fetchRecommendationLastForceRefresh = forceRefresh
        fetchRecommendationLastUserMemberships = userMemberships
        if fetchRecommendationDelay > 0 {
            try? await Task.sleep(for: .seconds(fetchRecommendationDelay))
        }
        return try fetchRecommendationResult.get()
    }

    var streamPricesLastQueryOverride: String?
    var streamPricesLastFbLocationId: String?
    var streamPricesLastFbRadiusMiles: Int?

    func streamPrices(
        productId: UUID,
        forceRefresh: Bool,
        queryOverride: String?,
        fbLocationId: String?,
        fbRadiusMiles: Int?
    ) -> AsyncThrowingStream<RetailerStreamEvent, Error> {
        streamPricesCallCount += 1
        streamPricesLastProductId = productId
        streamPricesLastForceRefresh = forceRefresh
        streamPricesLastQueryOverride = queryOverride
        streamPricesLastFbLocationId = fbLocationId
        streamPricesLastFbRadiusMiles = fbRadiusMiles

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

    // MARK: - FB Marketplace location (fb-marketplace-location-resolver)

    var resolveFbLocationResult: Result<ResolvedFbLocation, APIError> = .success(
        ResolvedFbLocation(
            locationId: "108271525863730",
            canonicalName: "Accident, MD",
            verified: true,
            resolutionPath: "live"
        )
    )
    var resolveFbLocationCallCount = 0
    var resolveFbLocationLastCity: String?
    var resolveFbLocationLastState: String?

    func resolveFbLocation(
        city: String,
        state: String
    ) async throws -> ResolvedFbLocation {
        resolveFbLocationCallCount += 1
        resolveFbLocationLastCity = city
        resolveFbLocationLastState = state
        return try resolveFbLocationResult.get()
    }
}
