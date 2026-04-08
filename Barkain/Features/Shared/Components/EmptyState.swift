import SwiftUI

// MARK: - EmptyState

struct EmptyState: View {

    // MARK: - Properties

    let icon: String
    let title: String
    let subtitle: String
    var actionTitle: String?
    var action: (() -> Void)?

    // MARK: - Body

    var body: some View {
        VStack(spacing: Spacing.md) {
            Image(systemName: icon)
                .font(.system(size: 56))
                .foregroundStyle(Color.barkainOutlineVariant)

            Text(title)
                .font(.barkainTitle2)
                .foregroundStyle(Color.barkainOnSurface)

            Text(subtitle)
                .font(.barkainBody)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
                .multilineTextAlignment(.center)

            if let actionTitle, let action {
                Button(action: action) {
                    Text(actionTitle)
                        .font(.barkainHeadline)
                        .foregroundStyle(.white)
                        .padding(.horizontal, Spacing.xl)
                        .padding(.vertical, Spacing.sm)
                        .background(Color.barkainPrimaryGradient)
                        .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadiusLarge))
                }
                .padding(.top, Spacing.xs)
            }
        }
        .padding(Spacing.xl)
    }
}

// MARK: - Preview

#Preview {
    EmptyState(
        icon: "magnifyingglass",
        title: "No Results",
        subtitle: "Try scanning a different barcode or searching for a product.",
        actionTitle: "Try Again",
        action: {}
    )
}
