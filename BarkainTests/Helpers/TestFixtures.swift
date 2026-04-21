import Foundation
@testable import Barkain

// MARK: - TestFixtures

enum TestFixtures {

    // MARK: - Product

    static let sampleProductId = UUID(uuidString: "12345678-1234-1234-1234-123456789abc")!

    static let sampleProduct = Product(
        id: sampleProductId,
        upc: "012345678901",
        asin: "B0BSHF7WHN",
        name: "Sony WH-1000XM5",
        brand: "Sony",
        category: "headphones",
        imageUrl: "https://example.com/image.jpg",
        source: "gemini_upc"
    )

    // MARK: - PriceComparison

    static let samplePriceComparison = PriceComparison(
        productId: sampleProductId,
        productName: "Sony WH-1000XM5",
        prices: [
            RetailerPrice(
                retailerId: "amazon",
                retailerName: "Amazon",
                price: 298.00,
                originalPrice: 349.99,
                currency: "USD",
                url: "https://amazon.com/dp/B0BSHF7WHN",
                condition: "new",
                isAvailable: true,
                isOnSale: true,
                lastChecked: Date()
            ),
            RetailerPrice(
                retailerId: "best_buy",
                retailerName: "Best Buy",
                price: 329.99,
                originalPrice: nil,
                currency: "USD",
                url: "https://bestbuy.com/site/123",
                condition: "new",
                isAvailable: true,
                isOnSale: false,
                lastChecked: Date()
            ),
            RetailerPrice(
                retailerId: "walmart",
                retailerName: "Walmart",
                price: 299.99,
                originalPrice: nil,
                currency: "USD",
                url: "https://walmart.com/ip/123",
                condition: "new",
                isAvailable: true,
                isOnSale: false,
                lastChecked: Date()
            ),
        ],
        totalRetailers: 11,
        retailersSucceeded: 3,
        retailersFailed: 0,
        cached: false,
        fetchedAt: Date()
    )

    // MARK: - Cached PriceComparison

    static let cachedPriceComparison = PriceComparison(
        productId: sampleProductId,
        productName: "Sony WH-1000XM5",
        prices: samplePriceComparison.prices,
        totalRetailers: 11,
        retailersSucceeded: 3,
        retailersFailed: 0,
        cached: true,
        fetchedAt: Date()
    )

    // MARK: - Empty PriceComparison

    static let emptyPriceComparison = PriceComparison(
        productId: sampleProductId,
        productName: "Sony WH-1000XM5",
        prices: [],
        totalRetailers: 11,
        retailersSucceeded: 0,
        retailersFailed: 11,
        cached: false,
        fetchedAt: Date()
    )

    // MARK: - Partial PriceComparison

    static let partialPriceComparison = PriceComparison(
        productId: sampleProductId,
        productName: "Sony WH-1000XM5",
        prices: [
            RetailerPrice(
                retailerId: "amazon",
                retailerName: "Amazon",
                price: 298.00,
                originalPrice: 349.99,
                currency: "USD",
                url: "https://amazon.com/dp/B0BSHF7WHN",
                condition: "new",
                isAvailable: true,
                isOnSale: true,
                lastChecked: Date()
            ),
        ],
        totalRetailers: 11,
        retailersSucceeded: 1,
        retailersFailed: 5,
        cached: false,
        fetchedAt: Date()
    )

    // MARK: - JSON Payloads

    static let productJSON = """
    {
        "id": "12345678-1234-1234-1234-123456789abc",
        "upc": "012345678901",
        "asin": "B0BSHF7WHN",
        "name": "Sony WH-1000XM5",
        "brand": "Sony",
        "category": "headphones",
        "image_url": "https://example.com/image.jpg",
        "source": "gemini_upc"
    }
    """.data(using: .utf8)!

