import XCTest
@testable import Barkain

// MARK: - LocationPreferencesTests

@MainActor
final class LocationPreferencesTests: XCTestCase {

    // MARK: - Helpers

    private func makeIsolatedDefaults() -> UserDefaults {
        let suite = "test.location.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defaults.removePersistentDomain(forName: suite)
        return defaults
    }

    // MARK: - Round-trip

    func test_currentReturnsNilWhenEmpty() {
        let prefs = LocationPreferences(defaults: makeIsolatedDefaults())
        XCTAssertNil(prefs.current())
    }

    func test_saveThenCurrentRoundTrips() {
        let defaults = makeIsolatedDefaults()
        let prefs = LocationPreferences(defaults: defaults)

        let stored = LocationPreferences.Stored(
            latitude: 40.6782,
            longitude: -73.9442,
            displayLabel: "Brooklyn, NY",
            fbLocationSlug: "brooklyn",
            radiusMiles: 25
        )
        prefs.save(stored)

        let loaded = prefs.current()
        XCTAssertEqual(loaded, stored)
    }

    func test_saveOverwritesPreviousValue() {
        let prefs = LocationPreferences(defaults: makeIsolatedDefaults())
        prefs.save(
            .init(
                latitude: 40.6782,
                longitude: -73.9442,
                displayLabel: "Brooklyn, NY",
                fbLocationSlug: "brooklyn",
                radiusMiles: 25
            )
        )
        prefs.save(
            .init(
                latitude: 30.2672,
                longitude: -97.7431,
                displayLabel: "Austin, TX",
                fbLocationSlug: "austin",
                radiusMiles: 50
            )
        )
        XCTAssertEqual(prefs.current()?.fbLocationSlug, "austin")
        XCTAssertEqual(prefs.current()?.radiusMiles, 50)
    }

    func test_clearRemovesStoredValue() {
        let defaults = makeIsolatedDefaults()
        let prefs = LocationPreferences(defaults: defaults)
        prefs.save(
            .init(
                latitude: 40.6782,
                longitude: -73.9442,
                displayLabel: "Brooklyn, NY",
                fbLocationSlug: "brooklyn",
                radiusMiles: 25
            )
        )
        prefs.clear()
        XCTAssertNil(prefs.current())
        XCTAssertNil(defaults.data(forKey: LocationPreferences.storageKey))
    }

    // MARK: - Slugify

    func test_slugifyLowercasesAndStripsNonAlphanumeric() {
        XCTAssertEqual(LocationPreferences.slugify("Brooklyn"), "brooklyn")
        XCTAssertEqual(LocationPreferences.slugify("San Francisco"), "sanfrancisco")
        XCTAssertEqual(LocationPreferences.slugify("St. Louis"), "stlouis")
        XCTAssertEqual(LocationPreferences.slugify("New York City"), "newyorkcity")
    }

    func test_slugifyReturnsEmptyForPunctuationOnly() {
        XCTAssertEqual(LocationPreferences.slugify("-..."), "")
    }

    // MARK: - Radius options

    func test_radiusOptionsCoverFbMarketplaceStandardValues() {
        XCTAssertEqual(LocationPreferences.radiusOptions, [5, 10, 25, 50, 100])
        XCTAssertEqual(LocationPreferences.defaultRadiusMiles, 25)
    }
}
