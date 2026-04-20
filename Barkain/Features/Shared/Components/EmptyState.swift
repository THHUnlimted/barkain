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
        VStack(spacing: Spacing.lg) {
            iconWell

            VStack(spacing: Spacing.xs) {
                Text(title)
                    .font(.barkainTitle)
                    .foregroundStyle(Color.barkainOnSurface)
                    .multilineTextAlignment(.center)

                Text(subtitle)
                    .font(.barkainBody)
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
                    .multilineTextAlignment(.center)
            }

            if let actionTitle, let action {
                Button(action: action) {
                    Text(actionTitle)
                        .font(.barkainHeadline)
                        .foregroundStyle(.white)
                        .padding(.horizontal, Spacing.xl)
                        .padding(.vertical, Spacing.md)
                        .background(
                            Capsule(style: .continuous)
                                .fill(Color.barkainPrimaryGradient)
                        )
                }
                .buttonStyle(.plain)
                .barkainShadowGlow()
                .padding(.top, Spacing.xs)
            }
        }
        .padding(Spacing.xl)
        .frame(maxWidth: .infinity)
    }

    /// Large iconographic well — a soft-gold disc behind the SF Symbol.
    /// Matches the HTML's recurring "icon-in-a-tinted-circle" pattern.
    private var iconWell: some View {
        ZStack {
            Circle()
                .fill(Color.barkainPrimaryFixed.opacity(0.45))
                .frame(width: 120, height: 120)
            Circle()
                .fill(Color.barkainPrimaryFixed.opacity(0.25))
                .frame(width: 160, height: 160)
            Image(systemName: icon)
                .font(.system(size: 52, weight: .semibold))
                .foregroundStyle(Color.barkainPrimary)
        }
        .frame(width: 160, height: 160)
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
    .background(Color.barkainSurface)
}
