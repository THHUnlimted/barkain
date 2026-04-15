import SwiftUI

// MARK: - IdentityDiscountsSection

struct IdentityDiscountsSection: View {

    let discounts: [EligibleDiscount]
    // Step 2g: verification URL taps are routed through an in-app browser
    // sheet owned by the presenting view. Identity URLs are NOT affiliate
    // links — no `/affiliate/click` round-trip.
    let onOpen: (URL) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            header
            ForEach(discounts) { discount in
                IdentityDiscountCard(discount: discount, onOpen: onOpen)
            }
        }
    }

    private var header: some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: "person.badge.shield.checkmark.fill")
                .foregroundStyle(Color.barkainPrimary)
            Text("Your Identity Savings")
                .font(.barkainTitle2)
                .foregroundStyle(Color.barkainOnSurface)
            Spacer()
        }
    }
}

// MARK: - IdentityDiscountCard

struct IdentityDiscountCard: View {

    let discount: EligibleDiscount
    let onOpen: (URL) -> Void

    var body: some View {
        Button {
            openVerificationURL()
        } label: {
            HStack(spacing: Spacing.md) {
                iconBadge

                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(discount.retailerName)
                        .font(.barkainHeadline)
                        .foregroundStyle(Color.barkainOnSurface)
                    Text(programLine)
                        .font(.barkainCaption)
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                        .lineLimit(2)
                    if let badge = verificationBadge {
                        Text(badge)
                            .font(.barkainCaption)
                            .foregroundStyle(Color.barkainPrimary)
                            .padding(.horizontal, Spacing.xs)
                            .padding(.vertical, 2)
                            .background(Color.barkainPrimaryFixed.opacity(0.6))
                            .clipShape(Capsule())
                    }
                }

                Spacer()

                VStack(alignment: .trailing, spacing: Spacing.xxs) {
                    savingsLabel
                    Image(systemName: "arrow.up.right.square")
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                        .font(.caption)
                }
            }
            .padding(Spacing.md)
            .background(Color.barkainSurfaceContainerLowest)
            .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                    .stroke(Color.barkainPrimaryFixed, lineWidth: 1.5)
            )
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityHint("Opens the verification page in an in-app browser")
    }

    // Exposed for testing. Prefers `verificationUrl` over `url`, returns
    // nil if both are missing or unparseable.
    var resolvedURL: URL? {
        let candidate = discount.verificationUrl ?? discount.url
        guard let candidate else { return nil }
        return URL(string: candidate)
    }

    private var iconBadge: some View {
        ZStack {
            Circle()
                .fill(Color.barkainPrimaryFixed.opacity(0.7))
                .frame(width: 44, height: 44)
            Image(systemName: "tag.fill")
                .foregroundStyle(Color.barkainPrimary)
                .font(.system(size: 18, weight: .semibold))
        }
    }

    private var programLine: String {
        let details = discount.discountDetails
        if let details, !details.isEmpty { return details }
        return discount.programName
    }

    private var verificationBadge: String? {
        switch discount.verificationMethod {
        case "id_me": return "Verify with ID.me"
        case "sheer_id": return "Verify with SheerID"
        case "unidays": return "Verify with UNiDAYS"
        case "wesalute": return "Verify with WeSalute"
        case .some(let other): return "Verify with \(other)"
        case .none: return nil
        }
    }

    private var savingsLabel: some View {
        Text(savingsText)
            .font(.barkainHeadline)
            .foregroundStyle(Color.barkainPrimary)
    }

    private var savingsText: String {
        if let savings = discount.estimatedSavings, savings > 0 {
            return "Save \(formatCurrency(savings))"
        }
        if discount.discountType == "percentage", let value = discount.discountValue {
            if let max = discount.discountMaxValue, max > value {
                return "Up to \(Int(max))% off"
            }
            return "\(Int(value))% off"
        }
        if let value = discount.discountValue {
            return "$\(Int(value)) off"
        }
        return "View"
    }

    private func formatCurrency(_ amount: Double) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.maximumFractionDigits = 0
        return formatter.string(from: NSNumber(value: amount)) ?? "$\(Int(amount))"
    }

    private func openVerificationURL() {
        guard let url = resolvedURL else { return }
        onOpen(url)
    }
}

// MARK: - IdentityOnboardingCTARow

struct IdentityOnboardingCTARow: View {

    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: Spacing.sm) {
                Image(systemName: "sparkles")
                    .foregroundStyle(Color.barkainPrimary)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Unlock more savings")
                        .font(.barkainHeadline)
                        .foregroundStyle(Color.barkainOnSurface)
                    Text("Set up your identity profile to reveal exclusive brand discounts.")
                        .font(.barkainCaption)
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                        .multilineTextAlignment(.leading)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
                    .font(.caption)
            }
            .padding(Spacing.md)
            .background(Color.barkainPrimaryFixed.opacity(0.3))
            .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Preview

#Preview("Discounts section") {
    IdentityDiscountsSection(
        discounts: [
            EligibleDiscount(
                programId: UUID(),
                retailerId: "samsung_direct",
                retailerName: "Samsung.com",
                programName: "Samsung Offer Program",
                eligibilityType: "military",
                discountType: "percentage",
                discountValue: 30,
                discountMaxValue: nil,
                discountDetails: "Up to 30% off. 2 products per category per calendar year.",
                verificationMethod: "id_me",
                verificationUrl: "https://www.samsung.com/us/shop/offer-program/military",
                url: nil,
                estimatedSavings: 450
            ),
            EligibleDiscount(
                programId: UUID(),
                retailerId: "home_depot",
                retailerName: "Home Depot",
                programName: "Military Discount",
                eligibilityType: "veteran",
                discountType: "percentage",
                discountValue: 10,
                discountMaxValue: 400,
                discountDetails: "$400 annual cap. Most full-price products.",
                verificationMethod: "sheer_id",
                verificationUrl: "https://www.homedepot.com/c/military",
                url: nil,
                estimatedSavings: 400
            ),
        ],
        onOpen: { _ in }
    )
    .padding()
    .background(Color.barkainSurface)
}

#Preview("CTA row") {
    IdentityOnboardingCTARow(onTap: {})
        .padding()
        .background(Color.barkainSurface)
}
