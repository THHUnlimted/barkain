import SwiftUI

// MARK: - ContentView

struct ContentView: View {

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
                SearchPlaceholderView()
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
                ProfilePlaceholderView()
            }
            .tabItem {
                Label("Profile", systemImage: "person.circle")
            }
        }
        .tint(.barkainPrimary)
    }
}

// MARK: - Preview

#Preview {
    ContentView()
}
