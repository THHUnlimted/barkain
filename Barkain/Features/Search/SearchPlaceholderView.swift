import SwiftUI

// MARK: - SearchPlaceholderView

struct SearchPlaceholderView: View {
    var body: some View {
        EmptyState(
            icon: "magnifyingglass",
            title: "Search",
            subtitle: "Search for products by name or description. Coming soon."
        )
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.barkainSurface)
        .navigationTitle("Search")
    }
}

#Preview {
    NavigationStack {
        SearchPlaceholderView()
    }
}
