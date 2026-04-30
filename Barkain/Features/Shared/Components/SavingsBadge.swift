import SwiftUI

// MARK: - SavingsBadge

struct SavingsBadge: View {

    // MARK: - Properties

    let savedAmount: Double
    let originalPrice: Double

    // MARK: - Body

    var body: some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: "arrow.down.circle.fill")
                .font(.system(size: 14, weight: .bold))
            Text("Save \(formattedAmount)" + (percentageOff > 0 ? " (\(percentageOff)%)" : ""))
                .font(.barkainLabel)
                .tracking(1.2)
                .textCase(.uppercase)
        }
        .foregroundStyle(Color.barkainOnPrimaryFixed)
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.xs)
        .background(
            Capsule(style: .continuous)
                .fill(Color.barkainPrimaryFixed)
        )
        .overlay(
            Capsule(style: .continuous)
                .stroke(Color.barkainPrimaryContainer.opacity(0.4), lineWidth: 1)
        )
        .barkainShadowSoft()
    }

    // MARK: - Helpers

    private var percentageOff: Int {
        guard originalPrice > 0 else { return 0 }
        return Int(round(savedAmount / originalPrice * 100))
    }

    private var formattedAmount: String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        formatter.maximumFractionDigits = 2
        return formatter.string(from: NSNumber(value: savedAmount)) ?? "$\(savedAmount)"
    }
}

// MARK: - Preview

#Preview {
    SavingsBadge(savedAmount: 51.99, originalPrice: 349.99)
        .padding()
        .background(Color.barkainSurface)
}
