import SwiftUI

// MARK: - SavingsBadge

struct SavingsBadge: View {

    // MARK: - Properties

    let savedAmount: Double
    let originalPrice: Double

    // MARK: - Body

    var body: some View {
        HStack(spacing: Spacing.xxs) {
            Image(systemName: "arrow.down.circle.fill")
                .font(.caption)
            Text("Save \(formattedAmount)")
                .font(.barkainLabel)
                .tracking(0.5)
        }
        .foregroundStyle(Color.barkainPrimary)
        .padding(.horizontal, Spacing.sm)
        .padding(.vertical, 6)
        .background(Color.barkainPrimaryFixed.opacity(0.5))
        .clipShape(Capsule())
    }

    // MARK: - Helpers

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
}
