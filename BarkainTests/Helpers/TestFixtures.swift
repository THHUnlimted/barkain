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
}
