import Foundation
import os

// MARK: - IdentityCache
//
// In-memory TTL cache for /identity/discounts and /cards/recommendations
// responses. Keyed by productId so a repeat scan/search of the same product
// within the TTL window returns instantly instead of round-tripping the
// backend (~200 ms each, ~400 ms total saved).
//
// Reads are read-through: cache miss falls through to the supplied APIClient,
// writes the response, and returns. Failures are NOT cached — a transient
// backend error doesn't poison subsequent retries.
//
// Invalidation contract:
//   • `invalidateAll()` — call after IdentityProfile is updated. Identity
//     discounts AND card recommendations both depend on user identity state
//     via the M5 join, so both go.
//   • `invalidateCards()` — call after card portfolio mutations. Identity
//     discounts don't depend on the card portfolio.
//
// Portal-membership toggles deliberately do NOT invalidate this cache:
// neither response shape includes portal data (portal stacking lives in M6,
// which is its own Redis-backed cache). Over-invalidating here would just
// burn API budget for no correctness gain.
//
// TTL of 5 minutes amortizes warm across an average iOS session (~3 min)
// while keeping out-of-band staleness inside a typical tab-switch + back-action.

@MainActor
final class IdentityCache {

    // MARK: - Singleton

    /// Production accessor. Tests construct fresh instances directly so
    /// invalidation hooks reaching `.shared` don't cross test boundaries.
    static let shared = IdentityCache()

    // MARK: - Configuration

    static let ttl: TimeInterval = 300

    // MARK: - Storage

    private struct CachedIdentity {
        let response: IdentityDiscountsResponse
        let cachedAt: Date
    }

    private struct CachedCards {
        let response: CardRecommendationsResponse
        let cachedAt: Date
    }

    // Identity is keyed by Optional<UUID> so a future global eligibility warm
    // (productId=nil) shares this cache without colliding with per-product
    // entries. PR-2 will exercise the nil key on app foreground.
    private var identity: [UUID?: CachedIdentity] = [:]
    private var cards: [UUID: CachedCards] = [:]

    private let now: () -> Date
    private let log = Logger(subsystem: "com.barkain.app", category: "IdentityCache")

    // MARK: - Init

    /// `now` is injectable so TTL behavior is deterministically testable
    /// without sleeping. Production defaults to `Date.init`.
    init(now: @escaping () -> Date = Date.init) {
        self.now = now
    }

    // MARK: - Reads

    func fetchIdentity(
        productId: UUID?,
        apiClient: any APIClientProtocol
    ) async throws -> IdentityDiscountsResponse {
        if let entry = identity[productId], !isExpired(entry.cachedAt) {
            return entry.response
        }
        let response = try await apiClient.getEligibleDiscounts(productId: productId)
        identity[productId] = CachedIdentity(response: response, cachedAt: now())
        return response
    }

    func fetchCards(
        productId: UUID,
        apiClient: any APIClientProtocol
    ) async throws -> CardRecommendationsResponse {
        if let entry = cards[productId], !isExpired(entry.cachedAt) {
            return entry.response
        }
        let response = try await apiClient.getCardRecommendations(productId: productId)
        cards[productId] = CachedCards(response: response, cachedAt: now())
        return response
    }

    // MARK: - Invalidation

    func invalidateAll() {
        identity.removeAll()
        cards.removeAll()
        log.info("invalidated all (identity + cards)")
    }

    func invalidateCards() {
        cards.removeAll()
        log.info("invalidated cards")
    }

    // MARK: - Helpers

    private func isExpired(_ cachedAt: Date) -> Bool {
        now().timeIntervalSince(cachedAt) > Self.ttl
    }
}
