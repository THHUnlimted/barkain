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

    // MARK: - Retry on resolver failure (fb-resolver-followups L9)

    /// Seed a `.failed` state via a real failing resolve so the VM
    /// caches `lastResolveTarget`. Then a retry must call the API
    /// again — caller didn't have to re-share location.
    func test_retry_afterResolverFailure_recallsAPI() async {
        let mock = MockAPIClient()
        mock.resolveFbLocationResult = .failure(.network(URLError(.notConnectedToInternet)))
        let (vm, _) = makeVM(mock: mock)

        await vm.resolveFbLocation(city: "Brooklyn", state: "NY", label: "Brooklyn, NY")
        guard case .failed = vm.resolveState else {
            XCTFail("expected .failed after first resolve, got \(vm.resolveState)")
            return
        }
        XCTAssertTrue(vm.canRetry)
        XCTAssertEqual(mock.resolveFbLocationCallCount, 1)

        // Retry succeeds this time.
        mock.resolveFbLocationResult = .success(
            ResolvedFbLocation(
                locationId: "112111905481230",
                canonicalName: "Brooklyn, NY",
                verified: true,
                resolutionPath: "live"
            )
        )
        vm.retry()
        // retry() spawns an async Task; await one MainActor turn so it
        // completes before we assert.
        await Task.yield()
        try? await Task.sleep(nanoseconds: 50_000_000)

        XCTAssertEqual(mock.resolveFbLocationCallCount, 2,
                       "retry must call /fb-location/resolve again")
        if case let .resolved(label, _) = vm.resolveState {
            XCTAssertEqual(label, "Brooklyn, NY")
        } else {
            XCTFail("expected .resolved after successful retry, got \(vm.resolveState)")
        }
        XCTAssertTrue(vm.canSave)
    }

    /// After 3 consecutive failures, the retry button must be hidden
    /// — `canRetry` flips false. Stops the user from looping against
    /// a genuinely unresolvable city.
    func test_retry_disabled_afterThreeConsecutiveFailures() async {
        let mock = MockAPIClient()
        mock.resolveFbLocationResult = .failure(.network(URLError(.notConnectedToInternet)))
        let (vm, _) = makeVM(mock: mock)

        await vm.resolveFbLocation(city: "Ding Dong", state: "TX", label: "Ding Dong, TX")
        XCTAssertTrue(vm.canRetry, "retry available after 1st failure")

        for i in 1...LocationPickerViewModel.maxConsecutiveRetries {
            vm.retry()
            await Task.yield()
            try? await Task.sleep(nanoseconds: 50_000_000)
            if i < LocationPickerViewModel.maxConsecutiveRetries {
                XCTAssertTrue(vm.canRetry, "retry still available after \(i) attempts")
            }
        }

        XCTAssertFalse(vm.canRetry,
                       "retry must be suppressed after maxConsecutiveRetries")
    }

    /// Successful resolve clears the retry budget — a later failure
    /// starts fresh from 0/3.
    func test_retry_counterResetsOnSuccessfulResolve() async {
        let mock = MockAPIClient()
        mock.resolveFbLocationResult = .failure(.network(URLError(.notConnectedToInternet)))
        let (vm, _) = makeVM(mock: mock)

        await vm.resolveFbLocation(city: "Brooklyn", state: "NY", label: "Brooklyn, NY")
        vm.retry()
        await Task.yield()
        try? await Task.sleep(nanoseconds: 50_000_000)
        // Two failures so far.

        // Now succeed.
        mock.resolveFbLocationResult = .success(
            ResolvedFbLocation(
                locationId: "112111905481230",
                canonicalName: "Brooklyn, NY",
                verified: true,
                resolutionPath: "live"
            )
        )
        await vm.resolveFbLocation(city: "Brooklyn", state: "NY", label: "Brooklyn, NY")
        XCTAssertEqual(vm.retryAttemptCount, 0,
                       "successful resolve must reset retry budget")
    }

    // MARK: - Canonical-redirect dismiss banner (fb-resolver-followups L11)

    /// When FB's canonical name differs from the user's label,
    /// `showsCanonicalRedirectAffordance` flips true so the sheet
    /// surfaces the "Don't use this — start over" button.
    func test_showsCanonicalRedirectAffordance_whenCanonicalDiffers() async {
        let mock = MockAPIClient()
        mock.resolveFbLocationResult = .success(
            ResolvedFbLocation(
                locationId: "108271525863730",
                canonicalName: "Killeen, TX",
                verified: true,
                resolutionPath: "live"
            )
        )
        let (vm, _) = makeVM(mock: mock)
        await vm.resolveFbLocation(city: "Ding Dong", state: "TX", label: "Ding Dong, TX")
        XCTAssertTrue(vm.showsCanonicalRedirectAffordance)
    }

    /// When canonical name matches the user's label, no banner
    /// affordance — the redirect flag is silent.
    func test_showsCanonicalRedirectAffordance_falseWhenCanonicalMatches() async {
        let mock = MockAPIClient()
        mock.resolveFbLocationResult = .success(
            ResolvedFbLocation(
                locationId: "112111905481230",
                canonicalName: "Brooklyn, NY",
                verified: true,
                resolutionPath: "live"
            )
        )
        let (vm, _) = makeVM(mock: mock)
        await vm.resolveFbLocation(city: "Brooklyn", state: "NY", label: "Brooklyn, NY")
        XCTAssertFalse(vm.showsCanonicalRedirectAffordance)
    }

    /// Tapping "Don't use this — start over" returns the picker to
    /// idle, drops the resolved id (so canSave goes false), and
    /// resets the retry budget.
    func test_dismissCanonicalRedirect_resetsToIdle() async {
        let mock = MockAPIClient()
        mock.resolveFbLocationResult = .success(
            ResolvedFbLocation(
                locationId: "108271525863730",
                canonicalName: "Killeen, TX",
                verified: true,
                resolutionPath: "live"
            )
        )
        let (vm, _) = makeVM(mock: mock)
        await vm.resolveFbLocation(city: "Ding Dong", state: "TX", label: "Ding Dong, TX")
        XCTAssertTrue(vm.canSave)

        vm.dismissCanonicalRedirect()

        XCTAssertEqual(vm.resolveState, .idle)
        XCTAssertFalse(vm.canSave)
        XCTAssertFalse(vm.showsCanonicalRedirectAffordance)
        XCTAssertEqual(vm.retryAttemptCount, 0)
    }
}
