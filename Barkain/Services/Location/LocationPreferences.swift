import Foundation

// MARK: - LocationPreferences

/// Persistent store for the user's Facebook Marketplace location.
///
/// Thin `UserDefaults` wrapper with a Codable payload, no observable state,
/// read on demand by callers. When the user hasn't set a location,
/// `current()` returns `nil` and the backend falls back to the container's
/// baked `FB_MARKETPLACE_LOCATION` env default (typically `sanfrancisco`).
///
/// Not `@MainActor` — `UserDefaults` is thread-safe and the backend-facing
/// callsite (`ScannerViewModel.fetchPrices`) reads this off-main when
/// assembling the stream request. The picker sheet's view model stays on
/// main and talks to the same instance safely.
// `nonisolated` at the class level (matching `APIClient`'s pattern)
// sidesteps the project's default @MainActor isolation. UserDefaults is
// thread-safe so there's no real actor crossing to worry about, and it
// lets SwiftUI view inits (which are nonisolated) use
// `LocationPreferences()` as a default arg without a hop.
nonisolated final class LocationPreferences: @unchecked Sendable {

    // MARK: - Constants

    static let storageKey = "barkain.fbMarketplaceLocation.v1"
    static let radiusOptions: [Int] = [5, 10, 25, 50, 100]
    static let defaultRadiusMiles: Int = 25

    // MARK: - Stored

    struct Stored: Codable, Equatable, Sendable {
        var latitude: Double
        var longitude: Double
        /// Human-readable label for UI ("Brooklyn, NY"). Never sent to the
        /// backend — only the slug + radius are.
        var displayLabel: String
        /// URL-safe slug (lowercased alphanumeric/underscore) used by the
        /// fb_marketplace container to build its search URL.
        var fbLocationSlug: String
        var radiusMiles: Int
    }

    // MARK: - Dependencies

    private let defaults: UserDefaults

    // MARK: - Init

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    // MARK: - API

    func current() -> Stored? {
        guard let data = defaults.data(forKey: Self.storageKey),
              let decoded = try? JSONDecoder().decode(Stored.self, from: data)
        else { return nil }
        return decoded
    }

    func save(_ value: Stored) {
        guard let encoded = try? JSONEncoder().encode(value) else { return }
        defaults.set(encoded, forKey: Self.storageKey)
    }

    func clear() {
        defaults.removeObject(forKey: Self.storageKey)
    }

    // MARK: - Helpers

    /// Convert a CLGeocoder locality ("Brooklyn", "San Francisco", "St. Louis")
    /// into the [a-z0-9_] slug shape Facebook Marketplace URLs expect. FB's
    /// real slugs aren't strictly normalized ("newyork" not "new_york"), but
    /// lowercase + strip non-alphanumeric matches the vast majority of US
    /// cities. The sheet lets the user edit the slug if auto-derivation is
    /// wrong for their city.
    static func slugify(_ locality: String) -> String {
        let lower = locality.lowercased()
        return lower.unicodeScalars
            .filter { CharacterSet.alphanumerics.contains($0) }
            .map(String.init)
            .joined()
    }
}
