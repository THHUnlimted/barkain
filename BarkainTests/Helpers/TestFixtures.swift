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
}
