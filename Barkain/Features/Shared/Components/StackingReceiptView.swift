import SwiftUI

// MARK: - StackingReceiptView (savings-math-prominence Item 2)
//
// Canonical receipt for the stacking math. Single source of truth so the
// hero, the purchase interstitial, and any future post-purchase confirm
// view all read the math the same way.
//
// Input is a plain value type (`StackingReceipt`) so the view doesn't
// depend on `StackedPath` or `PurchaseInterstitialContext` directly —
// either can build one. Zero-discount lines suppress; a receipt with
// no discounts at all returns nil from `hasAnyDiscount` and the caller
// is expected not to render the view in that case.
//
// Typography: monospaced digits for decimal alignment (so line items
// stack neatly even when amounts vary in width). Numbers are never
// negative-formatted — the leading "−" is hard-coded so the
// NumberFormatter doesn't have to special-case sign placement.

// MARK: - Receipt model

nonisolated struct StackingReceipt: Equatable, Hashable, Sendable {

    let retailPrice: Double
    let identitySavings: Double
    let identitySource: String?
    let portalSavings: Double
    let portalSource: String?
    let cardSavings: Double
    let cardSource: String?
    let yourPrice: Double

    /// True when at least one discount line is non-zero — caller uses
    /// this to decide whether to render the receipt at all (a stripped
    /// receipt with only retail + your-price would just duplicate the
    /// hero line and add visual noise).
    var hasAnyDiscount: Bool {
        identitySavings + portalSavings + cardSavings > 0
    }

    // MARK: - Conveniences

    /// Build from a recommendation winner (or any other StackedPath).
    /// `effectiveCost` is the post-rebate price the M6 service computes
    /// — what the user actually pays after card + portal cashback.
    init(stackedPath: StackedPath) {
        self.retailPrice = stackedPath.basePrice
        self.identitySavings = stackedPath.identitySavings
        self.identitySource = stackedPath.identitySource
        self.portalSavings = stackedPath.portalSavings
        self.portalSource = stackedPath.portalSource
        self.cardSavings = stackedPath.cardSavings
        self.cardSource = stackedPath.cardSource
        self.yourPrice = stackedPath.effectiveCost
    }

    /// Build from the purchase interstitial context. The price-row entry
    /// path (non-winner retailer tap) has no identity / portal data — the
    /// stacking math only exists on the recommendation winner — so those
    /// fields default to zero and the corresponding lines suppress.
    init(interstitialContext context: PurchaseInterstitialContext) {
        self.retailPrice = context.basePrice
        self.identitySavings = context.identitySavings
        self.identitySource = context.identitySource
        self.portalSavings = context.portalSavings
        self.portalSource = context.portalSource
        self.cardSavings = context.cardSavings
        self.cardSource = context.cardName
        self.yourPrice = context.basePrice
            - context.identitySavings
            - context.portalSavings
            - context.cardSavings
    }

    /// Memberwise init kept for tests + previews.
    init(
        retailPrice: Double,
        identitySavings: Double = 0,
        identitySource: String? = nil,
        portalSavings: Double = 0,
        portalSource: String? = nil,
        cardSavings: Double = 0,
        cardSource: String? = nil,
        yourPrice: Double
    ) {
        self.retailPrice = retailPrice
        self.identitySavings = identitySavings
        self.identitySource = identitySource
        self.portalSavings = portalSavings
        self.portalSource = portalSource
        self.cardSavings = cardSavings
        self.cardSource = cardSource
        self.yourPrice = yourPrice
    }
}

// MARK: - View

struct StackingReceiptView: View {

    let receipt: StackingReceipt

    var body: some View {
        VStack(spacing: Spacing.xs) {
            line(
                label: "Retail price",
                amount: receipt.retailPrice,
                isDiscount: false
            )
            if receipt.identitySavings > 0, let label = receipt.identitySource {
                line(label: label, amount: receipt.identitySavings, isDiscount: true)
            }
            if receipt.portalSavings > 0, let label = receipt.portalSource {
                line(label: "\(label) portal", amount: receipt.portalSavings, isDiscount: true)
            }
            if receipt.cardSavings > 0, let label = receipt.cardSource {
                line(label: label, amount: receipt.cardSavings, isDiscount: true)
            }
            Divider()
                .padding(.vertical, 2)
            line(
                label: "Your price",
                amount: receipt.yourPrice,
                isDiscount: false,
                emphasis: true
            )
        }
        .padding(.vertical, Spacing.xs)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityDescription)
        .accessibilityIdentifier("stackingReceiptView")
    }

    // MARK: - Row builder

    @ViewBuilder
    private func line(
        label: String,
        amount: Double,
        isDiscount: Bool,
        emphasis: Bool = false
    ) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label)
                .font(.barkainBody)
                .fontWeight(emphasis ? .semibold : .regular)
                .foregroundStyle(
                    emphasis ? Color.barkainOnSurface : Color.barkainOnSurfaceVariant
                )
                .lineLimit(1)
                .truncationMode(.tail)
            Spacer(minLength: Spacing.sm)
            Text(formatAmount(amount, isDiscount: isDiscount))
                .font(.system(.body, design: .monospaced))
                .fontWeight(emphasis ? .semibold : .regular)
                .foregroundStyle(
                    isDiscount ? Color.barkainPrimary : Color.barkainOnSurface
                )
        }
    }

    // MARK: - Formatting

    private func formatAmount(_ value: Double, isDiscount: Bool) -> String {
        let absoluteString = Money.format(value)
        return isDiscount ? "−\(absoluteString)" : absoluteString
    }

    // MARK: - Accessibility

    private var accessibilityDescription: String {
        var parts = ["Retail price \(receipt.retailPrice) dollars"]
        if receipt.identitySavings > 0, let src = receipt.identitySource {
            parts.append("\(src) saves \(receipt.identitySavings) dollars")
        }
        if receipt.portalSavings > 0, let src = receipt.portalSource {
            parts.append("\(src) portal saves \(receipt.portalSavings) dollars")
        }
        if receipt.cardSavings > 0, let src = receipt.cardSource {
            parts.append("\(src) saves \(receipt.cardSavings) dollars")
        }
        parts.append("Your price \(receipt.yourPrice) dollars")
        return parts.joined(separator: ", ")
    }
}
