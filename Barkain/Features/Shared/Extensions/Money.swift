import Foundation

// MARK: - Money formatting (savings-math-prominence Item 3)
//
// Single canonical money formatter. Per the pack copy rule, whole-dollar
// amounts render without trailing zeros ("$47" not "$47.00") while
// fractional amounts always show two decimals ("$47.99"). Three call
// sites had drift-prone copies of this logic before — RecommendationHero,
// PurchaseInterstitialContext, StackingReceiptView — and they used to
// disagree on formatter config; consolidating here pins them.

enum Money {

    /// Render a USD amount with the demo-ready convention:
    ///   - 47.0 → "$47"
    ///   - 47.5 → "$47.50"
    ///   - 47.99 → "$47.99"
    /// Negative values are returned with the leading "-$" the
    /// NumberFormatter applies; callers that need a UI-tone "−" prefix
    /// (e.g. receipt discount lines) format the absolute value and
    /// prepend the symbol themselves.
    static func format(_ value: Double) -> String {
        let formatter = isWholeDollar(value) ? wholeDollarFormatter : centsFormatter
        return formatter.string(from: NSNumber(value: value)) ?? "$\(value)"
    }

    private static func isWholeDollar(_ value: Double) -> Bool {
        value.rounded(.toNearestOrEven) == value
    }

    private static let wholeDollarFormatter: NumberFormatter = {
        let f = NumberFormatter()
        f.numberStyle = .currency
        f.currencyCode = "USD"
        f.maximumFractionDigits = 0
        f.minimumFractionDigits = 0
        return f
    }()

    private static let centsFormatter: NumberFormatter = {
        let f = NumberFormatter()
        f.numberStyle = .currency
        f.currencyCode = "USD"
        f.maximumFractionDigits = 2
        f.minimumFractionDigits = 2
        return f
    }()
}
