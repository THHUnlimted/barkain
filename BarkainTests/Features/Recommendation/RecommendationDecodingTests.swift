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
}
