import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

// MARK: - ContentView
//
// Root TabView. Home is surfaced first so the app launches with the
// brand front-and-centre; users who prefer Scan can still go there in
// one tap. The Home tab owns "quick action" buttons that flip the tab
// selection from inside HomeView — `selection` is `@State` here and
// passed down as a binding-via-closure.

struct ContentView: View {

    // MARK: - Tab identifiers

    private enum Tab: Hashable {
        case home, scan, search, savings, profile
    }

    // MARK: - State

    @AppStorage("hasCompletedIdentityOnboarding")
    private var hasCompletedOnboarding: Bool = false

    @State private var showOnboarding = false
    @State private var selection: Tab = .home

    /// When a user taps a "Recently sniffed" card on Home we jump them
    /// to Search with this seed; SearchView consumes + clears it via
    /// `.onChange`. Keeps the cross-tab handoff explicit + one-shot.
    @State private var pendingSearchSeed: String?

    // MARK: - Init — configure the shared UITabBar appearance once.
    //
    // SwiftUI's `.tint(...)` handles active-icon colour, but the bar's
    // background, unselected hue, and shadow divider still come from the
    // UIKit appearance proxy. This block sets:
    //   - a translucent surface background so the bar blends with our
    //     warm-gold palette instead of showing the iOS system chrome
    //   - an ultra-thin divider matching `.barkainOutlineVariant`
    //   - unselected glyphs in the muted on-surface-variant tone

    init() {
        let appearance = UITabBarAppearance()
        appearance.configureWithTransparentBackground()
        appearance.backgroundEffect = UIBlurEffect(style: .systemUltraThinMaterial)
        appearance.shadowColor = UIColor { trait in
            trait.userInterfaceStyle == .dark
                ? UIColor(white: 1, alpha: 0.06)
                : UIColor(red: 0xD4/255, green: 0xC4/255, blue: 0xAC/255, alpha: 0.5)
        }

        let unselected = UIColor { trait in
            trait.userInterfaceStyle == .dark
                ? UIColor(red: 0xB8/255, green: 0xAC/255, blue: 0x96/255, alpha: 1)
                : UIColor(red: 0x50/255, green: 0x45/255, blue: 0x33/255, alpha: 1)
        }
        for item in [appearance.stackedLayoutAppearance, appearance.inlineLayoutAppearance, appearance.compactInlineLayoutAppearance] {
            item.normal.iconColor = unselected
            item.normal.titleTextAttributes = [.foregroundColor: unselected]
        }

        UITabBar.appearance().standardAppearance = appearance
        UITabBar.appearance().scrollEdgeAppearance = appearance
    }

    // MARK: - Body

    var body: some View {
        TabView(selection: $selection) {
            NavigationStack {
                HomeView(
                    onSelectScan: { selection = .scan },
                    onSelectSearch: { selection = .search },
                    onSelectRecent: { item in
                        pendingSearchSeed = item.name
                        selection = .search
                    }
                )
            }
            .tag(Tab.home)
            .tabItem {
                Label("Home", systemImage: "pawprint.fill")
            }

            NavigationStack {
                ScannerView()
            }
            .tag(Tab.scan)
            .tabItem {
                Label("Scan", systemImage: "barcode.viewfinder")
            }

            NavigationStack {
                SearchView(pendingSeed: $pendingSearchSeed)
            }
            .tag(Tab.search)
            .tabItem {
                Label("Search", systemImage: "magnifyingglass")
            }

            NavigationStack {
                SavingsPlaceholderView()
            }
            .tag(Tab.savings)
            .tabItem {
                Label("Savings", systemImage: "chart.line.uptrend.xyaxis")
            }

            NavigationStack {
                ProfileView()
            }
            .tag(Tab.profile)
            .tabItem {
                Label("Kennel", systemImage: "house.fill")
            }
        }
        .tint(.barkainPrimary)
        .task {
            if !hasCompletedOnboarding {
                showOnboarding = true
            }
        }
        .sheet(isPresented: $showOnboarding) {
            IdentityOnboardingView(
                viewModel: IdentityOnboardingViewModel(apiClient: APIClient()),
                hasCompletedOnboarding: $hasCompletedOnboarding
            )
        }
    }
}

// MARK: - Preview

#Preview {
    ContentView()
}
