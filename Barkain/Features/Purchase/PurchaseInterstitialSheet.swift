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
