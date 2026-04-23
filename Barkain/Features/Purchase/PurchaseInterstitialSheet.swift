import SwiftUI
import os

// MARK: - Logger

private let interstitialLog = Logger(
    subsystem: "com.barkain.app", category: "PurchaseInterstitial"
)

// MARK: - PurchaseInterstitialViewModel (Step 3f)

@Observable
final class PurchaseInterstitialViewModel {

    // MARK: - Properties

    let context: PurchaseInterstitialContext
    let apiClient: APIClientProtocol

    /// Flipped true after the user taps "Activate this bonus". The
    /// issuer's website is the source of truth for actual activation;
    /// we record only that the user visited it, not that they
    /// completed the flow.
    private(set) var activationAcknowledged: Bool = false

    // MARK: - Init

    init(context: PurchaseInterstitialContext, apiClient: APIClientProtocol) {
        self.context = context
        self.apiClient = apiClient
    }

    // MARK: - Actions

    /// User tapped "Activate this bonus →". Caller opens
    /// `context.activationUrl` in an `SFSafariViewController`. VM flips
    /// the acknowledged flag so the Continue click records
    /// `activation_skipped=false`.
    func acknowledgeActivation() {
        activationAcknowledged = true
    }

    /// User tapped "Continue to \(retailerName) →". Logs the affiliate
    /// click (with the activation-skipped telemetry) and returns the
    /// tagged URL for the caller to present in an in-app browser.
    /// Returns nil on failure — caller falls back to the untagged URL.
    func continueToRetailer() async -> URL? {
        let skipped = context.activationRequired && !activationAcknowledged
        do {
            let resp = try await apiClient.getAffiliateURL(
                productId: context.productId,
                retailerId: context.retailerId,
                productURL: context.productUrl,
                activationSkipped: skipped
            )
            return URL(string: resp.affiliateUrl)
        } catch {
            interstitialLog.error(
                "continueToRetailer failed: \(error.localizedDescription, privacy: .public)"
            )
            return URL(string: context.productUrl)
        }
    }

    /// Step 3g-B: user tapped a portal CTA row. Logs the affiliate click
    /// with the portal event-type/source so funnel analytics can split
    /// MEMBER_DEEPLINK detours, SIGNUP_REFERRAL conversions, and
    /// GUIDED_ONLY handoffs separately. Hands `cta.ctaUrl` to the in-app
    /// browser regardless of the click-log outcome — UX should not block
    /// on telemetry.
    func openPortal(cta: PortalCTA, onOpen: (URL) -> Void) async {
        Task {
            _ = try? await apiClient.getAffiliateURL(
                productId: context.productId,
                retailerId: context.retailerId,
                productURL: cta.ctaUrl,
                activationSkipped: false,
                portalEventType: cta.mode,
                portalSource: cta.portalSource
            )
        }
        if let url = URL(string: cta.ctaUrl) {
            onOpen(url)
        } else {
            interstitialLog.warning(
                "openPortal: invalid cta_url for portal=\(cta.portalSource, privacy: .public)"
            )
        }
    }

    // MARK: - Copy

    var baselineComparisonCopy: String {
        let baseline = PurchaseInterstitialContext.formatMoney(
            context.baselineOnePercentSavings
        )
        return "vs. \(baseline) with default card (1%)"
    }

    var savingsHeadline: String {
        "Total rewards: "
            + PurchaseInterstitialContext.formatMoney(context.cardSavings)
    }

    var continueButtonLabel: String {
        "Continue to \(context.retailerName) →"
    }
}

// MARK: - PurchaseInterstitialSheet (Step 3f)
//
// Slide-up sheet presented when the user taps the RecommendationHero
// action button or any PriceRow's Buy path. Shows which card to use at
// checkout, an activation reminder when needed, and the primary
// Continue button that hands off to the in-app browser.
//
// Data-in only — no fetches. If the sheet ever has to `await` during
// presentation, that's an architectural bug in 3f.

struct PurchaseInterstitialSheet: View {

    // MARK: - Properties

    @State var viewModel: PurchaseInterstitialViewModel
    let onDismiss: () -> Void
    let onOpenActivation: (URL) -> Void
    let onContinue: (URL) -> Void

    // MARK: - Init

    init(
        context: PurchaseInterstitialContext,
        apiClient: APIClientProtocol,
        onDismiss: @escaping () -> Void,
        onOpenActivation: @escaping (URL) -> Void,
        onContinue: @escaping (URL) -> Void
    ) {
        self._viewModel = State(
            wrappedValue: PurchaseInterstitialViewModel(
                context: context, apiClient: apiClient
            )
        )
        self.onDismiss = onDismiss
        self.onOpenActivation = onOpenActivation
        self.onContinue = onContinue
    }

