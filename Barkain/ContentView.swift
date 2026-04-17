import SwiftUI

// MARK: - ContentView

struct ContentView: View {

    // MARK: - State

    @AppStorage("hasCompletedIdentityOnboarding")
    private var hasCompletedOnboarding: Bool = false

    @State private var showOnboarding = false

    // MARK: - Body

    var body: some View {
        TabView {
            NavigationStack {
                ScannerView()
            }
            .tabItem {
                Label("Scan", systemImage: "barcode.viewfinder")
            }

            NavigationStack {
                SearchView()
            }
            .tabItem {
                Label("Search", systemImage: "magnifyingglass")
            }

            NavigationStack {
                SavingsPlaceholderView()
            }
            .tabItem {
                Label("Savings", systemImage: "chart.line.uptrend.xyaxis")
            }

            NavigationStack {
                ProfileView()
            }
            .tabItem {
                Label("Profile", systemImage: "person.circle")
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
