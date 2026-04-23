import SwiftUI

// MARK: - PriceRow

struct PriceRow: View {

    // MARK: - Properties

    let retailerPrice: RetailerPrice
    /// Step 2e — optional best-card subtitle shown below the price row.
    var cardRecommendation: CardRecommendation? = nil
    /// Visual emphasis bump for the cheapest row. Drawn with a primary
    /// container border + a slight lift — matches the HTML's
    /// "Best Barkain" treatment.
    var isBest: Bool = false
    /// Tapping the "Using SF default" pill (fb_marketplace + no
    /// fb_location_id) calls this — parent wires it up to deep-link
    /// into Profile → Marketplace location. Optional; pill is
    /// non-interactive when nil.
    var onLocationDefaultPillTap: (() -> Void)? = nil

    // MARK: - Body

    var body: some View {
        VStack(spacing: Spacing.xs) {
            HStack(spacing: Spacing.md) {
                retailerIcon
                retailerInfo
                Spacer(minLength: 0)
                priceInfo
            }
            if showsLocationDefaultPill {
                locationDefaultPill
            }
            if let rec = cardRecommendation {
                cardRecommendationRow(rec)
            }
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.md)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .fill(isBest ? Color.barkainSurfaceContainerLowest : Color.barkainSurfaceContainerLow)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .stroke(
                    isBest ? Color.barkainPrimaryContainer.opacity(0.5) : Color.clear,
                    lineWidth: 2
                )
        )
        .barkainShadowSoft()
    }

    // MARK: - Location default pill (fb-resolver-followups L12)

    /// Visible only on the fb_marketplace row when the backend tells us
    /// the container fell back to its baked SF default — i.e., the user
    /// never picked a Marketplace location.
    private var showsLocationDefaultPill: Bool {
        retailerPrice.retailerId == "fb_marketplace"
            && retailerPrice.locationDefaultUsed == true
    }

    private var locationDefaultPill: some View {
        Button {
            onLocationDefaultPillTap?()
        } label: {
            HStack(spacing: Spacing.xxs) {
                Image(systemName: "mappin.and.ellipse")
                    .font(.caption2)
                Text("Using SF default — set your city in Profile")
                    .font(.barkainCaption)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                Spacer(minLength: 0)
            }
            .foregroundStyle(Color.barkainOnSurface)
            .padding(.horizontal, Spacing.sm)
            .padding(.vertical, Spacing.xs)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: Spacing.cornerRadiusSmall, style: .continuous)
                    .fill(Color.barkainPrimaryFixed.opacity(0.45))
            )
        }
        .buttonStyle(.plain)
        .disabled(onLocationDefaultPillTap == nil)
        .accessibilityLabel("Using San Francisco default location. Tap to set your city in Profile.")
    }

    // MARK: - Card recommendation

    private func cardRecommendationRow(_ rec: CardRecommendation) -> some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: "creditcard.fill")
                .font(.caption)
                .foregroundStyle(Color.barkainPrimary)
            Text(cardRecText(rec))
                .font(.barkainCaption)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
                .lineLimit(2)
            Spacer()
            if rec.activationRequired, let activationUrl = rec.activationUrl,
               let url = URL(string: activationUrl) {
                Link(destination: url) {
                    Text("Activate")
                        .font(.barkainLabel)
                        .tracking(0.8)
                        .textCase(.uppercase)
                        .foregroundStyle(.white)
                        .padding(.horizontal, Spacing.sm)
                        .padding(.vertical, Spacing.xxs)
                        .background(Capsule().fill(Color.barkainPrimaryGradient))
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, Spacing.sm)
        .padding(.vertical, Spacing.xs)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadiusSmall, style: .continuous)
                .fill(Color.barkainPrimaryFixed.opacity(0.35))
        )
    }

    private func cardRecText(_ rec: CardRecommendation) -> String {
        let rateLabel: String
        if rec.rewardRate.truncatingRemainder(dividingBy: 1) == 0 {
            rateLabel = String(format: "%.0fx", rec.rewardRate)
        } else {
            rateLabel = String(format: "%.1fx", rec.rewardRate)
        }
        let amount = String(format: "$%.2f", rec.rewardAmount)
        return "Use \(rec.cardDisplayName) for \(rateLabel) (\(amount) back)"
    }

    // MARK: - Subviews

    private var retailerIcon: some View {
        ZStack {
            Circle()
                .fill(Color.barkainSurfaceContainer)
            Image(systemName: "bag.fill")
                .font(.body)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
        }
        .frame(width: 48, height: 48)
    }

    private var retailerInfo: some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(retailerPrice.retailerName)
                .font(.barkainHeadline)
                .foregroundStyle(Color.barkainOnSurface)

            HStack(spacing: Spacing.xxs) {
                Text(retailerPrice.condition.capitalized)
                    .font(.barkainCaption)
                    .foregroundStyle(Color.barkainOnSurfaceVariant)

                if retailerPrice.isOnSale {
                    Text("SALE")
                        .font(.barkainLabel)
                        .tracking(0.8)
                        .foregroundStyle(.white)
                        .padding(.horizontal, Spacing.xs)
                        .padding(.vertical, 2)
                        .background(Capsule().fill(Color.barkainError))
                }
            }
        }
    }

    private var priceInfo: some View {
        VStack(alignment: .trailing, spacing: Spacing.xxs) {
            Text(formattedPrice(retailerPrice.price))
                .font(.barkainTitle)
                .foregroundStyle(Color.barkainPrimary)
                // Long prices ($2,249.99) were wrapping the trailing "9" to a
                // second line because the retailer-info column ate the space.
                // Keep the price on one row and let the font auto-shrink a
                // bit before trimming.
                .lineLimit(1)
                .minimumScaleFactor(0.7)

            if let originalPrice = retailerPrice.originalPrice,
               retailerPrice.isOnSale {
                Text(formattedPrice(originalPrice))
                    .font(.barkainCaption)
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
                    .strikethrough()
                    .lineLimit(1)
            }
        }
        // Win the width negotiation against retailerInfo so the price
        // block always gets the room it needs.
        .layoutPriority(1)
    }

    // MARK: - Helpers

    private func formattedPrice(_ price: Double) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = retailerPrice.currency
        return formatter.string(from: NSNumber(value: price)) ?? "$\(price)"
    }
}

// MARK: - Preview

#Preview {
    VStack(spacing: Spacing.xs) {
        PriceRow(retailerPrice: RetailerPrice(
            retailerId: "amazon",
            retailerName: "Amazon",
            price: 298.00,
            originalPrice: 349.99,
            currency: "USD",
            url: nil,
            condition: "new",
            isAvailable: true,
            isOnSale: true,
            lastChecked: Date()
        ), isBest: true)
        PriceRow(retailerPrice: RetailerPrice(
            retailerId: "best_buy",
            retailerName: "Best Buy",
            price: 329.99,
            originalPrice: nil,
            currency: "USD",
            url: nil,
            condition: "new",
            isAvailable: true,
            isOnSale: false,
            lastChecked: Date()
        ))
    }
    .padding()
    .background(Color.barkainSurface)
}
