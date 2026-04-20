import SwiftUI

// MARK: - LoadingState
//
// Generic loading indicator. Spinner + message. Use this for any "we're
// working" state that isn't a price stream — text search, profile fetch,
// card catalog, product resolution, etc. The animated retailer checklist
// with live prices lives in `PriceStreamLoader`.

struct LoadingState: View {

    // MARK: - Properties

    let message: String

    // MARK: - Body

    var body: some View {
        VStack(spacing: Spacing.md) {
            ProgressView()
                .controlSize(.large)
                .tint(Color.barkainPrimary)

            Text(message)
                .font(.barkainBody)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
                .multilineTextAlignment(.center)
        }
        .padding(Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Preview

#Preview {
    LoadingState(message: "Resolving product…")
        .background(Color.barkainSurface)
}
