import SwiftUI

// MARK: - UpgradeCardsBanner
//
// Single subtle banner shown above the retailer list when a free user has
// matching card recommendations but isn't entitled to see them. We render
// ONE banner instead of repeating "Upgrade to Pro" 11 times across every
// retailer row — less visual noise, equally discoverable.

struct UpgradeCardsBanner: View {

    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: Spacing.sm) {
                Image(systemName: "creditcard.fill")
                    .foregroundStyle(Color.barkainPrimary)
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text("Upgrade for card recommendations")
                        .font(.barkainHeadline)
                        .foregroundStyle(Color.barkainOnSurface)
                    Text("Pro members see the best card to use at each retailer.")
                        .font(.barkainCaption)
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
            }
            .padding(Spacing.md)
            .background(Color.barkainSurfaceContainerLow)
            .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}
