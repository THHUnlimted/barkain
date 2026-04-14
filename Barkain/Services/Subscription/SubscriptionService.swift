import Foundation
import OSLog
import RevenueCat

// MARK: - Logger

private let billingLog = Logger(subsystem: "com.barkain.app", category: "Billing")

// MARK: - SubscriptionService
//
// Thin wrapper around the RevenueCat SDK that exposes a SwiftUI-observable
// view of the current tier + `CustomerInfo` + offerings. Designed to live in
// the SwiftUI environment (see `BarkainApp`) so any view can gate on
// `subscription.isProUser`.
//
// ## Two sources of truth, by design
//
// The iOS client reads tier state from this service (backed by RevenueCat's
// SDK). The backend reads `users.subscription_tier` from Postgres, kept in
// sync by the `POST /api/v1/billing/webhook` endpoint. Up to ~60s drift is
// accepted for rate-limit purposes so UI gating never blocks on a network
// round-trip.
//
// ## Graceful no-configure
//
// If `AppConfig.revenueCatAPIKey` is empty (Release build without a real
// key, tests, or previews), `configure()` logs a warning and stays on free
// tier. The app stays fully functional — paywalls just don't present.

@MainActor
@Observable
final class SubscriptionService {

    // MARK: - Tier

    enum Tier: String, Sendable {
        case free
        case pro
    }

    // MARK: - Observable state

    private(set) var currentTier: Tier = .free
    private(set) var customerInfo: CustomerInfo?
    private(set) var offerings: Offerings?
    private(set) var isConfigured: Bool = false

    var isProUser: Bool { currentTier == .pro }

    // MARK: - Configuration

    /// The RevenueCat entitlement identifier that grants Pro.
    ///
    /// Must match the entitlement configured in the RevenueCat dashboard
    /// (Project Settings → Entitlements). The string has a space and is
    /// case-sensitive — keep it in lockstep with the dashboard.
    private let entitlementId = "Barkain Pro"

    // MARK: - Init

    init() {}

    /// Strong reference to the delegate adapter. RevenueCat holds `delegate`
    /// weakly, so without our own retain the adapter is deallocated on the
    /// first ARC pass and we silently lose all tier updates.
    private var delegateAdapter: PurchasesDelegateAdapter?

    /// Configure the RevenueCat SDK and begin listening for tier changes.
    ///
    /// - Parameters:
    ///   - apiKey: RevenueCat public API key. Empty = billing disabled.
    ///   - appUserId: Identifier used as the RevenueCat `app_user_id`.
    ///     MUST match the backend's Clerk user id so webhook events land
    ///     on the correct `users` row. In demo mode, use the constant
    ///     defined by `AppConfig.demoUserId`.
    ///
    /// Idempotent — calling configure twice is a no-op. The initial
    /// `customerInfo()` fetch is fire-and-forget; tier updates stream in
    /// via the delegate callback installed here.
    func configure(apiKey: String, appUserId: String) {
        guard !isConfigured else { return }
        guard !apiKey.isEmpty else {
            billingLog.warning("RevenueCat API key missing — billing disabled, staying free tier")
            return
        }

        #if DEBUG
        Purchases.logLevel = .debug
        #endif

        Purchases.configure(withAPIKey: apiKey, appUserID: appUserId)
        isConfigured = true
        billingLog.info("RevenueCat configured with appUserId=\(appUserId, privacy: .public)")

        // Install the delegate adapter. v5 uses the `PurchasesDelegate`
        // protocol (NSObject-bound) — we route the callback back to the
        // main actor so observation tracking works correctly.
        let adapter = PurchasesDelegateAdapter { [weak self] info in
            Task { @MainActor in
                self?.apply(info: info)
            }
        }
        delegateAdapter = adapter
        Purchases.shared.delegate = adapter

        // Fire an initial fetch — this resolves from the SDK's local cache
        // first, then backfills from the network. Failure is non-fatal
        // because the delegate above will catch the next update anyway.
        Task { [weak self] in
            do {
                let info = try await Purchases.shared.customerInfo()
                self?.apply(info: info)
            } catch {
                billingLog.warning("Initial customerInfo() failed: \(error.localizedDescription, privacy: .public)")
            }
        }
    }

    // MARK: - Commands

    /// Force a network refresh of the customer info. Normally unnecessary —
    /// the listener handles incremental updates — but useful after the
    /// Paywall's `onPurchaseCompleted` callback to reconcile state.
    func refresh() async {
        guard isConfigured else { return }
        do {
            let info = try await Purchases.shared.customerInfo()
            apply(info: info)
        } catch {
            billingLog.warning("refresh() failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    /// Load the current offerings (products) from RevenueCat. Call before
    /// presenting a paywall if you want to preflight network errors —
    /// `PaywallView()` also does this internally.
    func loadOfferings() async {
        guard isConfigured else { return }
        do {
            offerings = try await Purchases.shared.offerings()
        } catch {
            billingLog.warning("offerings() failed: \(error.localizedDescription, privacy: .public)")
            offerings = nil
        }
    }

    /// Restore previous purchases — wired up to the Paywall's restore button
    /// and the Profile tab's restore action (when added).
    func restorePurchases() async throws -> CustomerInfo {
        guard isConfigured else {
            throw SubscriptionError.notConfigured
        }
        let info = try await Purchases.shared.restorePurchases()
        apply(info: info)
        return info
    }

    // MARK: - Private

    /// Update the tier + cached customer info from a freshly-received
    /// `CustomerInfo`. Centralized so both the initial fetch and the
    /// listener path run the same reconciliation logic.
    private func apply(info: CustomerInfo) {
        customerInfo = info
        let active = info.entitlements[entitlementId]?.isActive ?? false
        let newTier: Tier = active ? .pro : .free
        if newTier != currentTier {
            billingLog.info(
                "Tier changed: \(self.currentTier.rawValue, privacy: .public) → \(newTier.rawValue, privacy: .public)"
            )
        }
        currentTier = newTier
    }
}

// MARK: - Errors

enum SubscriptionError: Error, LocalizedError {
    case notConfigured

    var errorDescription: String? {
        switch self {
        case .notConfigured:
            return "Billing is not available in this build (RevenueCat API key missing)."
        }
    }
}

// MARK: - PurchasesDelegateAdapter
//
// `PurchasesDelegate` is NSObject-bound (`@objc`) and Swift's `@Observable`
// macro classes don't conform cleanly to NSObject protocols. This thin
// adapter wraps the delegate callback in a closure so `SubscriptionService`
// can stay a pure `@Observable final class`.

private final class PurchasesDelegateAdapter: NSObject, PurchasesDelegate, @unchecked Sendable {
    private let onUpdate: (CustomerInfo) -> Void

    init(onUpdate: @escaping (CustomerInfo) -> Void) {
        self.onUpdate = onUpdate
        super.init()
    }

    func purchases(_ purchases: Purchases, receivedUpdated customerInfo: CustomerInfo) {
        onUpdate(customerInfo)
    }
}