    static let priceComparisonJSON = """
    {
        "product_id": "12345678-1234-1234-1234-123456789abc",
        "product_name": "Sony WH-1000XM5",
        "prices": [
            {
                "retailer_id": "amazon",
                "retailer_name": "Amazon",
                "price": 298.00,
                "original_price": 349.99,
                "currency": "USD",
                "url": "https://amazon.com/dp/B0BSHF7WHN",
                "condition": "new",
                "is_available": true,
                "is_on_sale": true,
                "last_checked": "2026-04-08T12:00:00.000000"
            }
        ],
        "total_retailers": 11,
        "retailers_succeeded": 1,
        "retailers_failed": 0,
        "cached": false,
        "fetched_at": "2026-04-08T12:00:00.000000"
    }
    """.data(using: .utf8)!

    static let notFoundErrorJSON = """
    {
        "error": {
            "code": "PRODUCT_NOT_FOUND",
            "message": "No product found for UPC 000000000000",
            "details": {}
        }
    }
    """.data(using: .utf8)!

    // MARK: - Identity (Step 2d)

    static let sampleIdentityProfile = IdentityProfile(
        userId: "user_test_123",
        isMilitary: false,
        isVeteran: false,
        isStudent: false,
        isTeacher: false,
        isFirstResponder: false,
        isNurse: false,
        isHealthcareWorker: false,
        isSenior: false,
        isGovernment: false,
        isYoungAdult: false,
        isAaaMember: false,
        isAarpMember: false,
        isCostcoMember: false,
        isPrimeMember: false,
        isSamsMember: false,
        idMeVerified: false,
        sheerIdVerified: false,
        createdAt: Date(),
        updatedAt: Date()
    )

    static let veteranIdentityProfile = IdentityProfile(
        userId: "user_test_123",
        isMilitary: false,
        isVeteran: true,
        isStudent: false,
        isTeacher: false,
        isFirstResponder: false,
        isNurse: false,
        isHealthcareWorker: false,
        isSenior: false,
        isGovernment: false,
        isYoungAdult: false,
        isAaaMember: false,
        isAarpMember: false,
        isCostcoMember: false,
        isPrimeMember: false,
        isSamsMember: false,
        idMeVerified: true,
        sheerIdVerified: false,
        createdAt: Date(),
        updatedAt: Date()
    )