    // MARK: - Body

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.lg) {
            header
            if viewModel.context.hasCardGuidance {
                cardBlock
                Divider()
                    .padding(.vertical, Spacing.xxs)
                summaryBlock
            } else {
                directPurchaseBlock
            }
            if !viewModel.context.portalCTAs.isEmpty {
                portalBlock
            }
            if viewModel.context.shouldShowActivationBlock {
                activationBlock
            }
            continueButton
        }
        .padding(Spacing.lg)
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .accessibilityIdentifier("purchaseInterstitialSheet")
    }

    // MARK: - Portal block (Step 3g-B)
    //
    // Renders ≤3 CTAs already sorted by the backend (rate desc, portal asc).
    // Top CTA bold; signup-promo amber line is conditional; FTC disclosure
    // ("Referral — Barkain earns a bonus if you sign up.") renders only on
    // SIGNUP_REFERRAL rows because that's the only mode that triggers
    // attribution. All disclosure copy is co-located with the link per FTC
    // guidance, not buried in a separate sheet.

    private var portalBlock: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            ForEach(Array(viewModel.context.portalCTAs.enumerated()), id: \.element.id) { idx, cta in
                portalRow(cta: cta, isTop: idx == 0)
            }
        }
        .padding(.vertical, Spacing.xs)
        .accessibilityIdentifier("purchaseInterstitialPortalBlock")
    }

    @ViewBuilder
    private func portalRow(cta: PortalCTA, isTop: Bool) -> some View {
        Button {
            Task { await viewModel.openPortal(cta: cta, onOpen: onContinue) }
        } label: {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                HStack(alignment: .firstTextBaseline) {
                    Text("+ \(cta.displayName) — \(formatPortalRate(cta.bonusRatePercent))")
                        .font(.barkainBody)
                        .fontWeight(isTop ? .semibold : .regular)
                        .foregroundStyle(Color.barkainOnSurface)
                    Spacer()
                    Image(systemName: "arrow.up.right")
                        .font(.system(size: 12))
                        .foregroundStyle(Color.barkainOnSurfaceVariant.opacity(0.6))
                }
                Text(cta.ctaLabel)
                    .font(.barkainCaption)
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
                if let promo = cta.signupPromoCopy {
                    Text(promo)
                        .font(.barkainCaption)
                        .foregroundStyle(Color.orange)
                }
                if cta.disclosureRequired {
                    Text("Referral — Barkain earns a bonus if you sign up.")
                        .font(.system(size: 11))
                        .foregroundStyle(Color.barkainOnSurfaceVariant.opacity(0.7))
                        .accessibilityIdentifier("purchaseInterstitialPortalDisclosure")
                }
            }
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("purchaseInterstitialPortalRow_\(cta.portalSource)")
    }

    private func formatPortalRate(_ rate: Double) -> String {
        if rate == rate.rounded() { return "\(Int(rate))%" }
        return String(format: "%.1f%%", rate)
    }

    // MARK: - Header

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(viewModel.context.productName)
                    .font(.barkainCaption)
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
                Text(headlineText)
                    .font(.barkainTitle2)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.barkainOnSurface)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("purchaseInterstitialCardHeadline")
            }
            Spacer(minLength: Spacing.sm)
            Button {
                onDismiss()
            } label: {
                Image(systemName: "xmark.circle.fill")
                    .font(.system(size: 24))
                    .foregroundStyle(Color.barkainOnSurfaceVariant.opacity(0.6))
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("purchaseInterstitialDismissButton")
        }
    }

    private var headlineText: String {
        if let card = viewModel.context.cardName {
            return "💳 Use your \(card)"
        }
        return "Heading to \(viewModel.context.retailerName)"
    }

    // MARK: - Card block (when a covering card exists)

    @ViewBuilder
    private var cardBlock: some View {
        if let rate = viewModel.context.cardRateLabel {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(rate)
                    .font(.barkainBody)
                    .foregroundStyle(Color.barkainOnSurface)
                Text(
                    "= "
                        + PurchaseInterstitialContext.formatMoney(
                            viewModel.context.cardSavings
                        )
                        + " cashback"
                )
                .font(.barkainBody)
                .fontWeight(.semibold)
                .foregroundStyle(Color.barkainPrimary)
            }
        }
    }

    // MARK: - Summary block

    private var summaryBlock: some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(viewModel.savingsHeadline)
                .font(.barkainHeadline)
                .foregroundStyle(Color.barkainOnSurface)
                .accessibilityIdentifier("purchaseInterstitialSavingsDelta")
            if viewModel.context.baselineOnePercentSavings > 0 {
                Text(viewModel.baselineComparisonCopy)
                    .font(.barkainCaption)
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
            }
        }
    }

    // MARK: - Direct purchase (no card match)

    private var directPurchaseBlock: some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(
                "Price: "
                    + PurchaseInterstitialContext.formatMoney(
                        viewModel.context.basePrice
                    )
            )
            .font(.barkainHeadline)
            .foregroundStyle(Color.barkainOnSurface)
            Text("No card bonus for this retailer — add one in Profile.")
                .font(.barkainCaption)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
        }
    }

    // MARK: - Activation block

    private var activationBlock: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.xs) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(Color.orange)
                Text("Activate this quarter's category first")
                    .font(.barkainBody)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.barkainOnSurface)
            }
            Text(
                "The 5% bonus only applies after you activate the category "
                    + "on the issuer's site."
            )
            .font(.barkainCaption)
            .foregroundStyle(Color.barkainOnSurfaceVariant)
            .fixedSize(horizontal: false, vertical: true)
            Button {
                guard let urlString = viewModel.context.activationUrl,
                    let url = URL(string: urlString)
                else { return }
                viewModel.acknowledgeActivation()
                onOpenActivation(url)
            } label: {
                HStack {
                    Text("Activate this bonus")
                        .font(.barkainBody)
                        .fontWeight(.semibold)
                    Spacer()
                    Image(systemName: "arrow.up.right.square")
                }
                .foregroundStyle(Color.barkainPrimary)
                .padding(.vertical, Spacing.xs)
                .padding(.horizontal, Spacing.sm)
                .frame(maxWidth: .infinity)
                .background(Color.barkainPrimary.opacity(0.1))
                .clipShape(
                    RoundedRectangle(
                        cornerRadius: Spacing.cornerRadius,
                        style: .continuous
                    )
                )
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("purchaseInterstitialActivateButton")
        }
        .padding(Spacing.sm)
        .background(Color.orange.opacity(0.08))
        .clipShape(
            RoundedRectangle(
                cornerRadius: Spacing.cornerRadius,
                style: .continuous
            )
        )
    }

    // MARK: - Continue button

    private var continueButton: some View {
        Button {
            Task {
                if let url = await viewModel.continueToRetailer() {
                    onContinue(url)
                }
            }
        } label: {
            HStack {
                Text(viewModel.continueButtonLabel)
                    .font(.barkainHeadline)
                    .fontWeight(.semibold)
                Spacer()
                Image(systemName: "arrow.up.right")
            }
            .foregroundStyle(.white)
            .padding(.vertical, Spacing.sm)
            .padding(.horizontal, Spacing.md)
            .frame(maxWidth: .infinity)
            .background(Color.barkainPrimaryGradient)
            .clipShape(
                RoundedRectangle(
                    cornerRadius: Spacing.cornerRadiusLarge,
                    style: .continuous
                )
            )
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("purchaseInterstitialContinueButton")
    }
}

