import Foundation

// MARK: - App Configuration

nonisolated enum AppConfig {
    static let apiBaseURL: URL = {
        // Read from Info.plist (set via xcconfig: Config/Debug.xcconfig or Config/Release.xcconfig)
        if let urlString = Bundle.main.infoDictionary?["API_BASE_URL"] as? String,
           !urlString.isEmpty,
           let url = URL(string: urlString) {
            return url
        }
        #if DEBUG
        #if targetEnvironment(simulator)
        // 127.0.0.1, NOT localhost — the simulator otherwise tries IPv6 (::1)
        // first and the connection hangs / fails on hosts where IPv6 loopback
        // isn't routable to the FastAPI bind. Documented in CLAUDE.md as
        // L-sim-localhost-ipv4.
        return URL(string: "http://127.0.0.1:8000")!
        #else
        // Physical device on dev — must use the Mac's LAN IP and the backend
        // must be bound to 0.0.0.0 (run uvicorn with --host 0.0.0.0). Update
        // this when the dev Mac's LAN IP changes, or set API_BASE_URL via
        // Info.plist / xcconfig so this fallback never fires.
        return URL(string: "http://192.168.1.194:8000")!
        #endif
        #else
        return URL(string: "https://api.barkain.ai")!
        #endif
    }()

    // MARK: - Billing (Step 2f)

    /// RevenueCat public API key, read from Info.plist (set via xcconfig).
    /// Empty string means billing is disabled — the SDK never configures
    /// and `SubscriptionService` stays on free tier.
    static let revenueCatAPIKey: String = {
        (Bundle.main.infoDictionary?["REVENUECAT_API_KEY"] as? String) ?? ""
    }()

    /// Identifier used as RevenueCat `app_user_id` and as the Clerk user id
    /// sent with authenticated requests.
    ///
    /// Must match the value that `backend/app/dependencies.py::get_current_user`
    /// returns in demo mode (`DEMO_MODE=1`, was `BARKAIN_DEMO_MODE` before 2i-b) so the RevenueCat webhook
    /// can find the matching `users` row when we process purchase events.
    /// When the real Clerk iOS SDK lands, replace the constant with the
    /// live Clerk user id from the signed-in session, and call
    /// `Purchases.shared.logIn(id)` / `.logOut()` on auth changes.
    static let demoUserId: String = "demo_user"
}
