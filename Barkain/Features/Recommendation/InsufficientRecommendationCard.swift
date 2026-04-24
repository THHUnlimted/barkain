import SwiftUI

// MARK: - InsufficientRecommendationCard (demo-prep-1 Item 1)
//
// Renders at the hero slot in PriceComparisonView when the backend returns
// 422 RECOMMEND_INSUFFICIENT_DATA. Replaces the previous silent-hero
// behavior where a missing hero was indistinguishable from "still loading"
// — a common F&F demo failure mode per L-perf-L4.
//
// The retailer grid below stays visible; this card is additive, not
// blocking. Friendly copy, no retry (insufficient-data is permanent for
// this product + this session; the user can scan again).

struct InsufficientRecommendationCard: View {

    // MARK: - Properties

    let productName: String

    // MARK: - Body

    var body: some View {
        HStack(alignment: .top, spacing: Spacing.md) {
            iconWell
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text("Couldn't pick a best option")
                    .font(.barkainHeadline)
                    .foregroundStyle(Color.barkainOnSurface)
                    .accessibilityIdentifier("insufficientRecommendationTitle")

                Text("Not enough price data for \(productName) yet. The retailers we did find are listed below.")
                    .font(.barkainBody)
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .padding(Spacing.md)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .fill(Color.barkainSurfaceContainerLow)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .stroke(Color.barkainOutlineVariant, lineWidth: 1)
        )
        .accessibilityIdentifier("insufficientRecommendationCard")
    }

    private var iconWell: some View {
        ZStack {
            Circle()
                .fill(Color.barkainPrimaryFixed.opacity(0.35))
                .frame(width: 44, height: 44)
            Image(systemName: "magnifyingglass")
                .font(.system(size: 20, weight: .semibold))
                .foregroundStyle(Color.barkainPrimary)
        }
    }
}

// MARK: - Preview

#Preview {
    InsufficientRecommendationCard(productName: "Logitech G613 Wireless Keyboard")
        .padding()
        .background(Color.barkainSurface)
}
