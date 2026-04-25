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

    @Test("Portal-only winner without a card still surfaces the receipt")
    func receiptRendersWithoutCardWhenPortalSavingsExist() {
        // Demo path: hero promises "$205.79 at eBay" via Befrugal portal
        // cashback. User has no card on file (skipped onboarding). The
        // interstitial must still show the receipt or the user lands on
        // a sheet that contradicts the hero.
        let portalOnlyWinner = StackedPath(
            retailerId: "ebay_used",
            retailerName: "eBay (Used/Refurb)",
            basePrice: 209.99,
            finalPrice: 209.99,
            effectiveCost: 205.79,
            totalSavings: 4.20,
            identitySavings: 0,
            identitySource: nil,
            cardSavings: 0,
            cardSource: nil,
            portalSavings: 4.20,
            portalSource: "befrugal",
            condition: "used",
            productUrl: "https://www.ebay.com/itm/X"
        )
        let ctx = PurchaseInterstitialContext(
            winner: portalOnlyWinner,
            productId: UUID(),
            productName: "Apple MacBook Air M1",
            cards: []
        )
        #expect(ctx.hasCardGuidance == false)

        let receipt = StackingReceipt(interstitialContext: ctx)
        #expect(receipt.hasAnyDiscount == true)
        #expect(receipt.portalSavings == 4.20)
        #expect(receipt.portalSource == "befrugal")
        #expect(abs(receipt.yourPrice - 205.79) < 0.005)
    }

    @Test("Identity-only winner without a card still surfaces the receipt")
    func receiptRendersWithoutCardWhenIdentitySavingsExist() {
        let identityOnlyWinner = StackedPath(
            retailerId: "best_buy",
            retailerName: "Best Buy",
            basePrice: 100.00,
            finalPrice: 90.00,
            effectiveCost: 90.00,
            totalSavings: 10.00,
            identitySavings: 10.00,
            identitySource: "Student",
            cardSavings: 0,
            cardSource: nil,
            portalSavings: 0,
            portalSource: nil,
            condition: "new",
            productUrl: "https://www.bestbuy.com/X"
        )
        let ctx = PurchaseInterstitialContext(
            winner: identityOnlyWinner,
            productId: UUID(),
            productName: "Sony WH-1000XM5",
            cards: []
        )
        #expect(ctx.hasCardGuidance == false)

        let receipt = StackingReceipt(interstitialContext: ctx)
        #expect(receipt.hasAnyDiscount == true)
        #expect(receipt.identitySavings == 10.00)
        #expect(receipt.identitySource == "Student")
    }

    @Test("No card and no stack falls back to direct-purchase copy")
    func directPurchaseWhenNothingToStack() {
        let bareWinner = makeWinner(cardSavings: 0, cardSource: nil)
        let ctx = PurchaseInterstitialContext(
            winner: bareWinner,
            productId: UUID(),
            productName: "Sony WH-1000XM5",
            cards: []
        )
        #expect(ctx.hasCardGuidance == false)
        let receipt = StackingReceipt(interstitialContext: ctx)
        #expect(receipt.hasAnyDiscount == false)
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

// MARK: - Portal CTA tests (Step 3g-B)

private func makePortalCTA(
    portalSource: String = "rakuten",
    mode: String = "member_deeplink",
    rate: Double = 3.0,
    disclosureRequired: Bool = false,
    signupPromoCopy: String? = nil
) -> PortalCTA {
    PortalCTA(
        portalSource: portalSource,
        displayName: portalSource.capitalized,
        mode: mode,
        bonusRatePercent: rate,
        bonusIsElevated: false,
        ctaUrl: "https://www.\(portalSource).com/store/X",
        ctaLabel: "Open \(portalSource.capitalized) for \(Int(rate))% back",
        signupPromoCopy: signupPromoCopy,
        lastVerified: Date(),
        disclosureRequired: disclosureRequired
    )
}

private func makeWinnerWithPortals(_ ctas: [PortalCTA]) -> StackedPath {
    StackedPath(
        retailerId: "amazon",
        retailerName: "Amazon",
        basePrice: 100,
        finalPrice: 100,
        effectiveCost: 100,
        totalSavings: 0,
        portalCtas: ctas
    )
}

@Suite("PurchaseInterstitialContext + sheet portal row")
struct PurchaseInterstitialPortalTests {

    @Test("Winner-init populates portalCTAs from StackedPath")
    func winnerInitPropagatesCTAs() {
        let ctas = [makePortalCTA(portalSource: "rakuten")]
        let ctx = PurchaseInterstitialContext(
            winner: makeWinnerWithPortals(ctas),
            productId: UUID(),
            productName: "Sony WH-1000XM5",
            cards: []
        )
        #expect(ctx.portalCTAs.count == 1)
        #expect(ctx.portalCTAs.first?.portalSource == "rakuten")
    }

    @Test("Price-row init defaults portalCTAs to empty (filled on demand)")
    func priceRowInitDefaultsCTAsToEmpty() {
        let price = RetailerPrice(
            retailerId: "amazon",
            retailerName: "Amazon",
            price: 99.00,
            url: nil,
            condition: "new",
            lastChecked: Date()
        )
        let ctx = PurchaseInterstitialContext(
            price: price,
            productId: UUID(),
            productName: "Sony WH-1000XM5",
            card: nil
        )
        #expect(ctx.portalCTAs.isEmpty)
    }

    @Test("openPortal logs the click with portal_event_type + portal_source")
    func openPortalSendsAffiliateClickWithPortalMetadata() async {
        let mock = MockAPIClient()
        mock.getAffiliateURLResult = .success(
            AffiliateURLResponse(
                affiliateUrl: "https://www.rakuten.com/r/X",
                isAffiliated: false,
                network: nil,
                retailerId: "amazon"
            )
        )
        let cta = makePortalCTA(portalSource: "rakuten", mode: "signup_referral")
        let ctx = PurchaseInterstitialContext(
            winner: makeWinnerWithPortals([cta]),
            productId: UUID(),
            productName: "Sony WH-1000XM5",
            cards: []
        )
        let vm = PurchaseInterstitialViewModel(context: ctx, apiClient: mock)

        var openedURL: URL?
        await vm.openPortal(cta: cta) { url in openedURL = url }

        // openPortal hands the URL to the caller synchronously regardless of
        // the click-log outcome — UX must not block on telemetry.
        #expect(openedURL != nil)

        // The click is fire-and-forget via Task — give it a tick to land.
        try? await Task.sleep(for: .milliseconds(50))
        #expect(mock.getAffiliateURLLastPortalEventType == "signup_referral")
        #expect(mock.getAffiliateURLLastPortalSource == "rakuten")
    }

    @Test("Multi-portal context preserves backend-provided sort order")
    func multiPortalSortPreserved() {
        // Backend sorts (rate desc, portal_source asc); iOS must NOT re-sort.
        let ctas = [
            makePortalCTA(portalSource: "topcashback", rate: 4.0),
            makePortalCTA(portalSource: "befrugal", rate: 2.5),
            makePortalCTA(portalSource: "rakuten", rate: 1.0),
        ]
        let ctx = PurchaseInterstitialContext(
            winner: makeWinnerWithPortals(ctas),
            productId: UUID(),
            productName: "Sony WH-1000XM5",
            cards: []
        )
        #expect(ctx.portalCTAs.map(\.portalSource) == ["topcashback", "befrugal", "rakuten"])
    }

    @Test("Disclosure flag is per-CTA, not all-or-nothing")
    func disclosurePerCTA() {
        let ctas = [
            makePortalCTA(portalSource: "rakuten", mode: "signup_referral", disclosureRequired: true),
            makePortalCTA(portalSource: "befrugal", mode: "member_deeplink", disclosureRequired: false),
        ]
        let ctx = PurchaseInterstitialContext(
            winner: makeWinnerWithPortals(ctas),
            productId: UUID(),
            productName: "Sony WH-1000XM5",
            cards: []
        )
        #expect(ctx.portalCTAs[0].disclosureRequired == true)
        #expect(ctx.portalCTAs[1].disclosureRequired == false)
    }
}
