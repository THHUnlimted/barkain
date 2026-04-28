import XCTest
@testable import Barkain

// MARK: - MiscMerchantRowTests (Step 3n)
//
// Locks the snake→camel mapping for the `/api/v1/misc/{product_id}`
// wire shape. Same risk profile as `RecommendationDecodingTests`: a
// rename on either side that the autodecoder doesn't catch slips
// through silently. These tests fail-closed on missing fields so an
// iOS rename is loud.

final class MiscMerchantRowTests: XCTestCase {

    // MARK: - Helpers

    private func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    private func makeEncoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        // Sort keys for deterministic round-trip comparisons.
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }

    // MARK: - Tests

    func test_decodesFullRowFromBackendShape() throws {
        // Mirrors the actual response from `/api/v1/misc/{product_id}`
        // after `_serper_shopping_fetch` strips imageUrl + the service
        // applies the KNOWN_RETAILER_DOMAINS filter + 3-row cap.
        let json = #"""
        {
          "title": "Royal Canin Adult Maintenance Dog Food",
          "source": "Chewy",
          "source_normalized": "chewy",
          "link": "https://www.google.com/shopping/product/abc",
          "price": "$84.99",
          "price_cents": 8499,
          "rating": 4.7,
          "rating_count": 1024,
          "product_id": "rc-adult-12",
          "position": 1
        }
        """#.data(using: .utf8)!

        let row = try makeDecoder().decode(MiscMerchantRow.self, from: json)

        XCTAssertEqual(row.title, "Royal Canin Adult Maintenance Dog Food")
        XCTAssertEqual(row.source, "Chewy")
        XCTAssertEqual(row.sourceNormalized, "chewy")
        XCTAssertEqual(row.link.absoluteString, "https://www.google.com/shopping/product/abc")
        XCTAssertEqual(row.price, "$84.99")
        XCTAssertEqual(row.priceCents, 8499)
        XCTAssertEqual(row.rating ?? 0, 4.7, accuracy: 0.01)
        XCTAssertEqual(row.ratingCount, 1024)
        XCTAssertEqual(row.productId, "rc-adult-12")
        XCTAssertEqual(row.position, 1)
    }

    func test_decodesNullableFieldsAsNil() throws {
        // Backend returns `null` for unparseable price strings, missing
        // ratings, no product_id. iOS must accept all of those.
        let json = #"""
        {
          "title": "Royal Canin",
          "source": "Petflow",
          "source_normalized": "petflow",
          "link": "https://x",
          "price": "Free shipping",
          "price_cents": null,
          "rating": null,
          "rating_count": null,
          "product_id": null,
          "position": 3
        }
        """#.data(using: .utf8)!

        let row = try makeDecoder().decode(MiscMerchantRow.self, from: json)

        XCTAssertNil(row.priceCents)
        XCTAssertNil(row.rating)
        XCTAssertNil(row.ratingCount)
        XCTAssertNil(row.productId)
    }

    func test_decodesArrayFromBackendCappedAtThree() throws {
        // Smoke test against the array endpoint shape.
        let json = #"""
        [
          {"title": "A", "source": "Chewy", "source_normalized": "chewy",
           "link": "https://a", "price": "$1", "price_cents": 100,
           "rating": null, "rating_count": null, "product_id": null, "position": 1},
          {"title": "B", "source": "Petco", "source_normalized": "petco",
           "link": "https://b", "price": "$2", "price_cents": 200,
           "rating": null, "rating_count": null, "product_id": null, "position": 2},
          {"title": "C", "source": "Petflow", "source_normalized": "petflow",
           "link": "https://c", "price": "$3", "price_cents": 300,
           "rating": null, "rating_count": null, "product_id": null, "position": 3}
        ]
        """#.data(using: .utf8)!

        let rows = try makeDecoder().decode([MiscMerchantRow].self, from: json)
        XCTAssertEqual(rows.count, 3)
        XCTAssertEqual(rows.map(\.sourceNormalized), ["chewy", "petco", "petflow"])
    }

    func test_idIsStableAcrossEncode() throws {
        let row = MiscMerchantRow(
            title: "X",
            source: "Chewy",
            sourceNormalized: "chewy",
            link: URL(string: "https://x")!,
            price: "$1",
            priceCents: 100,
            rating: nil,
            ratingCount: nil,
            productId: "abc",
            position: 1
        )
        XCTAssertEqual(row.id, "Chewy-1-abc")

        let encoded = try makeEncoder().encode(row)
        let decoded = try makeDecoder().decode(MiscMerchantRow.self, from: encoded)
        XCTAssertEqual(decoded.id, row.id)
    }
}
