import SwiftUI

// MARK: - BarkainApp

@main
struct BarkainApp: App {

    // MARK: - Services
    //
    // SubscriptionService + FeatureGateService are owned by the App so they
    // live for the full process lifetime and survive view rebuilds. They're
    // injected into the SwiftUI environment via the iOS 17+ native
    // `.environment(observableObject)` API; child views read them with
    // `@Environment(SubscriptionService.self)` etc.

    @State private var subscriptionService: SubscriptionService
    @State private var featureGateService: FeatureGateService
    @State private var recentSearches = RecentSearches()
    @State private var recentlyScanned = RecentlyScannedStore()
    private let autocompleteService: any AutocompleteServiceProtocol = AutocompleteService()

    init() {
        let subscription = SubscriptionService()
        // configure() is idempotent + falls open to free tier when the
        // RevenueCat API key is missing (e.g. preview / unit-test build).
        // app_user_id is bound to the demo Clerk user so webhook events can
        // map to the matching `users` row. Replace with the live Clerk
        // session id when the iOS auth SDK lands.
        subscription.configure(
            apiKey: AppConfig.revenueCatAPIKey,
            appUserId: AppConfig.demoUserId
        )
        let gate = FeatureGateService(subscription: subscription)

        _subscriptionService = State(initialValue: subscription)
        _featureGateService = State(initialValue: gate)
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(subscriptionService)
                .environment(featureGateService)
                .environment(\.autocompleteService, autocompleteService)
                .environment(\.recentSearches, recentSearches)
                .environment(\.recentlyScanned, recentlyScanned)
        }
    }
}
