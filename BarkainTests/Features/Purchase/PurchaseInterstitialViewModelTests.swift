import Foundation
import Testing
@testable import Barkain

// MARK: - Fixtures

private func makeCard(
    retailerId: String = "amazon",
    displayName: String = "Chase Freedom Flex",
    rate: Double = 5.0,
    amount: Double = 24.95,
    activationRequired: Bool = true,
    activationUrl: String? = "https://chase.com/activate"
) -> CardRecommendation {
    CardRecommendation(
        retailerId: retailerId,
        retailerName: retailerId.capitalized,
        userCardId: UUID(),
        cardProgramId: UUID(),
        cardDisplayName: displayName,
        cardIssuer: "chase",
        rewardRate: rate,
        rewardAmount: amount,
        rewardCurrency: "ultimate_rewards",
        isRotatingBonus: activationRequired,
        isUserSelectedBonus: false,
        activationRequired: activationRequired,
        activationUrl: activationUrl
    )
}

private func makeWinner(
    retailerId: String = "amazon",
    basePrice: Double = 499.0,
    cardSavings: Double = 24.95,
    cardSource: String? = "Chase Freedom Flex"
) -> StackedPath {
    StackedPath(
        retailerId: retailerId,
        retailerName: retailerId.capitalized,
        basePrice: basePrice,
        finalPrice: basePrice,
        effectiveCost: basePrice - cardSavings,
        totalSavings: cardSavings,
        identitySavings: 0,
        identitySource: nil,
        cardSavings: cardSavings,
        cardSource: cardSource,
        portalSavings: 0,
        portalSource: nil,
        condition: "new",
        productUrl: "https://www.amazon.com/dp/B0C33XXXXX"
    )
}

private func makeContext(
    withCard card: CardRecommendation? = makeCard()
) -> PurchaseInterstitialContext {
    PurchaseInterstitialContext(
        winner: makeWinner(),
        productId: UUID(),
        productName: "Sony WH-1000XM5",
        cards: card.map { [$0] } ?? []
    )
}

// MARK: - ViewModel tests

@Suite("PurchaseInterstitialViewModel")
struct PurchaseInterstitialViewModelTests {

    @Test("activationAcknowledged starts false and flips after acknowledge")
    func acknowledgeFlipsFlag() async {
        let vm = PurchaseInterstitialViewModel(
            context: makeContext(),
            apiClient: MockAPIClient()
        )
        #expect(vm.activationAcknowledged == false)
        vm.acknowledgeActivation()
        #expect(vm.activationAcknowledged == true)
    }

    @Test("continueToRetailer records activation_skipped=true when not acknowledged and activation required")
    func continueWithoutActivationRecordsSkipped() async {
        let mock = MockAPIClient()
        mock.getAffiliateURLResult = .success(
            AffiliateURLResponse(
                affiliateUrl: "https://www.amazon.com/dp/X?tag=barkain-20",
                isAffiliated: true,
                network: "amazon_associates",
                retailerId: "amazon"
            )
        )
        let vm = PurchaseInterstitialViewModel(
            context: makeContext(),
            apiClient: mock
        )
        _ = await vm.continueToRetailer()
        #expect(mock.getAffiliateURLLastActivationSkipped == true)
    }

    @Test("continueToRetailer records activation_skipped=false after acknowledge")
    func continueAfterActivationRecordsNotSkipped() async {
        let mock = MockAPIClient()
        mock.getAffiliateURLResult = .success(
            AffiliateURLResponse(
                affiliateUrl: "https://www.amazon.com/dp/X?tag=barkain-20",
                isAffiliated: true,
                network: "amazon_associates",
                retailerId: "amazon"
            )
        )
        let vm = PurchaseInterstitialViewModel(
            context: makeContext(),
            apiClient: mock
        )
        vm.acknowledgeActivation()
        _ = await vm.continueToRetailer()
        #expect(mock.getAffiliateURLLastActivationSkipped == false)
    }

    @Test("continueToRetailer records activation_skipped=false when activation not required")
    func continueWithoutActivationRequired() async {
        let mock = MockAPIClient()
        mock.getAffiliateURLResult = .success(
            AffiliateURLResponse(
                affiliateUrl: "https://www.amazon.com/dp/X",
                isAffiliated: false,
                network: nil,
                retailerId: "amazon"
            )
        )
        let cardNoActivation = makeCard(activationRequired: false, activationUrl: nil)
        let vm = PurchaseInterstitialViewModel(
            context: makeContext(withCard: cardNoActivation),
            apiClient: mock
        )
        _ = await vm.continueToRetailer()
        #expect(mock.getAffiliateURLLastActivationSkipped == false)
    }

    @Test("baseline 1 percent delta is computed from base price")
    func baselineOnePercent() {
        let ctx = makeContext()
        #expect(ctx.baselineOnePercentSavings == 4.99)
    }
}

// MARK: - Sheet render-model tests (no ViewInspector — state-assertion only)

@Suite("PurchaseInterstitialSheet render model")
struct PurchaseInterstitialSheetRenderTests {

    @Test("shouldShowActivationBlock is false when activation not required")
    func hidesActivationBlockWhenNotRequired() {
        let card = makeCard(activationRequired: false, activationUrl: nil)
        let ctx = makeContext(withCard: card)
        #expect(ctx.shouldShowActivationBlock == false)
    }

    @Test("shouldShowActivationBlock is true when required and url present")
    func showsActivationBlockWhenRequired() {
        let ctx = makeContext()
        #expect(ctx.shouldShowActivationBlock == true)
    }

    @Test("hasCardGuidance false on uncovered rows")
    func directPurchaseWhenNoCard() {
        let ctx = PurchaseInterstitialContext(
            winner: makeWinner(cardSavings: 0, cardSource: nil),
            productId: UUID(),
            productName: "Sony WH-1000XM5",
            cards: []
        )
        #expect(ctx.hasCardGuidance == false)
    }

    @Test("continueButtonLabel includes retailer name")
    func continueLabelContainsRetailer() {
        let vm = PurchaseInterstitialViewModel(
            context: makeContext(),
            apiClient: MockAPIClient()
        )
        #expect(vm.continueButtonLabel.contains("Amazon"))
    }
}
