import XCTest
@testable import Barkain

@MainActor
final class IdentityCacheTests: XCTestCase {

    // MARK: - Identity reads

    func test_identityCacheHitReturnsResponseWithoutSecondCall() async throws {
        let cache = IdentityCache()
        let mock = MockAPIClient()
        let productId = UUID()

        _ = try await cache.fetchIdentity(productId: productId, apiClient: mock)
        _ = try await cache.fetchIdentity(productId: productId, apiClient: mock)

        XCTAssertEqual(mock.getEligibleDiscountsCallCount, 1)
    }

    func test_identityCacheKeyedByProductIdIncludingNil() async throws {
        let cache = IdentityCache()
        let mock = MockAPIClient()
        let pid1 = UUID()
        let pid2 = UUID()

        _ = try await cache.fetchIdentity(productId: pid1, apiClient: mock)
        _ = try await cache.fetchIdentity(productId: pid2, apiClient: mock)
        _ = try await cache.fetchIdentity(productId: nil, apiClient: mock)

        // Re-fetch all three: each should hit the cache.
        _ = try await cache.fetchIdentity(productId: pid1, apiClient: mock)
        _ = try await cache.fetchIdentity(productId: pid2, apiClient: mock)
        _ = try await cache.fetchIdentity(productId: nil, apiClient: mock)

        XCTAssertEqual(mock.getEligibleDiscountsCallCount, 3)
    }

    func test_identityFailureIsNotCached() async throws {
        let cache = IdentityCache()
        let mock = MockAPIClient()
        let productId = UUID()
        mock.getEligibleDiscountsResult = .failure(.unknown(500, "boom"))

        do {
            _ = try await cache.fetchIdentity(productId: productId, apiClient: mock)
            XCTFail("Expected first fetch to throw")
        } catch {
            // Expected.
        }

        // Recover: next call should fire HTTP again, not return a cached failure.
        mock.getEligibleDiscountsResult = .success(TestFixtures.emptyIdentityDiscounts)
        _ = try await cache.fetchIdentity(productId: productId, apiClient: mock)

        XCTAssertEqual(mock.getEligibleDiscountsCallCount, 2)
    }

    // MARK: - Cards reads

    func test_cardsCacheHitReturnsResponseWithoutSecondCall() async throws {
        let cache = IdentityCache()
        let mock = MockAPIClient()
        let productId = UUID()

        _ = try await cache.fetchCards(productId: productId, apiClient: mock)
        _ = try await cache.fetchCards(productId: productId, apiClient: mock)

        XCTAssertEqual(mock.getCardRecommendationsCallCount, 1)
    }

    func test_cardsFailureIsNotCached() async throws {
        let cache = IdentityCache()
        let mock = MockAPIClient()
        let productId = UUID()
        mock.getCardRecommendationsResult = .failure(.unknown(500, "boom"))

        do {
            _ = try await cache.fetchCards(productId: productId, apiClient: mock)
            XCTFail("Expected first fetch to throw")
        } catch {
            // Expected.
        }

        mock.getCardRecommendationsResult = .success(TestFixtures.emptyCardRecommendations)
        _ = try await cache.fetchCards(productId: productId, apiClient: mock)

        XCTAssertEqual(mock.getCardRecommendationsCallCount, 2)
    }

    // MARK: - TTL

    func test_identityRefreshesAfterTTLExpiry() async throws {
        var fakeNow = Date(timeIntervalSince1970: 1_000_000)
        let cache = IdentityCache(now: { fakeNow })
        let mock = MockAPIClient()
        let pid = UUID()

        _ = try await cache.fetchIdentity(productId: pid, apiClient: mock)

        fakeNow = fakeNow.addingTimeInterval(IdentityCache.ttl + 1)
        _ = try await cache.fetchIdentity(productId: pid, apiClient: mock)

        XCTAssertEqual(mock.getEligibleDiscountsCallCount, 2)
    }

    func test_cardsRefreshAfterTTLExpiry() async throws {
        var fakeNow = Date(timeIntervalSince1970: 1_000_000)
        let cache = IdentityCache(now: { fakeNow })
        let mock = MockAPIClient()
        let pid = UUID()

        _ = try await cache.fetchCards(productId: pid, apiClient: mock)

        fakeNow = fakeNow.addingTimeInterval(IdentityCache.ttl + 1)
        _ = try await cache.fetchCards(productId: pid, apiClient: mock)

        XCTAssertEqual(mock.getCardRecommendationsCallCount, 2)
    }

    func test_identityStaysCachedJustBeforeTTLEdge() async throws {
        var fakeNow = Date(timeIntervalSince1970: 1_000_000)
        let cache = IdentityCache(now: { fakeNow })
        let mock = MockAPIClient()
        let pid = UUID()

        _ = try await cache.fetchIdentity(productId: pid, apiClient: mock)

        fakeNow = fakeNow.addingTimeInterval(IdentityCache.ttl - 1)
        _ = try await cache.fetchIdentity(productId: pid, apiClient: mock)

        XCTAssertEqual(mock.getEligibleDiscountsCallCount, 1)
    }

    // MARK: - Invalidation

    func test_invalidateAllClearsBothCaches() async throws {
        let cache = IdentityCache()
        let mock = MockAPIClient()
        let pid = UUID()

        _ = try await cache.fetchIdentity(productId: pid, apiClient: mock)
        _ = try await cache.fetchCards(productId: pid, apiClient: mock)

        cache.invalidateAll()

        _ = try await cache.fetchIdentity(productId: pid, apiClient: mock)
        _ = try await cache.fetchCards(productId: pid, apiClient: mock)

        XCTAssertEqual(mock.getEligibleDiscountsCallCount, 2)
        XCTAssertEqual(mock.getCardRecommendationsCallCount, 2)
    }

    func test_invalidateCardsLeavesIdentityIntact() async throws {
        let cache = IdentityCache()
        let mock = MockAPIClient()
        let pid = UUID()

        _ = try await cache.fetchIdentity(productId: pid, apiClient: mock)
        _ = try await cache.fetchCards(productId: pid, apiClient: mock)

        cache.invalidateCards()

        _ = try await cache.fetchIdentity(productId: pid, apiClient: mock)
        _ = try await cache.fetchCards(productId: pid, apiClient: mock)

        XCTAssertEqual(mock.getEligibleDiscountsCallCount, 1)
        XCTAssertEqual(mock.getCardRecommendationsCallCount, 2)
    }

    func test_invalidateAllClearsAllProductIdEntriesIncludingNil() async throws {
        let cache = IdentityCache()
        let mock = MockAPIClient()
        let pid1 = UUID()
        let pid2 = UUID()

        _ = try await cache.fetchIdentity(productId: pid1, apiClient: mock)
        _ = try await cache.fetchIdentity(productId: pid2, apiClient: mock)
        _ = try await cache.fetchIdentity(productId: nil, apiClient: mock)

        cache.invalidateAll()

        _ = try await cache.fetchIdentity(productId: pid1, apiClient: mock)
        _ = try await cache.fetchIdentity(productId: pid2, apiClient: mock)
        _ = try await cache.fetchIdentity(productId: nil, apiClient: mock)

        XCTAssertEqual(mock.getEligibleDiscountsCallCount, 6)
    }
}
