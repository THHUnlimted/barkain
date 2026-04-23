import XCTest
@testable import Barkain

// MARK: - EndpointsLocationTests

/// Coverage for the fb-marketplace-location query-param builders on
/// `Endpoint.streamPrices`. The URL layer is the last place iOS can get
/// this wrong — if the params aren't emitted, the backend silently falls
/// back to the env-default `sanfrancisco` bucket.
final class EndpointsLocationTests: XCTestCase {

    // MARK: - Helpers

    private let baseURL = URL(string: "http://127.0.0.1:8000")!

    private func queryItems(for endpoint: Endpoint) -> [URLQueryItem] {
        let url = endpoint.url(base: baseURL)
        return URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
    }

    // MARK: - streamPrices params

    func test_streamPrices_noLocation_emitsNoLocationParams() {
        let endpoint = Endpoint.streamPrices(productId: UUID())
        let items = queryItems(for: endpoint)
        XCTAssertFalse(items.contains { $0.name == "fb_location_id" })
        XCTAssertFalse(items.contains { $0.name == "fb_radius_miles" })
    }

    func test_streamPrices_withLocation_emitsBothParams() {
        let endpoint = Endpoint.streamPrices(
            productId: UUID(),
            fbLocationId: "112111905481230",
            fbRadiusMiles: 25
        )
        let items = queryItems(for: endpoint)
        XCTAssertEqual(items.first { $0.name == "fb_location_id" }?.value, "112111905481230")
        XCTAssertEqual(items.first { $0.name == "fb_radius_miles" }?.value, "25")
    }

    func test_streamPrices_idOnly_emitsIdParamNotRadius() {
        // The picker sheet's save gate forces radius when id is set, but
        // we still verify the builder tolerates a partial override rather
        // than dropping the id silently.
        let endpoint = Endpoint.streamPrices(
            productId: UUID(),
            fbLocationId: "112782425413239"
        )
        let items = queryItems(for: endpoint)
        XCTAssertEqual(items.first { $0.name == "fb_location_id" }?.value, "112782425413239")
        XCTAssertNil(items.first { $0.name == "fb_radius_miles" })
    }

    func test_streamPrices_emptyId_dropsTheParam() {
        let endpoint = Endpoint.streamPrices(
            productId: UUID(),
            fbLocationId: "",
            fbRadiusMiles: 25
        )
        let items = queryItems(for: endpoint)
        XCTAssertNil(items.first { $0.name == "fb_location_id" })
        // Radius alone is allowed — backend ignores it without an id, but
        // we'd rather leave the param shape honest than strip it.
        XCTAssertEqual(items.first { $0.name == "fb_radius_miles" }?.value, "25")
    }

    func test_streamPrices_preservesLargeBigintIds() {
        // FB Page IDs are bigints — guarantee the param value round-trips
        // verbatim without a narrowing numeric cast somewhere along the
        // path. Picked a value > 2^53.
        let largeId = "112111905481230123"
        let endpoint = Endpoint.streamPrices(
            productId: UUID(),
            fbLocationId: largeId
        )
        let items = queryItems(for: endpoint)
        XCTAssertEqual(items.first { $0.name == "fb_location_id" }?.value, largeId)
    }

    func test_streamPrices_coexistsWithForceRefreshAndOverride() {
        let endpoint = Endpoint.streamPrices(
            productId: UUID(),
            forceRefresh: true,
            queryOverride: "Steam Deck OLED",
            fbLocationId: "112111905481230",
            fbRadiusMiles: 10
        )
        let items = queryItems(for: endpoint)
        let names = Set(items.map { $0.name })
        XCTAssertEqual(
            names,
            ["force_refresh", "query", "fb_location_id", "fb_radius_miles"]
        )
    }

    // MARK: - resolveFbLocation path + body

    func test_resolveFbLocation_pathAndMethod() {
        let endpoint = Endpoint.resolveFbLocation(
            ResolveFbLocationRequest(city: "Brooklyn", state: "NY")
        )
        XCTAssertEqual(endpoint.method, .post)
        let url = endpoint.url(base: baseURL)
        XCTAssertTrue(url.absoluteString.hasSuffix("/api/v1/fb-location/resolve"))
    }

    func test_resolveFbLocation_bodyUsesSnakeCase() throws {
        let endpoint = Endpoint.resolveFbLocation(
            ResolveFbLocationRequest(city: "Brooklyn", state: "NY")
        )
        let body = try XCTUnwrap(endpoint.body)
        let json = try XCTUnwrap(
            JSONSerialization.jsonObject(with: body) as? [String: Any]
        )
        XCTAssertEqual(json["city"] as? String, "Brooklyn")
        XCTAssertEqual(json["state"] as? String, "NY")
        XCTAssertEqual(json["country"] as? String, "US")
    }

    // MARK: - ResolvedFbLocation decoding (L13 rename)

    /// Wire format renamed `source` → `resolution_path` in
    /// fb-resolver-followups. Pin the snake-case decode so a future
    /// JSONDecoder swap can't silently break the field.
    func test_resolvedFbLocation_decodesResolutionPathFromSnakeCase() throws {
        let json = """
        {
          "location_id": "112111905481230",
          "canonical_name": "Brooklyn, NY",
          "verified": true,
          "resolution_path": "live"
        }
        """.data(using: .utf8)!
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let resolved = try decoder.decode(ResolvedFbLocation.self, from: json)
        XCTAssertEqual(resolved.locationId, "112111905481230")
        XCTAssertEqual(resolved.canonicalName, "Brooklyn, NY")
        XCTAssertTrue(resolved.verified)
        XCTAssertEqual(resolved.resolutionPath, "live")
    }
}
