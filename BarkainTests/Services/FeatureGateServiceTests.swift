import XCTest
@testable import Barkain

// MARK: - FeatureGateServiceTests
//
// 8 tests covering the free-tier scan limit, daily rollover, and feature
// access decisions. Uses the test seam `init(proTierProvider:defaults:clock:)`
// to bypass `SubscriptionService` and `RevenueCat` entirely — tests don't
// link any real billing SDK.
//
// Each test gets a fresh, isolated `UserDefaults` suite so writes don't
// leak across the suite.

@MainActor
final class FeatureGateServiceTests: XCTestCase {

    // MARK: - Helpers

    private func makeDefaults(_ id: String = UUID().uuidString) -> UserDefaults {
        let defaults = UserDefaults(suiteName: "test.feature_gate.\(id)")!
        defaults.removePersistentDomain(forName: "test.feature_gate.\(id)")
        return defaults
    }

    private func makeGate(
        isPro: Bool = false,
        defaults: UserDefaults? = nil,
        clock: @escaping () -> Date = Date.init
    ) -> FeatureGateService {
        FeatureGateService(
            proTierProvider: { isPro },
            defaults: defaults ?? makeDefaults(),
            clock: clock
        )
    }

    // MARK: - Tests

    func test_free_user_hits_scan_limit_at_10() {
        let gate = makeGate(isPro: false)

        for i in 0..<FeatureGateService.freeDailyScanLimit {
            XCTAssertFalse(gate.scanLimitReached, "limit reached too early at scan \(i)")
            gate.recordScan()
        }

        XCTAssertTrue(gate.scanLimitReached)
        XCTAssertEqual(gate.dailyScanCount, FeatureGateService.freeDailyScanLimit)
    }

    func test_pro_user_never_hits_scan_limit() {
        let gate = makeGate(isPro: true)

        for _ in 0..<100 {
            gate.recordScan()
        }

        XCTAssertFalse(gate.scanLimitReached)
        XCTAssertNil(gate.remainingScans, "pro user should report nil (unlimited)")
    }

    func test_scan_count_resets_on_new_day() {
        // Use a mutable clock closure so we can advance time between scans.
        var now = Date()
        let gate = makeGate(isPro: false, defaults: makeDefaults(), clock: { now })

        for _ in 0..<5 {
            gate.recordScan()
        }
        XCTAssertEqual(gate.dailyScanCount, 5)

        // Advance the clock by 25 hours — definitely a new local day.
        now = now.addingTimeInterval(25 * 60 * 60)

        // Reading scanLimitReached triggers rollover.
        _ = gate.scanLimitReached
        XCTAssertEqual(gate.dailyScanCount, 0, "count should reset on new day")
        XCTAssertEqual(gate.remainingScans, FeatureGateService.freeDailyScanLimit)
    }

    func test_canAccess_fullIdentityDiscounts_false_for_free() {
        let gate = makeGate(isPro: false)
        XCTAssertFalse(gate.canAccess(.fullIdentityDiscounts))
    }

    func test_canAccess_cardRecommendations_false_for_free() {
        let gate = makeGate(isPro: false)
        XCTAssertFalse(gate.canAccess(.cardRecommendations))
    }

    func test_canAccess_all_features_true_for_pro() {
        let gate = makeGate(isPro: true)
        for feature in ProFeature.allCases {
            XCTAssertTrue(gate.canAccess(feature), "pro should access \(feature)")
        }
    }

    func test_remainingScans_nil_for_pro() {
        let gate = makeGate(isPro: true)
        XCTAssertNil(gate.remainingScans)
    }

    func test_hydrate_restores_persisted_count() {
        // Two services pointed at the same UserDefaults suite — write with
        // the first, read back with a fresh one to verify hydration.
        let defaults = makeDefaults()
        let dateKey: () -> String = {
            let formatter = DateFormatter()
            formatter.calendar = Calendar(identifier: .gregorian)
            formatter.timeZone = .current
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.dateFormat = "yyyy-MM-dd"
            return formatter.string(from: Date())
        }
        defaults.set(7, forKey: "barkain.featureGate.dailyScanCount")
        defaults.set(dateKey(), forKey: "barkain.featureGate.lastScanDateKey")

        let gate = makeGate(isPro: false, defaults: defaults)

        XCTAssertEqual(gate.dailyScanCount, 7)
        XCTAssertEqual(gate.remainingScans, FeatureGateService.freeDailyScanLimit - 7)
    }
}
