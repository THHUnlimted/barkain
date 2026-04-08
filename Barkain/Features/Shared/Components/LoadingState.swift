import SwiftUI

// MARK: - LoadingState

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
        }
        .padding(Spacing.xl)
    }
}

// MARK: - Preview

#Preview {
    LoadingState(message: "Resolving product...")
}
