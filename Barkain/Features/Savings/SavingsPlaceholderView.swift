import SwiftUI

// MARK: - SavingsPlaceholderView
//
// Honest "coming soon" hero for the Savings tab. M10 receipt OCR +
// aggregation aren't wired yet (see CLAUDE.md "What's Next") so we don't
// fabricate numbers — we tell the user what will land here and preview
// the three stats they'll see.

struct SavingsPlaceholderView: View {

    var body: some View {
        ScrollView {
            VStack(spacing: Spacing.lg) {
                heroCard
                statPreviewRow
                explainerCard
                Spacer(minLength: Spacing.xxl)
            }
            .padding(Spacing.lg)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.barkainSurface.ignoresSafeArea())
        .navigationTitle("Savings")
    }

    // MARK: - Hero

    private var heroCard: some View {
        VStack(spacing: Spacing.md) {
            GlowingPawLogo(size: 140)

            VStack(spacing: Spacing.xxs) {
                Text("Your savings trail")
                    .font(.barkainLargeTitle)
                    .foregroundStyle(Color.barkainOnSurface)
                    .multilineTextAlignment(.center)

                Text("Snap a receipt and Barkain tallies up how much your loyal AI sniffed out for you.")
                    .font(.barkainBody)
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, Spacing.md)
            }

            comingSoonBadge
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Spacing.xl)
        .padding(.horizontal, Spacing.lg)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadiusLarge, style: .continuous)
                .fill(Color.barkainSurfaceContainerLow)
        )
        .barkainShadowSoft()
    }

    private var comingSoonBadge: some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: "sparkles")
                .font(.caption)
                .foregroundStyle(Color.barkainPrimary)
            Text("Coming soon")
                .barkainEyebrow()
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.xs)
        .background(
            Capsule(style: .continuous)
                .fill(Color.barkainPrimaryFixed.opacity(0.5))
        )
    }

    // MARK: - Stat preview

    private var statPreviewRow: some View {
        HStack(spacing: Spacing.sm) {
            statTile(icon: "dollarsign.circle.fill", label: "Lifetime savings", placeholder: "—")
            statTile(icon: "receipt.fill", label: "Receipts scanned", placeholder: "—")
            statTile(icon: "pawprint.fill", label: "Deals tracked", placeholder: "—")
        }
    }

    private func statTile(icon: String, label: String, placeholder: String) -> some View {
        VStack(spacing: Spacing.xs) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundStyle(Color.barkainPrimary)
            Text(placeholder)
                .font(.barkainTitle2)
                .foregroundStyle(Color.barkainOnSurface)
            Text(label)
                .font(.barkainCaption)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
                .multilineTextAlignment(.center)
                .lineLimit(2)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Spacing.md)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .fill(Color.barkainSurfaceContainerLowest)
        )
        .barkainShadowSoft()
    }

    // MARK: - Explainer

    private var explainerCard: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text("What lands here")
                .barkainEyebrow()

            explainerRow(
                icon: "doc.text.viewfinder",
                title: "Scan your receipts",
                subtitle: "Target, Amazon, Best Buy, Walmart — any purchase receipt."
            )

            explainerRow(
                icon: "chart.line.uptrend.xyaxis",
                title: "See what you saved",
                subtitle: "Barkain compares each item against the lowest price it found that week."
            )

            explainerRow(
                icon: "bell.badge.fill",
                title: "Catch missed deals",
                subtitle: "If you overpaid, we'll nudge you to track the item so it's cheaper next time."
            )
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .fill(Color.barkainSurfaceContainerLowest)
        )
        .barkainShadowSoft()
    }

    private func explainerRow(icon: String, title: String, subtitle: String) -> some View {
        HStack(alignment: .top, spacing: Spacing.md) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundStyle(Color.barkainPrimary)
                .frame(width: 32, height: 32)
                .background(
                    Circle().fill(Color.barkainPrimaryFixed.opacity(0.4))
                )

            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(title)
                    .font(.barkainHeadline)
                    .foregroundStyle(Color.barkainOnSurface)
                Text(subtitle)
                    .font(.barkainBody)
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
            }
        }
    }
}

#Preview {
    NavigationStack {
        SavingsPlaceholderView()
    }
}
