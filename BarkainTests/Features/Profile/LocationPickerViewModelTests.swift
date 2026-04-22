import XCTest
@testable import Barkain

// MARK: - LocationPickerViewModelTests

/// Exercises the resolve flow in isolation — CLGeocoder / CLLocationManager
/// can't run in unit tests without a real device location, so we drive
/// `resolveFbLocation` directly through the `MockAPIClient` and verify
/// the state machine transitions + `canSave` gate behave as expected.
@MainActor
final class LocationPickerViewModelTests: XCTestCase {

    // MARK: - Helpers

    private func makeIsolatedDefaults() -> UserDefaults {
        let suite = "test.location_picker_vm.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defaults.removePersistentDomain(forName: suite)
        return defaults
    }

    private func makeVM(
        mock: MockAPIClient,
        existing: LocationPreferences.Stored? = nil
    ) -> (LocationPickerViewModel, LocationPreferences) {
        let prefs = LocationPreferences(defaults: makeIsolatedDefaults())
        if let existing { prefs.save(existing) }
        let vm = LocationPickerViewModel(preferences: prefs, apiClient: mock)
        return (vm, prefs)
    }

    // MARK: - Initial state

    func test_fresh_vm_startsIdle_cannotSave() {
        let (vm, _) = makeVM(mock: MockAPIClient())
        XCTAssertEqual(vm.resolveState, .idle)
        XCTAssertFalse(vm.canSave)
        XCTAssertFalse(vm.hasStoredPreference)
    }

    func test_vm_loadsExistingStoredPreference() {
        let stored = LocationPreferences.Stored(
            latitude: 40.6782,
            longitude: -73.9442,
            displayLabel: "Brooklyn, NY",
            fbLocationId: "112111905481230",
            radiusMiles: 25
        )
        let (vm, _) = makeVM(mock: MockAPIClient(), existing: stored)
        XCTAssertTrue(vm.hasStoredPreference)
        XCTAssertTrue(vm.canSave)
        XCTAssertEqual(vm.radiusMiles, 25)
        // resolved state seeded from stored pref; canonicalName nil because
        // we don't re-resolve on load.
        if case let .resolved(label, canonical) = vm.resolveState {
            XCTAssertEqual(label, "Brooklyn, NY")
            XCTAssertNil(canonical)
        } else {
            XCTFail("expected .resolved, got \(vm.resolveState)")
        }
    }

    // MARK: - Save gating

    func test_save_withoutResolvedId_isNoOp() {
        let (vm, prefs) = makeVM(mock: MockAPIClient())
        vm.save()
        XCTAssertNil(prefs.current())
        XCTAssertFalse(vm.hasStoredPreference)
    }

    func test_save_afterSeededState_persists() {
        let stored = LocationPreferences.Stored(
            latitude: 40.6782,
            longitude: -73.9442,
            displayLabel: "Brooklyn, NY",
            fbLocationId: "112111905481230",
            radiusMiles: 25
        )
        let (vm, prefs) = makeVM(mock: MockAPIClient(), existing: stored)
        // Mutate radius, save.
        vm.radiusMiles = 50
        vm.save()
        XCTAssertEqual(prefs.current()?.radiusMiles, 50)
        XCTAssertEqual(prefs.current()?.fbLocationId, "112111905481230")
    }

    // MARK: - Clear

    func test_clear_resetsEverything() {
        let stored = LocationPreferences.Stored(
            latitude: 40.6782,
            longitude: -73.9442,
            displayLabel: "Brooklyn, NY",
            fbLocationId: "112111905481230",
            radiusMiles: 50
        )
        let (vm, prefs) = makeVM(mock: MockAPIClient(), existing: stored)
        vm.clear()
        XCTAssertNil(prefs.current())
        XCTAssertFalse(vm.hasStoredPreference)
        XCTAssertFalse(vm.canSave)
        XCTAssertEqual(vm.resolveState, .idle)
        XCTAssertEqual(vm.radiusMiles, LocationPreferences.defaultRadiusMiles)
    }
}
