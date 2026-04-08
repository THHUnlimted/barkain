import SwiftUI

// MARK: - PriceRow

struct PriceRow: View {

    // MARK: - Properties

    let retailerPrice: RetailerPrice

    // MARK: - Body

    var body: some View {
        HStack(spacing: Spacing.md) {
            retailerIcon
            retailerInfo
            Spacer()
            priceInfo
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.sm)
        .background(Color.barkainSurfaceContainerLow)
        .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadius))
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
