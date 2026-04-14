import SwiftUI
import RevenueCat
import RevenueCatUI

// MARK: - CustomerCenterHost
//
// Thin SwiftUI wrapper around RevenueCat's `CustomerCenterView`. Lets Pro
// users manage their subscription (cancel, change plan, request a refund,
// contact support) without leaving the app. RevenueCat's dashboard owns
// the layout + paths; this file exists so the Profile tab can mount the
// view via a NavigationLink without importing `RevenueCatUI` directly.

struct CustomerCenterHost: View {
    var body: some View {
        CustomerCenterView()
            .navigationTitle("Manage Subscription")
            .navigationBarTitleDisplayMode(.inline)
    }
}
