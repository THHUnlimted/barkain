import Foundation

// MARK: - RecentSearches

/// Thin storage wrapper around `UserDefaults` for the user's most recent
/// search terms. Source of truth for persistence; the SearchViewModel
/// keeps an observable mirror so SwiftUI views can re-render on changes.
@MainActor
final class RecentSearches {

    // MARK: - Constants

    static let storageKey = "barkain.recentSearches"
    static let legacyStorageKey = "recentSearches"
    static let maxEntries = 10

    // MARK: - Stored

    private let defaults: UserDefaults

    // MARK: - Init

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        migrateLegacyKeyIfPresent()
    }

    // MARK: - API

    /// Returns the persisted list, newest first.
    func all() -> [String] {
        guard let data = defaults.data(forKey: Self.storageKey),
              let decoded = try? JSONDecoder().decode([String].self, from: data)
        else {
            return []
        }
        return decoded
    }

    /// Trims, dedupes (case-insensitive), prepends the term, caps at
    /// `maxEntries`, persists. No-op on empty trimmed input.
    @discardableResult
    func add(_ term: String) -> [String] {
        let trimmed = term.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return all() }
        var existing = all().filter { $0.lowercased() != trimmed.lowercased() }
        existing.insert(trimmed, at: 0)
        if existing.count > Self.maxEntries {
            existing = Array(existing.prefix(Self.maxEntries))
        }
        persist(existing)
        return existing
    }

    func clear() {
        defaults.removeObject(forKey: Self.storageKey)
    }

    // MARK: - Private

    private func persist(_ terms: [String]) {
        if let encoded = try? JSONEncoder().encode(terms) {
            defaults.set(encoded, forKey: Self.storageKey)
        }
    }

    /// One-time copy of the pre-3d UserDefaults key (`recentSearches`)
    /// into the new namespaced key. The legacy key is removed afterwards
    /// so we don't permanently maintain two stores.
    private func migrateLegacyKeyIfPresent() {
        guard defaults.data(forKey: Self.storageKey) == nil,
              let legacy = defaults.data(forKey: Self.legacyStorageKey)
        else { return }
        defaults.set(legacy, forKey: Self.storageKey)
        defaults.removeObject(forKey: Self.legacyStorageKey)
    }
}
