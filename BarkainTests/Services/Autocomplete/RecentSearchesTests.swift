import XCTest
@testable import Barkain

@MainActor
final class RecentSearchesTests: XCTestCase {

    private func makeIsolatedDefaults() -> UserDefaults {
        let suite = "test.recents.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defaults.removePersistentDomain(forName: suite)
        return defaults
    }

    // MARK: - Add / dedup / cap

    func test_add_prependsAndDedupes() {
        let recents = RecentSearches(defaults: makeIsolatedDefaults())
        recents.add("iPhone 17 Pro")
        recents.add("Sony WH-1000XM5")
        let after = recents.add("iphone 17 pro") // case-insensitive dup
        XCTAssertEqual(after, ["iphone 17 pro", "Sony WH-1000XM5"])
    }

    func test_add_capsAtTen() {
        let recents = RecentSearches(defaults: makeIsolatedDefaults())
        for i in 0..<12 {
            recents.add("query_\(i)")
        }
        let all = recents.all()
        XCTAssertEqual(all.count, 10)
        XCTAssertEqual(all.first, "query_11")
        XCTAssertFalse(all.contains("query_0"))
        XCTAssertFalse(all.contains("query_1"))
    }

    func test_add_ignoresWhitespaceOnly() {
        let recents = RecentSearches(defaults: makeIsolatedDefaults())
        recents.add("   ")
        XCTAssertTrue(recents.all().isEmpty)
    }

    func test_clear_emptiesStorage() {
        let defaults = makeIsolatedDefaults()
        let recents = RecentSearches(defaults: defaults)
        recents.add("iPhone 17")
        recents.clear()
        XCTAssertTrue(recents.all().isEmpty)
        XCTAssertNil(defaults.data(forKey: RecentSearches.storageKey))
    }

    // MARK: - Persistence across instances

    func test_persistsAcrossInstancesOnSameDefaults() {
        let defaults = makeIsolatedDefaults()
        let first = RecentSearches(defaults: defaults)
        first.add("iPhone 17 Pro")
        first.add("AirPods Pro 2")
        let second = RecentSearches(defaults: defaults)
        XCTAssertEqual(second.all(), ["AirPods Pro 2", "iPhone 17 Pro"])
    }

    // MARK: - Legacy key migration (Step 3a → 3d)

    func test_migratesLegacyRecentSearchesKey_onFirstInstantiation() throws {
        let defaults = makeIsolatedDefaults()
        let legacyData = try JSONEncoder().encode(["Sony WH-1000XM5", "iPhone 17"])
        defaults.set(legacyData, forKey: RecentSearches.legacyStorageKey)

        let recents = RecentSearches(defaults: defaults)

        XCTAssertEqual(recents.all(), ["Sony WH-1000XM5", "iPhone 17"])
        // Legacy key removed after migration.
        XCTAssertNil(defaults.data(forKey: RecentSearches.legacyStorageKey))
    }

    func test_doesNotMigrate_whenNewKeyAlreadyPopulated() throws {
        let defaults = makeIsolatedDefaults()
        let newData = try JSONEncoder().encode(["AirPods Pro 2"])
        let legacyData = try JSONEncoder().encode(["Stale Term"])
        defaults.set(newData, forKey: RecentSearches.storageKey)
        defaults.set(legacyData, forKey: RecentSearches.legacyStorageKey)

        let recents = RecentSearches(defaults: defaults)

        XCTAssertEqual(recents.all(), ["AirPods Pro 2"])
    }
}