    static let sampleEligibleDiscountSamsung = EligibleDiscount(
        programId: UUID(uuidString: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")!,
        retailerId: "samsung_direct",
        retailerName: "Samsung.com",
        programName: "Samsung Offer Program",
        eligibilityType: "veteran",
        discountType: "percentage",
        discountValue: 30,
        discountMaxValue: nil,
        discountDetails: "Up to 30% off. 2 products per category per year.",
        verificationMethod: "id_me",
        verificationUrl: "https://www.samsung.com/us/shop/offer-program/military",
        url: "https://www.samsung.com/us/shop/offer-program/military",
        estimatedSavings: 450
    )

    static let sampleEligibleDiscountHP = EligibleDiscount(
        programId: UUID(uuidString: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")!,
        retailerId: "hp_direct",
        retailerName: "HP.com",
        programName: "Frontline Heroes Program",
        eligibilityType: "veteran",
        discountType: "percentage",
        discountValue: 40,
        discountMaxValue: 55,
        discountDetails: "Up to 40% for military; up to 55% for healthcare workers.",
        verificationMethod: "id_me",
        verificationUrl: "https://www.hp.com/us-en/shop/cv/hp-frontline-heroes",
        url: "https://www.hp.com/us-en/shop/cv/hp-frontline-heroes",
        estimatedSavings: 600
    )

    static let sampleIdentityDiscountsResponse = IdentityDiscountsResponse(
        eligibleDiscounts: [sampleEligibleDiscountSamsung, sampleEligibleDiscountHP],
        identityGroupsActive: ["veteran"]
    )

    static let emptyIdentityDiscounts = IdentityDiscountsResponse(
        eligibleDiscounts: [],
        identityGroupsActive: []
    )

    // MARK: - Cards (Step 2e)

    static let sampleCardProgramId = UUID(uuidString: "aaaaaaaa-1111-1111-1111-aaaaaaaaaaaa")!

    static let sampleCardProgram = CardRewardProgram(
        id: sampleCardProgramId,
        cardNetwork: "visa",
        cardIssuer: "chase",
        cardProduct: "freedom_flex",
        cardDisplayName: "Chase Freedom Flex",
        baseRewardRate: 1.0,
        rewardCurrency: "ultimate_rewards",
        pointValueCents: 1.25,
        hasShoppingPortal: true,
        portalUrl: "https://ultimaterewardsmall.chase.com",
        annualFee: 0,
        userSelectedAllowed: nil
    )

    static let sampleUserCardSummaryId = UUID(uuidString: "bbbbbbbb-2222-2222-2222-bbbbbbbbbbbb")!

    static let sampleUserCardSummary = UserCardSummary(
        id: sampleUserCardSummaryId,
        cardProgramId: sampleCardProgramId,
        cardIssuer: "chase",
        cardProduct: "freedom_flex",
        cardDisplayName: "Chase Freedom Flex",
        nickname: "daily driver",
        isPreferred: true,
        baseRewardRate: 1.0,
        rewardCurrency: "ultimate_rewards"
    )

    static let sampleCardRecommendationAmazon = CardRecommendation(
        retailerId: "amazon",
        retailerName: "Amazon",
        userCardId: sampleUserCardSummaryId,
        cardProgramId: sampleCardProgramId,
        cardDisplayName: "Chase Freedom Flex",
        cardIssuer: "chase",
        rewardRate: 5.0,
        rewardAmount: 12.5,
        rewardCurrency: "ultimate_rewards",
        isRotatingBonus: true,
        isUserSelectedBonus: false,
        activationRequired: true,
        activationUrl: "https://example.com/activate"
    )

    static let sampleCardRecommendationsResponse = CardRecommendationsResponse(
        recommendations: [sampleCardRecommendationAmazon],
        userHasCards: true
    )

    static let emptyCardRecommendations = CardRecommendationsResponse(
        recommendations: [],
        userHasCards: false
    )

    // MARK: - Stream events (Step 3e — ready-made SSE sequence)

    /// Three retailer_result events followed by `done`. Matches the shape
    /// the backend emits for a successful cached SSE round-trip.
    static let successfulStreamEvents: [RetailerStreamEvent] = [
        .retailerResult(RetailerResultUpdate(
            retailerId: "amazon", retailerName: "Amazon",
            status: .success,
            price: RetailerPrice(
                retailerId: "amazon", retailerName: "Amazon",
                price: 298.0, originalPrice: 349.99, currency: "USD",
                url: "https://amazon.com/dp/B0BSHF7WHN", condition: "new",
                isAvailable: true, isOnSale: true, lastChecked: Date()
            )
        )),
        .retailerResult(RetailerResultUpdate(
            retailerId: "best_buy", retailerName: "Best Buy",
            status: .success,
            price: RetailerPrice(
                retailerId: "best_buy", retailerName: "Best Buy",
                price: 329.99, originalPrice: nil, currency: "USD",
                url: "https://bestbuy.com/site/123", condition: "new",
                isAvailable: true, isOnSale: false, lastChecked: Date()
            )
        )),
        .retailerResult(RetailerResultUpdate(
            retailerId: "walmart", retailerName: "Walmart",
            status: .success,
            price: RetailerPrice(
                retailerId: "walmart", retailerName: "Walmart",
                price: 299.99, originalPrice: nil, currency: "USD",
                url: "https://walmart.com/ip/123", condition: "new",
                isAvailable: true, isOnSale: false, lastChecked: Date()
            )
        )),
        .done(StreamSummary(
            productId: sampleProductId,
            productName: "Sony WH-1000XM5",
            totalRetailers: 3,
            retailersSucceeded: 3,
            retailersFailed: 0,
            cached: false,
            fetchedAt: Date()
        )),
    ]

    // MARK: - Recommendation (Step 3e)

    static let sampleStackedPathAmazon = StackedPath(
        retailerId: "amazon",
        retailerName: "Amazon",
        basePrice: 298.0,
        finalPrice: 298.0,
        effectiveCost: 283.10,
        totalSavings: 14.90,
        identitySavings: 0.0,
        identitySource: nil,
        cardSavings: 14.90,
        cardSource: "Chase Freedom Flex",
        portalSavings: 0.0,
        portalSource: nil,
        condition: "new",
        productUrl: "https://amazon.com/dp/B0BSHF7WHN"
    )

    static let sampleStackedPathBestBuy = StackedPath(
        retailerId: "best_buy",
        retailerName: "Best Buy",
        basePrice: 329.99,
        finalPrice: 329.99,
        effectiveCost: 316.39,
        totalSavings: 13.60,
        identitySavings: 0.0,
        identitySource: nil,
        cardSavings: 13.60,
        cardSource: "Chase Freedom Flex",
        portalSavings: 0.0,
        portalSource: nil,
        condition: "new",
        productUrl: "https://bestbuy.com/site/123"
    )

    static let sampleRecommendation = Recommendation(
        productId: sampleProductId,
        productName: "Sony WH-1000XM5",
        winner: sampleStackedPathAmazon,
        headline: "Amazon with Chase Freedom Flex",
        why: "Stacking Chase Freedom Flex earns $14.90 in rewards beats the naive cheapest listing by $14.90.",
        alternatives: [sampleStackedPathBestBuy],
        brandDirectCallout: nil,
        hasStackableValue: true,
        computeMs: 42,
        cached: false
    )

    static let recommendationJSON = """
    {
        "product_id": "12345678-1234-1234-1234-123456789abc",
        "product_name": "Sony WH-1000XM5",
        "winner": {
            "retailer_id": "amazon",
            "retailer_name": "Amazon",
            "base_price": 298.0,
            "final_price": 298.0,
            "effective_cost": 283.10,
            "total_savings": 14.90,
            "identity_savings": 0.0,
            "identity_source": null,
            "card_savings": 14.90,
            "card_source": "Chase Freedom Flex",
            "portal_savings": 0.0,
            "portal_source": null,
            "condition": "new",
            "product_url": "https://amazon.com/dp/B0BSHF7WHN"
        },
        "headline": "Amazon with Chase Freedom Flex",
        "why": "Lowest available price at Amazon.",
        "alternatives": [],
        "brand_direct_callout": null,
        "has_stackable_value": true,
        "compute_ms": 42,
        "cached": false
    }
    """.data(using: .utf8)!

    static let recommendationWithCalloutJSON = """
    {
        "product_id": "12345678-1234-1234-1234-123456789abc",
        "product_name": "Samsung Galaxy S25",
        "winner": {
            "retailer_id": "samsung_direct",
            "retailer_name": "Samsung.com",
            "base_price": 1000.0,
            "final_price": 700.0,
            "effective_cost": 658.0,
            "total_savings": 342.0,
            "identity_savings": 300.0,
            "identity_source": "Samsung Military",
            "card_savings": 14.0,
            "card_source": "Chase Freedom Flex",
            "portal_savings": 28.0,
            "portal_source": "rakuten",
            "condition": "new",
            "product_url": "https://samsung.com/p"
        },
        "headline": "Samsung.com via Rakuten with Chase Freedom Flex",
        "why": "Stacking Samsung Military saves $300.00 + Rakuten gives 28.00 back + Chase Freedom Flex earns $14.00 in rewards beats the naive cheapest listing by $342.00.",
        "alternatives": [],
        "brand_direct_callout": {
            "retailer_id": "samsung_direct",
            "retailer_name": "Samsung.com",
            "program_name": "Samsung Military",
            "discount_value": 30.0,
            "discount_type": "percentage",
            "purchase_url_template": "https://www.samsung.com/us/shop/offer-program/military"
        },
        "has_stackable_value": true,
        "compute_ms": 37,
        "cached": false
    }
    """.data(using: .utf8)!
}