// MARK: - Preview

#Preview("With activation reminder") {
    VStack {}
        .sheet(isPresented: .constant(true)) {
            PurchaseInterstitialSheet(
                context: PurchaseInterstitialContext(
                    winner: StackedPath(
                        retailerId: "amazon",
                        retailerName: "Amazon",
                        basePrice: 499.00,
                        finalPrice: 499.00,
                        effectiveCost: 474.05,
                        totalSavings: 24.95,
                        identitySavings: 0,
                        identitySource: nil,
                        cardSavings: 24.95,
                        cardSource: "Chase Freedom Flex",
                        portalSavings: 0,
                        portalSource: nil,
                        condition: "new",
                        productUrl: "https://www.amazon.com/dp/B0C33XXXXX"
                    ),
                    productId: UUID(),
                    productName: "Sony WH-1000XM5",
                    cards: [
                        CardRecommendation(
                            retailerId: "amazon",
                            retailerName: "Amazon",
                            userCardId: UUID(),
                            cardProgramId: UUID(),
                            cardDisplayName: "Chase Freedom Flex",
                            cardIssuer: "chase",
                            rewardRate: 5.0,
                            rewardAmount: 24.95,
                            rewardCurrency: "ultimate_rewards",
                            isRotatingBonus: true,
                            isUserSelectedBonus: false,
                            activationRequired: true,
                            activationUrl:
                                "https://chase.com/activate/freedom-flex"
                        )
                    ]
                ),
                apiClient: BarePreviewAPIClient(),
                onDismiss: {},
                onOpenActivation: { _ in },
                onContinue: { _ in }
            )
        }
}
