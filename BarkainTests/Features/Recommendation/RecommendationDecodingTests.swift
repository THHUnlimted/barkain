import XCTest
@testable import Barkain

// MARK: - RecommendationDecodingTests (Step 3e)
//
// Locks the snake→camel mapping from the backend wire shape. The main
// risk here is a rename on either side: if the Python schema adds a
// field the iOS DTO doesn't know about we silently ignore it (good);
// if iOS expects a field that backend renames we fail-closed (bad).
// These tests catch the second case.

final class RecommendationDecodingTests: XCTestCase {

    // MARK: - Helpers

    private func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    /// Production decoder shape for `RetailerPrice` payloads — they
    /// carry an ISO-8601 `last_checked` timestamp from the backend.
    /// Existing `RecommendationDecodingTests` don't decode dates so
    /// `makeDecoder()` doesn't set the strategy; this helper does.
    private func makeRetailerPriceDecoder() -> JSONDecoder {
        let decoder = makeDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }

    // MARK: - Tests

    func test_decodesFullRecommendationFromJSON() throws {
        let decoder = makeDecoder()

        let rec = try decoder.decode(Recommendation.self, from: TestFixtures.recommendationJSON)

        XCTAssertEqual(rec.productId, TestFixtures.sampleProductId)
        XCTAssertEqual(rec.productName, "Sony WH-1000XM5")
        XCTAssertEqual(rec.winner.retailerId, "amazon")
        XCTAssertEqual(rec.winner.basePrice, 298.0, accuracy: 0.001)
        XCTAssertEqual(rec.winner.cardSource, "Chase Freedom Flex")
        XCTAssertNil(rec.winner.identitySource)
        XCTAssertEqual(rec.alternatives.count, 0)
        XCTAssertNil(rec.brandDirectCallout)
        XCTAssertTrue(rec.hasStackableValue)
        XCTAssertEqual(rec.computeMs, 42)
        XCTAssertFalse(rec.cached)
    }

    func test_decodesBrandDirectCalloutAndStack() throws {
        let decoder = makeDecoder()

        let rec = try decoder.decode(
            Recommendation.self, from: TestFixtures.recommendationWithCalloutJSON
        )

        XCTAssertNotNil(rec.brandDirectCallout)
        XCTAssertEqual(rec.brandDirectCallout?.retailerId, "samsung_direct")
        XCTAssertEqual(rec.brandDirectCallout?.discountValue ?? 0.0, 30.0, accuracy: 0.01)
        XCTAssertEqual(rec.winner.identitySavings, 300.0, accuracy: 0.01)
        XCTAssertEqual(rec.winner.portalSource, "rakuten")
        XCTAssertEqual(rec.winner.cardSavings, 14.0, accuracy: 0.01)
    }

    func test_decodesSnakeCaseFieldsIntoCamelCase() throws {
        let decoder = makeDecoder()

        let rec = try decoder.decode(Recommendation.self, from: TestFixtures.recommendationJSON)

        // Spot-check the fields that would break if `.convertFromSnakeCase`
        // wasn't applied to the top-level decoder.
        XCTAssertEqual(rec.winner.effectiveCost, 283.10, accuracy: 0.01)
        XCTAssertEqual(rec.winner.totalSavings, 14.90, accuracy: 0.01)
        XCTAssertEqual(rec.winner.productUrl, "https://amazon.com/dp/B0BSHF7WHN")
    }

    // MARK: - RetailerPrice.locationDefaultUsed (fb-resolver-followups L12)

    /// fb_marketplace + no fb_location_id ⇒ backend sets
    /// `location_default_used: true`. iOS decodes it onto
    /// `RetailerPrice.locationDefaultUsed`; the SF-default pill in
    /// `PriceRow` is gated on this exact flag.
    func test_retailerPrice_decodesLocationDefaultUsedTrue() throws {
        let json = """
        {
          "retailer_id": "fb_marketplace",
          "retailer_name": "Facebook Marketplace",
          "price": 199.99,
          "original_price": null,
          "currency": "USD",
          "url": null,
          "condition": "used",
          "is_available": true,
          "is_on_sale": false,
          "last_checked": "2026-04-22T12:00:00Z",
          "location_default_used": true
        }
        """.data(using: .utf8)!
        let price = try makeRetailerPriceDecoder().decode(RetailerPrice.self, from: json)
        XCTAssertEqual(price.retailerId, "fb_marketplace")
        XCTAssertEqual(price.locationDefaultUsed, true)
    }

    /// Other retailers' payloads MUST NOT carry the flag (backend
    /// scopes it). Decoding silently maps an absent key to `nil`, and
    /// the pill renders only when the flag is exactly `true`.
    func test_retailerPrice_locationDefaultUsedAbsentDecodesAsNil() throws {
        let json = """
        {
          "retailer_id": "amazon",
          "retailer_name": "Amazon",
          "price": 298.00,
          "original_price": 349.99,
          "currency": "USD",
          "url": "https://amazon.com/dp/X",
          "condition": "new",
          "is_available": true,
          "is_on_sale": true,
          "last_checked": "2026-04-22T12:00:00Z"
        }
        """.data(using: .utf8)!
        let price = try makeRetailerPriceDecoder().decode(RetailerPrice.self, from: json)
        XCTAssertEqual(price.retailerId, "amazon")
        XCTAssertNil(price.locationDefaultUsed)
    }
}
