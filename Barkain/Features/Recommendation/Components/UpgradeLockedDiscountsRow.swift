import SwiftUI

// MARK: - UpgradeLockedDiscountsRow
//
// Tap-to-paywall row shown below the (truncated) identity discounts section
// when a free user matched more discounts than they're allowed to see. We
// slice the discount list at `FeatureGateService.freeIdentityDiscountLimit`
// in the parent view; this row exposes the hidden count + a single CTA.

struct UpgradeLockedDiscountsRow: View {

    let hiddenCount: Int
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: Spacing.sm) {
                Image(systemName: "lock.fill")
                    .foregroundStyle(Color.barkainPrimary)
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text("Upgrade to see \(hiddenCount) more discount\(hiddenCount == 1 ? "" : "s")")
                        .font(.barkainHeadline)
                        .foregroundStyle(Color.barkainOnSurface)
                    Text("Pro members see every identity discount you qualify for.")
                        .font(.barkainCaption)
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
            }
            .padding(Spacing.md)
            .background(Color.barkainPrimaryFixed.opacity(0.3))
            .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}
