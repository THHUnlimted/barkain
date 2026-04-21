import Foundation

// MARK: - RecentlyScannedProduct
//
// Compact snapshot of a product the user resolved via Scanner or Search.
// Stored in UserDefaults so the Home tab can show a "Recently Scanned"
// rail without a new backend call. All fields mirror `Product` so tapping
// a rail item can rehydrate into the Scan flow without a round-trip.

nonisolated struct RecentlyScannedProduct: Codable, Identifiable, Equatable, Sendable {
    let id: UUID
    let upc: String?
    let name: String
    let brand: String?
    let imageUrl: String?
    let scannedAt: Date
}

// MARK: - RecentlyScannedStore
//
// Observable UserDefaults-backed store. Pattern matches `RecentSearches`
// (cap at 12, newest-first, case-insensitive dedup on product id).
//
// Written to from:
//   - ScannerViewModel on successful UPC resolve
//   - SearchViewModel on search-result resolve
//
// Read by HomeView.

@MainActor
@Observable
final class RecentlyScannedStore {

    // MARK: - Constants

    static let storageKey = "barkain.recentlyScanned"
    static let maxEntries = 12

    // MARK: - State

    private(set) var items: [RecentlyScannedProduct] = []

    // MARK: - Stored

    private let defaults: UserDefaults

    // MARK: - Init

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        self.items = loadFromDisk()
    }

    // MARK: - API

    /// Upserts the product — existing entry with the same id is moved to
    /// the front, otherwise prepended. Caps at `maxEntries`, persists.
    func record(id: UUID, upc: String?, name: String, brand: String?, imageUrl: String?) {
        let trimmedName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedName.isEmpty else { return }

        let entry = RecentlyScannedProduct(
            id: id,
            upc: upc,
            name: trimmedName,
            brand: brand,
            imageUrl: imageUrl,
            scannedAt: Date()
        )

        var next = items.filter { $0.id != id }
        next.insert(entry, at: 0)
        if next.count > Self.maxEntries {
            next = Array(next.prefix(Self.maxEntries))
        }
        items = next
        persist(next)
    }

    func clear() {
        items = []
        defaults.removeObject(forKey: Self.storageKey)
    }

    // MARK: - Persistence

    private func loadFromDisk() -> [RecentlyScannedProduct] {
        guard let data = defaults.data(forKey: Self.storageKey),
              let decoded = try? JSONDecoder().decode([RecentlyScannedProduct].self, from: data)
        else {
            return []
        }
        return decoded
    }

    private func persist(_ entries: [RecentlyScannedProduct]) {
        if let encoded = try? JSONEncoder().encode(entries) {
            defaults.set(encoded, forKey: Self.storageKey)
        }
    }
}
