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
            fbLocationId: "112111905481230",
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
                fbLocationId: "112111905481230",
                radiusMiles: 25
            )
        )
        prefs.save(
            .init(
                latitude: 30.2672,
                longitude: -97.7431,
                displayLabel: "Austin, TX",
                fbLocationId: "112782425413239",
                radiusMiles: 50
            )
        )
        XCTAssertEqual(prefs.current()?.fbLocationId, "112782425413239")
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
                fbLocationId: "112111905481230",
                radiusMiles: 25
            )
        )
        prefs.clear()
        XCTAssertNil(prefs.current())
        XCTAssertNil(defaults.data(forKey: LocationPreferences.storageKey))
    }

    // MARK: - Schema

    func test_storageKeyIsV2() {
        // V1 held the old slug-based schema. Bumping to v2 means old prefs
        // are ignored on read — users re-pick their location once, then
        // never again. Guard against an accidental revert to v1.
        XCTAssertEqual(
            LocationPreferences.storageKey,
            "barkain.fbMarketplaceLocation.v2"
        )
    }

    func test_storedSupportsNilCoordinates() {
        // Coordinates are optional — a user who denies CoreLocation or
        // enters a city manually can still have a resolved FB ID.
        let prefs = LocationPreferences(defaults: makeIsolatedDefaults())
        let stored = LocationPreferences.Stored(
            latitude: nil,
            longitude: nil,
            displayLabel: "Brooklyn, NY",
            fbLocationId: "112111905481230",
            radiusMiles: 25
        )
        prefs.save(stored)
        XCTAssertEqual(prefs.current(), stored)
    }

    // MARK: - Radius options

    func test_radiusOptionsCoverFbMarketplaceStandardValues() {
        XCTAssertEqual(LocationPreferences.radiusOptions, [5, 10, 25, 50, 100])
        XCTAssertEqual(LocationPreferences.defaultRadiusMiles, 25)
    }

    // MARK: - Codable guard

    func test_fbLocationIdEncodesAsString() throws {
        // FB Marketplace Page IDs are bigints; JSONDecoder → Int narrows
        // values above 2^53. Guard the schema by asserting the wire
        // format is a string, not a number.
        let stored = LocationPreferences.Stored(
            latitude: 40.6782,
            longitude: -73.9442,
            displayLabel: "Brooklyn, NY",
            fbLocationId: "112111905481230",
            radiusMiles: 25
        )
        let encoded = try JSONEncoder().encode(stored)
        let json = try JSONSerialization.jsonObject(with: encoded) as? [String: Any]
        XCTAssertEqual(json?["fbLocationId"] as? String, "112111905481230")
    }
}
