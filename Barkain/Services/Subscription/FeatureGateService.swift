import Foundation
import OSLog

private let gateLog = Logger(subsystem: "com.barkain.app", category: "Billing")

// MARK: - ProFeature

/// Which features are gated behind the Pro tier. Free tier gets a strict
/// subset; Pro tier gets everything.
enum ProFeature: String, CaseIterable, Sendable {
    /// Free: 10 scans/day. Pro: unlimited.
    case unlimitedScans
    /// Free: first 3 identity discounts. Pro: all matched discounts.
    case fullIdentityDiscounts
    /// Free: hidden (single CTA banner). Pro: per-row card subtitle.
    case cardRecommendations
    /// Free: hidden. Pro: full price history. (Phase 4 feature, gated now.)
    case priceHistory
}

// MARK: - FeatureGateService
//
// Pure-Swift gate that owns the daily scan counter and exposes feature
// access decisions. Decoupled from the RevenueCat SDK via a `proTierProvider`
// closure so tests can flip Pro on/off without touching the SDK at all.
//
// ## Daily reset
//
// `dailyScanCount` rolls over to 0 when the local-timezone date changes.
// We store the last seen date as a `yyyy-MM-dd` string (not a Date) so the
// comparison is timezone-explicit and trivially testable. PST users
// scanning at 11:59pm PST and 12:01am PST get a fresh quota at midnight
// local — not at midnight UTC.
//
// ## Bypass vectors (acknowledged for MVP)
//
// - Reinstall: clears UserDefaults → fresh quota
// - Clock manipulation: trivial bypass
// - Multi-device: doubles their quota
//
// All deferred until post-launch abuse is observed. Tracking server-side
// would add a write to a hot SSE-adjacent path and demand timezone
// reasoning on the backend.

@MainActor
@Observable
final class FeatureGateService {

    // MARK: - Constants

    static let freeDailyScanLimit: Int = 10
    static let freeIdentityDiscountLimit: Int = 3

    private static let scanCountKey = "barkain.featureGate.dailyScanCount"
    private static let scanDateKey = "barkain.featureGate.lastScanDateKey"

    // MARK: - Experiment flags
    //
    // Default-OFF feature flags backed by UserDefaults. Production access
    // routes through these accessors so tests can flip them via the
    // injected `defaults` suite without touching `.standard`.

    /// PR-2: optimistic search-tap navigation. When ON, tapping a non-DB
    /// search result navigates to the PriceComparisonView skeleton
    /// immediately and runs `/resolve-from-search` in the background; when
    /// OFF, the legacy await-resolve-then-navigate flow runs. Default OFF
    /// for one TestFlight build per the rollout plan — flip via a debug
    /// gesture or remote config when ready.
    static let optimisticSearchTapKey = "experiment.optimisticSearchTap"

    // MARK: - Observable state

    private(set) var dailyScanCount: Int = 0
    private(set) var lastScanDateKey: String = ""

    // MARK: - Dependencies

    private let defaults: UserDefaults
    private let clock: () -> Date
    private let proTierProvider: () -> Bool

    // MARK: - Init

    /// Production initializer — gates are driven by a `SubscriptionService`.
    convenience init(subscription: SubscriptionService) {
        self.init(
            proTierProvider: { subscription.isProUser },
            defaults: .standard,
            clock: Date.init
        )
    }

    /// Test seam — bypasses any SDK and uses the provided closures directly.
    /// Tests pass a custom UserDefaults suite to avoid cross-test pollution
    /// and a clock closure to drive date rollover deterministically.
    init(
        proTierProvider: @escaping () -> Bool,
        defaults: UserDefaults = .standard,
        clock: @escaping () -> Date = Date.init
    ) {
        self.proTierProvider = proTierProvider
        self.defaults = defaults
        self.clock = clock
        hydrate()
    }

    // MARK: - Tier

    var isPro: Bool { proTierProvider() }

    // MARK: - Experiment flags

    /// PR-2 default-OFF: see `optimisticSearchTapKey` documentation.
    var isOptimisticSearchTapEnabled: Bool {
        defaults.bool(forKey: Self.optimisticSearchTapKey)
    }

    // MARK: - Feature access

    func canAccess(_ feature: ProFeature) -> Bool {
        if isPro { return true }
        // Free tier blanket-denies every Pro feature. Per-feature exceptions
        // (e.g. partial identity discounts) are handled at the call site by
        // slicing the data, not by returning true here.
        return false
    }

    // MARK: - Scan quota

    /// True when a free user has hit today's scan cap. Pro users always
    /// return false. Triggers a daily rollover check before reading.
    var scanLimitReached: Bool {
        if isPro { return false }
        rolloverIfNeeded()
        return dailyScanCount >= Self.freeDailyScanLimit
    }

    /// Number of scans remaining today for a free user. `nil` for pro
    /// (= unlimited / no UI display).
    var remainingScans: Int? {
        if isPro { return nil }
        rolloverIfNeeded()
        return max(0, Self.freeDailyScanLimit - dailyScanCount)
    }

    /// Increment the counter. Call this AFTER a successful product resolve,
    /// not before — we don't burn quota on barcode read failures.
    func recordScan() {
        rolloverIfNeeded()
        dailyScanCount += 1
        defaults.set(dailyScanCount, forKey: Self.scanCountKey)
        gateLog.debug(
            "recordScan \(self.dailyScanCount, privacy: .public)/\(Self.freeDailyScanLimit, privacy: .public)"
        )
    }

    // MARK: - Persistence

    private func hydrate() {
        let storedCount = defaults.integer(forKey: Self.scanCountKey)
        let storedDate = defaults.string(forKey: Self.scanDateKey) ?? ""
        let today = currentDateKey()

        if storedDate != today {
            // Either first launch or a day has passed since the last scan.
            // Reset to zero and record today's date.
            dailyScanCount = 0
            lastScanDateKey = today
            defaults.set(0, forKey: Self.scanCountKey)
            defaults.set(today, forKey: Self.scanDateKey)
        } else {
            dailyScanCount = storedCount
            lastScanDateKey = storedDate
        }
    }

    private func rolloverIfNeeded() {
        let today = currentDateKey()
        if today != lastScanDateKey {
            gateLog.info(
                "Daily quota rolled over from \(self.lastScanDateKey, privacy: .public) → \(today, privacy: .public)"
            )
            dailyScanCount = 0
            lastScanDateKey = today
            defaults.set(0, forKey: Self.scanCountKey)
            defaults.set(today, forKey: Self.scanDateKey)
        }
    }

    private func currentDateKey() -> String {
        // Use a fresh formatter per call. Cheap (no allocations of note),
        // and avoids the foot-gun of a shared formatter being mutated
        // from a different timezone in tests.
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.timeZone = .current
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: clock())
    }
}
