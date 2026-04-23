import Foundation

// MARK: - PortalMembershipPreferences (Step 3g-B)
//
// Persistent store for the user's self-reported portal memberships.
// Mirrors `LocationPreferences`: thin `UserDefaults` wrapper with a
// Codable payload, no observable state, read on demand by callers.
//
// The dict travels into `RecommendationRequest.user_memberships` so the
// backend's M6 cache key includes a hash of the active set — toggling
// "I'm a Rakuten member" busts stale recommendations on the next call
// rather than waiting for the 15-min TTL. Falsy entries are dropped
// before hashing on the backend, so {"rakuten": false} hashes the same
// as {} (toggling off and back on doesn't double-bust).
//
// Three known portals (rakuten / topcashback / befrugal) — schema is
// open-ended `[String: Bool]` so a future portal addition doesn't
// require a storage migration.
//
// `nonisolated` at the class level matches `LocationPreferences` and
// `APIClient`, sidestepping the project's default `@MainActor` isolation
// so SwiftUI view inits and the off-main `ScannerViewModel.fetchPrices`
// call site can both use the same instance without an actor hop.

nonisolated final class PortalMembershipPreferences: @unchecked Sendable {

    // MARK: - Constants

    /// v1 key — open-ended dict means future portals don't require a
    /// schema bump. If we ever need to migrate the value shape, follow
    /// the LocationPreferences v1→v2 silent-clear pattern.
    static let storageKey = "barkain.portalMemberships.v1"

    /// Portals the iOS Profile UI surfaces toggles for. Order = render
    /// order; backend accepts any portal_source the user opts into.
    static let knownPortals: [String] = ["rakuten", "topcashback", "befrugal"]

    static let displayNames: [String: String] = [
        "rakuten": "Rakuten",
        "topcashback": "TopCashback",
        "befrugal": "BeFrugal",
    ]

    // MARK: - Dependencies

    private let defaults: UserDefaults

    // MARK: - Init

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    // MARK: - API

    /// Returns the full membership map. Missing keys default to false.
    func current() -> [String: Bool] {
        guard let data = defaults.data(forKey: Self.storageKey),
              let decoded = try? JSONDecoder().decode([String: Bool].self, from: data)
        else { return [:] }
        return decoded
    }

    /// True if the user has marked themselves a member of `portal`.
    func isMember(_ portal: String) -> Bool {
        current()[portal] == true
    }

    /// Toggle membership for one portal. Other portals' state is preserved.
    func setMember(_ portal: String, isMember: Bool) {
        var dict = current()
        dict[portal] = isMember
        guard let encoded = try? JSONEncoder().encode(dict) else { return }
        defaults.set(encoded, forKey: Self.storageKey)
    }

    func clear() {
        defaults.removeObject(forKey: Self.storageKey)
    }
}
