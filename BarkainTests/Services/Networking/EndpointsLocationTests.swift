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

    // MARK: - Tests

    func test_streamPrices_noLocation_emitsNoLocationParams() {
        let endpoint = Endpoint.streamPrices(productId: UUID())
        let items = queryItems(for: endpoint)
        XCTAssertFalse(items.contains { $0.name == "fb_location_slug" })
        XCTAssertFalse(items.contains { $0.name == "fb_radius_miles" })
    }

    func test_streamPrices_withLocation_emitsBothParams() {
        let endpoint = Endpoint.streamPrices(
            productId: UUID(),
            fbLocationSlug: "brooklyn",
            fbRadiusMiles: 25
        )
        let items = queryItems(for: endpoint)
        XCTAssertEqual(items.first { $0.name == "fb_location_slug" }?.value, "brooklyn")
        XCTAssertEqual(items.first { $0.name == "fb_radius_miles" }?.value, "25")
    }

    func test_streamPrices_slugOnly_emitsSlugParamNotRadius() {
        // The picker sheet's save gate forces radius when slug is set, but
        // we still verify the builder tolerates a partial override rather
        // than dropping the slug silently.
        let endpoint = Endpoint.streamPrices(
            productId: UUID(),
            fbLocationSlug: "austin"
        )
        let items = queryItems(for: endpoint)
        XCTAssertEqual(items.first { $0.name == "fb_location_slug" }?.value, "austin")
        XCTAssertNil(items.first { $0.name == "fb_radius_miles" })
    }

    func test_streamPrices_emptySlug_dropsTheParam() {
        let endpoint = Endpoint.streamPrices(
            productId: UUID(),
            fbLocationSlug: "",
            fbRadiusMiles: 25
        )
        let items = queryItems(for: endpoint)
        XCTAssertNil(items.first { $0.name == "fb_location_slug" })
        // Radius alone is allowed — backend ignores it without a slug, but
        // we'd rather leave the param shape honest than strip it.
        XCTAssertEqual(items.first { $0.name == "fb_radius_miles" }?.value, "25")
    }

    func test_streamPrices_coexistsWithForceRefreshAndOverride() {
        let endpoint = Endpoint.streamPrices(
            productId: UUID(),
            forceRefresh: true,
            queryOverride: "Steam Deck OLED",
            fbLocationSlug: "brooklyn",
            fbRadiusMiles: 10
        )
        let items = queryItems(for: endpoint)
        let names = Set(items.map { $0.name })
        XCTAssertEqual(
            names,
            ["force_refresh", "query", "fb_location_slug", "fb_radius_miles"]
        )
    }
}
