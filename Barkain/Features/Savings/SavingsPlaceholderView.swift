import SwiftUI

// MARK: - SavingsPlaceholderView

struct SavingsPlaceholderView: View {
    var body: some View {
        EmptyState(
            icon: "chart.line.uptrend.xyaxis",
            title: "Savings",
            subtitle: "Track your savings from price comparisons. Coming soon."
        )
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.barkainSurface)
        .navigationTitle("Savings")
    }
}

#Preview {
    NavigationStack {
        SavingsPlaceholderView()
    }
}
