import SwiftUI
import RevenueCat
import RevenueCatUI

// MARK: - PaywallHost
//
// Thin SwiftUI wrapper around RevenueCat's `PaywallView` so call sites stay
// clean and don't need to import `RevenueCatUI` directly.
//
// Uses RevenueCat's built-in paywall UI (configured remotely from the
// dashboard). The dashboard owns layout, copy, and pricing; this app only
// hooks the success / restore callbacks to dismiss the sheet and reconcile
// `SubscriptionService` state.

struct PaywallHost: View {

    // MARK: - Properties

    @Environment(\.dismiss) private var dismiss
    @Environment(SubscriptionService.self) private var subscription

    /// Closure called after a successful purchase. The host always dismisses
    /// the sheet first; the callback fires after.
    var onPurchase: (() -> Void)? = nil

    /// Closure called after a successful restore.
    var onRestore: (() -> Void)? = nil

    // MARK: - Body

    var body: some View {
        PaywallView()
            .onPurchaseCompleted { _ in
                Task {
                    // Reconcile the SDK cache before we dismiss so any view
                    // observing `subscription.isProUser` sees the change
                    // instantly on dismiss.
                    await subscription.refresh()
                    onPurchase?()
                    dismiss()
                }
            }
            .onRestoreCompleted { _ in
                Task {
                    await subscription.refresh()
                    onRestore?()
                    dismiss()
                }
            }
    }
}
