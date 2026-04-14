import SwiftUI

// MARK: - PriceRow

struct PriceRow: View {

    // MARK: - Properties

    let retailerPrice: RetailerPrice
    /// Step 2e — optional best-card subtitle shown below the price row.
    var cardRecommendation: CardRecommendation? = nil

    // MARK: - Body

    var body: some View {
        VStack(spacing: Spacing.xs) {
            HStack(spacing: Spacing.md) {
                retailerIcon
                retailerInfo
                Spacer()
                priceInfo
            }
            if let rec = cardRecommendation {
                cardRecommendationRow(rec)
            }
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.sm)
        .background(Color.barkainSurfaceContainerLow)
        .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadius))
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
                        .foregroundStyle(.white)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(Color.barkainPrimary)
                        .clipShape(Capsule())
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, Spacing.sm)
        .padding(.vertical, Spacing.xxs)
        .background(Color.barkainPrimaryFixed.opacity(0.35))
        .clipShape(RoundedRectangle(cornerRadius: 8))
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
            Image(systemName: "bag")
                .font(.body)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
        }
        .frame(width: 40, height: 40)
    }

    private var retailerInfo: some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(retailerPrice.retailerName)
                .font(.barkainBody)
                .foregroundStyle(Color.barkainOnSurface)

            HStack(spacing: Spacing.xxs) {
                Text(retailerPrice.condition.capitalized)
                    .font(.barkainCaption)
                    .foregroundStyle(Color.barkainOnSurfaceVariant)

                if retailerPrice.isOnSale {
                    Text("SALE")
                        .font(.barkainLabel)
                        .foregroundStyle(.white)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Color.barkainError)
                        .clipShape(Capsule())
                }
            }
        }
    }

    private var priceInfo: some View {
        VStack(alignment: .trailing, spacing: Spacing.xxs) {
            Text(formattedPrice(retailerPrice.price))
                .font(.barkainTitle2)
                .foregroundStyle(Color.barkainPrimary)

            if let originalPrice = retailerPrice.originalPrice,
               retailerPrice.isOnSale {
                Text(formattedPrice(originalPrice))
                    .font(.barkainCaption)
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
                    .strikethrough()
            }
        }
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
        ))
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
}
