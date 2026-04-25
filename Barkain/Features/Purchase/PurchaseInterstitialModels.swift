import Foundation

// MARK: - PurchaseInterstitialContext (Step 3f)
//
// All data the interstitial sheet needs to render is resolved at the call
// site — the sheet itself never fetches. Value type so SwiftUI's
// `.sheet(item:)` treats identical-content context as the same
// presentation (no flicker when the parent view re-evaluates).
//
// Constructed from either (a) the 3e Recommendation winner plus the
// matched CardRecommendation, or (b) a PriceRow + its CardRecommendation
// for the secondary "tap any retailer" entry path.

nonisolated struct PurchaseInterstitialContext: Identifiable, Equatable, Hashable, Sendable {

    // MARK: - Identity

    /// `.sheet(item:)` needs a stable id. Retailer + user_card combo is
    /// unique per interstitial presentation, so reusing the same pair
    /// is a "same sheet" intent (avoids SwiftUI recreating the view).
    var id: String { "\(retailerId)-\(userCardId?.uuidString ?? "none")" }

    // MARK: - Product + retailer

    let productId: UUID?
    let productName: String
    let retailerId: String
    let retailerName: String
    let productUrl: String
    let basePrice: Double

    // MARK: - Card

    /// Nil when the tapped retailer has no matching user card (secondary
    /// entry path on an uncovered row). Interstitial hides the card block
    /// and shows only Continue.
    let userCardId: UUID?
    let cardName: String?
    let cardRateLabel: String?
    let cardSavings: Double
    let activationRequired: Bool
    let activationUrl: String?

    // MARK: - Identity + portal (savings-math-prominence Item 2)
    //
    // Carried so the canonical `StackingReceiptView` can render the full
    // breakdown in the interstitial without re-fetching. Populated only
    // on the recommendation-winner init path; the price-row entry path
    // (non-winner retailer tap) sets these to zero/nil because the M6
    // stacking math only exists on the winner.

    let identitySavings: Double
    let identitySource: String?
    let portalSavings: Double
    let portalSource: String?

    // MARK: - Portal CTAs (Step 3g-B)

    /// Up to 3 portal CTAs sorted by bonus rate descending. Pre-populated
    /// when built from the Recommendation winner; defaults [] for the
    /// price-row entry path (the VM may fetch on demand via
    /// `POST /api/v1/portal/cta` after presentation — Group 6).
    let portalCTAs: [PortalCTA]

    // MARK: - Init — Recommendation winner path

    /// Build from the 3e Recommendation winner. `cards` is the same list
    /// already loaded by the scanner/search VM (M5 `/cards/recommendations`).
    /// Matches on `retailer_id` + `cardSource == card_display_name` —
    /// both come from the same deterministic pipeline so equality holds.
    init(
        winner: StackedPath,
        productId: UUID?,
        productName: String,
        cards: [CardRecommendation]
    ) {
        self.productId = productId
        self.productName = productName
        self.retailerId = winner.retailerId
        self.retailerName = winner.retailerName
        self.productUrl = winner.productUrl ?? ""
        self.basePrice = winner.basePrice

        let match = cards.first {
            $0.retailerId == winner.retailerId
                && $0.cardDisplayName == winner.cardSource
        }
        self.userCardId = match?.userCardId
        self.cardName = match?.cardDisplayName
        self.cardSavings = winner.cardSavings
        self.cardRateLabel = match.map { card in
            let currency = card.rewardCurrency.replacingOccurrences(of: "_", with: " ")
            return "\(Self.formatRate(card.rewardRate)) back (\(currency))"
        }
        self.activationRequired = match?.activationRequired ?? false
        self.activationUrl = match?.activationUrl
        // savings-math-prominence Item 2 — winner carries the full M6
        // stacking math; receipt reads from these fields in the
        // interstitial just like the hero does.
        self.identitySavings = winner.identitySavings
        self.identitySource = winner.identitySource
        self.portalSavings = winner.portalSavings
        self.portalSource = winner.portalSource
        // Step 3g-B — winner carries the resolved portal CTAs from M6.
        // StackedPath uses lowercase `portalCtas` to round-trip through
        // `.convertFromSnakeCase`; the context type keeps the canonical
        // Swift acronym style.
        self.portalCTAs = winner.portalCtas
    }

    // MARK: - Init — Price row path

    /// Build from a retailer row tap. `card` may be nil on uncovered rows.
    init(
        price: RetailerPrice,
        productId: UUID?,
        productName: String,
        card: CardRecommendation?,
        portalCTAs: [PortalCTA] = []
    ) {
        self.productId = productId
        self.productName = productName
        self.retailerId = price.retailerId
        self.retailerName = price.retailerName
        self.productUrl = price.url ?? ""
        self.basePrice = price.price

        self.userCardId = card?.userCardId
        self.cardName = card?.cardDisplayName
        self.cardSavings = card?.rewardAmount ?? 0.0
        self.cardRateLabel = card.map {
            "\(Self.formatRate($0.rewardRate)) back"
        }
        self.activationRequired = card?.activationRequired ?? false
        self.activationUrl = card?.activationUrl
        // savings-math-prominence Item 2 — non-winner rows have no
        // identity / portal stacking. Zeros suppress those receipt lines.
        self.identitySavings = 0
        self.identitySource = nil
        self.portalSavings = 0
        self.portalSource = nil
        self.portalCTAs = portalCTAs
    }

    // MARK: - Formatting helpers

    static func formatRate(_ rate: Double) -> String {
        if rate == rate.rounded() {
            return "\(Int(rate))%"
        }
        return String(format: "%.1f%%", rate)
    }

    static func formatMoney(_ value: Double) -> String {
        Money.format(value)
    }

    // MARK: - Derived

    /// Conservative 1% baseline — "vs. your default card" comparison.
    /// See Step 3f Design doc: real per-user default-card math is
    /// low-value complexity for the demo.
    var baselineOnePercentSavings: Double {
        basePrice * 0.01
    }

    /// True when the card block should render with savings copy. Hidden
    /// when the row had no covering card.
    var hasCardGuidance: Bool {
        cardName != nil && cardSavings > 0
    }

    /// True when the activation reminder row should render.
    var shouldShowActivationBlock: Bool {
        activationRequired && activationUrl != nil
    }
}
