import Foundation

// MARK: - LocationPreferences

/// Persistent store for the user's Facebook Marketplace location.
///
/// Thin `UserDefaults` wrapper with a Codable payload, no observable state,
/// read on demand by callers. When the user hasn't set a location,
/// `current()` returns `nil` and the backend falls back to the container's
/// baked `FB_MARKETPLACE_LOCATION` env default (typically `sanfrancisco`).
///
/// The stored value now carries FB's **numeric** Marketplace location ID
/// — resolved once via `POST /api/v1/fb-location/resolve` when the user
/// picks a city — instead of the slug shape we used to send. Numeric IDs
/// are unambiguous (`112111905481230` is Brooklyn and nothing else) and
/// stable; FB's slug dictionary is short and mostly undocumented, which
/// is how we ended up with NY-marked users seeing California listings.
/// See `docs/CHANGELOG.md` (fb-marketplace-location-resolver) for the
/// full rationale.
///
/// Not `@MainActor` — `UserDefaults` is thread-safe and the backend-facing
/// callsite (`ScannerViewModel.fetchPrices`) reads this off-main when
/// assembling the stream request. The picker sheet's view model stays on
/// main and talks to the same instance safely.
///
/// `nonisolated` at the class level (matching `APIClient`'s pattern)
/// sidesteps the project's default `@MainActor` isolation. `UserDefaults`
/// is thread-safe so there's no real actor crossing to worry about, and
/// it lets SwiftUI view inits (which are nonisolated) use
/// `LocationPreferences()` as a default arg without a hop.
nonisolated final class LocationPreferences: @unchecked Sendable {

    // MARK: - Constants

    /// Version bumped from v1 → v2 when the slug schema was retired.
    /// Old v1 values stay on disk under the old key but are never read —
    /// effectively a silent migration: the user will be prompted to
    /// re-pick their location the next time the picker opens.
    static let storageKey = "barkain.fbMarketplaceLocation.v2"
    static let radiusOptions: [Int] = [5, 10, 25, 50, 100]
    static let defaultRadiusMiles: Int = 25

    // MARK: - Stored

    struct Stored: Codable, Equatable, Sendable {
        /// Optional so a user who denies CoreLocation permission can still
        /// save a location by typing city/state (picker would need a UI
        /// for that; currently auto-only). The backend never reads these
        /// — only `fbLocationId` + `radiusMiles` travel over the wire.
        var latitude: Double?
        var longitude: Double?
        /// Human-readable label shown in the Profile row ("Brooklyn, NY").
        /// Can be FB's canonical name (if the resolver found one) or the
        /// user's original input — whichever is more accurate.
        var displayLabel: String
        /// Numeric FB Marketplace Page ID as a string. Stored as `String`
        /// rather than `Int64` to avoid JSON → `Int` round-trip narrowing
        /// for IDs above 2^53; we only ever concatenate into URLs anyway.
        var fbLocationId: String
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
}
