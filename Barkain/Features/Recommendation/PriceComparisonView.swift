import SwiftUI

// MARK: - RetailerListRow

private enum RetailerListRow: Identifiable {
    case success(RetailerPrice)
    case noMatch(RetailerResult)
    case unavailable(RetailerResult)

    var id: String {
        switch self {
        case .success(let price): return "s-" + price.id
        case .noMatch(let result): return "n-" + result.retailerId
        case .unavailable(let result): return "u-" + result.retailerId
        }
    }
}

// MARK: - PriceComparisonView

struct PriceComparisonView: View {

    // MARK: - Properties

    let product: Product
    let comparison: PriceComparison
    let viewModel: ScannerViewModel
    var onRequestOnboarding: (() -> Void)? = nil
    var onRequestAddCards: (() -> Void)? = nil
    var onRequestUpgrade: (() -> Void)? = nil

    @Environment(FeatureGateService.self) private var featureGate

    @AppStorage("hasCompletedIdentityOnboarding")
    private var hasCompletedOnboarding: Bool = false

    // Step 2g: in-app browser sheet for retailer + identity discount taps.
    // Both flows funnel through this single state so only one sheet is
    // presented at a time.
    @State private var browserURL: IdentifiableURL?

    // MARK: - Body

    var body: some View {
        ScrollView {
            VStack(spacing: Spacing.lg) {
                ProductCard(product: product)
                savingsSection

                identityDiscountsSection

                sectionHeader
                cardUpgradeBanner
                retailerList

                addCardsCTA
                statusBar
                actionButtons
            }
            .padding(Spacing.lg)
            .animation(.easeInOut(duration: 0.3), value: viewModel.identityDiscounts)
            .animation(.easeInOut(duration: 0.3), value: viewModel.cardRecommendations)
        }
        .sheet(item: $browserURL) { item in
            InAppBrowserView(url: item.url)
                .ignoresSafeArea()
        }
    }

    // MARK: - Card upgrade banner (Step 2f)
    //
    // Single banner shown to free users who have matching card recs they
    // can't see. Free users also get nil card subtitles on each PriceRow
    // (handled below in the retailer list builder).

    @ViewBuilder
    private var cardUpgradeBanner: some View {
        if !featureGate.canAccess(.cardRecommendations)
            && !viewModel.cardRecommendations.isEmpty {
            UpgradeCardsBanner { onRequestUpgrade?() }
                .transition(.opacity)
        }
    }

    // MARK: - Card CTA (Step 2e)

    @ViewBuilder
    private var addCardsCTA: some View {
        if !viewModel.userHasCards && viewModel.cardRecommendations.isEmpty {
            Button {
                onRequestAddCards?()
            } label: {
                HStack(spacing: Spacing.sm) {
                    Image(systemName: "creditcard.and.123")
                        .foregroundStyle(Color.barkainPrimary)
                    VStack(alignment: .leading, spacing: Spacing.xxs) {
                        Text("Add your cards")
                            .font(.barkainHeadline)
                            .foregroundStyle(Color.barkainOnSurface)
                        Text("See which card earns the most at each retailer.")
                            .font(.barkainCaption)
                            .foregroundStyle(Color.barkainOnSurfaceVariant)
                    }
                    Spacer()
                    Image(systemName: "chevron.right")
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                }
                .padding(Spacing.md)
                .background(Color.barkainPrimaryFixed.opacity(0.3))
                .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous))
            }
            .buttonStyle(.plain)
            .transition(.opacity.combined(with: .scale(scale: 0.95)))
        }
    }

    // MARK: - Identity Discounts (Step 2d + 2f gate)

    @ViewBuilder
    private var identityDiscountsSection: some View {
        if !viewModel.identityDiscounts.isEmpty {
            // Step 2f: free users see at most `freeIdentityDiscountLimit`
            // discounts. The slice happens here so IdentityDiscountsSection
            // stays presentation-only — it doesn't need to know about
            // billing tiers.
            VStack(spacing: Spacing.sm) {
                IdentityDiscountsSection(
                    discounts: visibleIdentityDiscounts,
                    onOpen: { browserURL = IdentifiableURL(url: $0) }
                )
                if hiddenIdentityDiscountCount > 0 {
                    UpgradeLockedDiscountsRow(
                        hiddenCount: hiddenIdentityDiscountCount
                    ) {
                        onRequestUpgrade?()
                    }
                }
            }
            .transition(.opacity.combined(with: .move(edge: .top)))
        } else if !hasCompletedOnboarding {
            IdentityOnboardingCTARow {
                onRequestOnboarding?()
            }
            .transition(.opacity)
        }
    }

    private var visibleIdentityDiscounts: [EligibleDiscount] {
        if featureGate.canAccess(.fullIdentityDiscounts) {
            return viewModel.identityDiscounts
        }
        return Array(
            viewModel.identityDiscounts.prefix(FeatureGateService.freeIdentityDiscountLimit)
        )
    }

    private var hiddenIdentityDiscountCount: Int {
        viewModel.identityDiscounts.count - visibleIdentityDiscounts.count
    }

    // MARK: - Row data

    private var priceByRetailer: [String: RetailerPrice] {
        Dictionary(uniqueKeysWithValues: viewModel.sortedPrices.map { ($0.retailerId, $0) })
    }

    /// Combined row list: success rows (sorted by price) first, then no_match, then unavailable.
    /// Falls back to `sortedPrices` alone when the backend hasn't supplied retailer_results
    /// (e.g. an old cached response decoded from Redis before the schema change).
    private var allRetailerRows: [RetailerListRow] {
        if comparison.retailerResults.isEmpty {
            return viewModel.sortedPrices.map { .success($0) }
        }

        let lookup = priceByRetailer
        var successRows: [RetailerListRow] = []
        var noMatchRows: [RetailerListRow] = []
        var unavailableRows: [RetailerListRow] = []

        for result in comparison.retailerResults {
            switch result.status {
            case .success:
                if let price = lookup[result.retailerId] {
                    successRows.append(.success(price))
                } else {
                    // Status says success but price missing — treat as unavailable defensively.
                    unavailableRows.append(.unavailable(result))
                }
            case .noMatch:
                noMatchRows.append(.noMatch(result))
            case .unavailable:
                unavailableRows.append(.unavailable(result))
            }
        }

        successRows.sort { lhs, rhs in
            switch (lhs, rhs) {
            case (.success(let a), .success(let b)): return a.price < b.price
            default: return false
            }
        }
        return successRows + noMatchRows + unavailableRows
    }

    // MARK: - Savings

    @ViewBuilder
    private var savingsSection: some View {
        if let savings = viewModel.maxSavings, savings > 0,
           let highest = viewModel.sortedPrices.last {
            SavingsBadge(savedAmount: savings, originalPrice: highest.price)
        }
    }

    // MARK: - Section Header

    private var sectionHeader: some View {
        HStack {
            Text("Marketplace Comparison")
                .font(.barkainTitle2)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
            Spacer()
        }
    }

    // MARK: - Retailer List (all 11)

    private var retailerList: some View {
        VStack(spacing: Spacing.xs) {
            ForEach(Array(allRetailerRows.enumerated()), id: \.element.id) { index, row in
                Group {
                    switch row {
                    case .success(let retailerPrice):
                        Button {
                            Task {
                                if let url = await viewModel.resolveAffiliateURL(for: retailerPrice) {
                                    browserURL = IdentifiableURL(url: url)
                                }
                            }
                        } label: {
                            PriceRow(
                                retailerPrice: retailerPrice,
                                // Step 2f: hide card subtitle for free users.
                                // The cardUpgradeBanner above the list points
                                // them at the paywall instead of repeating an
                                // upgrade nudge on every row.
                                cardRecommendation: featureGate.canAccess(.cardRecommendations)
                                    ? viewModel.cardRecommendations.first { $0.retailerId == retailerPrice.retailerId }
                                    : nil
                            )
                        }
                        .buttonStyle(.plain)
                    case .noMatch(let result):
                        inactiveRow(name: result.retailerName, label: "Not found")
                    case .unavailable(let result):
                        inactiveRow(name: result.retailerName, label: "Unavailable")
                    }
                }
                .overlay(alignment: .topTrailing) {
                    if index == 0, case .success = row {
                        bestBarkainBadge
                    }
                }
            }
        }
        // Step 2c: animate row transitions as SSE events arrive.
        .animation(.default, value: comparison.retailerResults)
        .animation(.default, value: comparison.prices)
    }

    private func inactiveRow(name: String, label: String) -> some View {
        HStack {
            Text(name)
                .font(.barkainBody)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
            Spacer()
            Text(label)
                .font(.barkainCaption)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.sm)
        .background(Color.barkainSurfaceContainerLow.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadius))
        .opacity(0.6)
    }

    // MARK: - Best Barkain Badge

    private var bestBarkainBadge: some View {
        HStack(spacing: Spacing.xxs) {
            Image(systemName: "pawprint.fill")
                .font(.system(size: 10))
            Text("BEST BARKAIN")
                .font(.barkainLabel)
                .tracking(0.5)
        }
        .foregroundStyle(Color.barkainOnSurface)
        .padding(.horizontal, Spacing.sm)
        .padding(.vertical, 4)
        .background(Color.barkainPrimaryContainer)
        .clipShape(Capsule())
        .offset(x: -Spacing.sm, y: -Spacing.sm)
    }

    // MARK: - Status Bar

    private var statusBar: some View {
        HStack {
            Text("\(comparison.retailersSucceeded) of \(comparison.totalRetailers) retailers have this product")
                .font(.barkainCaption)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
            Spacer()
        }
        .padding(.horizontal, Spacing.xs)
    }

    // MARK: - Actions

    private var actionButtons: some View {
        VStack(spacing: Spacing.sm) {
            Button {
                Task { await viewModel.fetchPrices(forceRefresh: true) }
            } label: {
                HStack {
                    Image(systemName: "arrow.clockwise")
                    Text("Refresh Prices")
                }
                .font(.barkainHeadline)
                .foregroundStyle(Color.barkainPrimary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, Spacing.sm)
                .background(Color.barkainSurfaceContainerLow)
                .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadiusLarge))
            }

            Button {
                viewModel.reset()
            } label: {
                Text("Scan Another")
                    .font(.barkainHeadline)
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Spacing.sm)
                    .background(Color.barkainPrimaryGradient)
                    .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadiusLarge))
            }
        }
    }

    // MARK: - Helpers
    //
    // Step 2g: `openRetailerURL(_:)` was removed. All retailer taps now
    // route through `viewModel.resolveAffiliateURL(for:)` and present the
    // tagged URL via the in-app browser sheet.
}

// MARK: - Preview

#Preview {
    PriceComparisonView(
        product: Product(
            id: UUID(),
            upc: "012345678901",
            asin: "B0BSHF7WHN",
            name: "Sony WH-1000XM5",
            brand: "Sony",
            category: "headphones",
            imageUrl: nil,
            source: "gemini_upc"
        ),
        comparison: PriceComparison(
            productId: UUID(),
            productName: "Sony WH-1000XM5",
            prices: [
                RetailerPrice(retailerId: "amazon", retailerName: "Amazon", price: 298.00, originalPrice: 349.99, currency: "USD", url: nil, condition: "new", isAvailable: true, isOnSale: true, lastChecked: Date()),
                RetailerPrice(retailerId: "best_buy", retailerName: "Best Buy", price: 329.99, originalPrice: nil, currency: "USD", url: nil, condition: "new", isAvailable: true, isOnSale: false, lastChecked: Date()),
                RetailerPrice(retailerId: "walmart", retailerName: "Walmart", price: 299.99, originalPrice: nil, currency: "USD", url: nil, condition: "new", isAvailable: true, isOnSale: false, lastChecked: Date()),
            ],
            retailerResults: [
                RetailerResult(retailerId: "amazon", retailerName: "Amazon", status: .success),
                RetailerResult(retailerId: "best_buy", retailerName: "Best Buy", status: .success),
                RetailerResult(retailerId: "walmart", retailerName: "Walmart", status: .success),
                RetailerResult(retailerId: "target", retailerName: "Target", status: .noMatch),
                RetailerResult(retailerId: "home_depot", retailerName: "Home Depot", status: .noMatch),
                RetailerResult(retailerId: "ebay_new", retailerName: "eBay New", status: .unavailable),
            ],
            totalRetailers: 11,
            retailersSucceeded: 3,
            retailersFailed: 3,
            cached: false,
            fetchedAt: Date()
        ),
        viewModel: {
            let vm = ScannerViewModel(apiClient: PreviewAPIClient())
            return vm
        }()
    )
    .environment(FeatureGateService(proTierProvider: { false }))
}

// MARK: - Preview Helper

private struct PreviewAPIClient: APIClientProtocol {
    func resolveProduct(upc: String) async throws -> Product {
        fatalError("Preview only")
    }
    func getPrices(productId: UUID, forceRefresh: Bool) async throws -> PriceComparison {
        fatalError("Preview only")
    }
    func streamPrices(productId: UUID, forceRefresh: Bool) -> AsyncThrowingStream<RetailerStreamEvent, Error> {
        AsyncThrowingStream { $0.finish() }
    }
    func getIdentityProfile() async throws -> IdentityProfile {
        fatalError("Preview only")
    }
    func updateIdentityProfile(_ request: IdentityProfileRequest) async throws -> IdentityProfile {
        fatalError("Preview only")
    }
    func getEligibleDiscounts(productId: UUID?) async throws -> IdentityDiscountsResponse {
        IdentityDiscountsResponse(eligibleDiscounts: [], identityGroupsActive: [])
    }
    func getCardCatalog() async throws -> [CardRewardProgram] { [] }
    func getUserCards() async throws -> [UserCardSummary] { [] }
    func addCard(_ request: AddCardRequest) async throws -> UserCardSummary { fatalError("Preview only") }
    func removeCard(userCardId: UUID) async throws {}
    func setPreferredCard(userCardId: UUID) async throws -> UserCardSummary { fatalError("Preview only") }
    func setCardCategories(userCardId: UUID, request: SetCategoriesRequest) async throws {}
    func getCardRecommendations(productId: UUID) async throws -> CardRecommendationsResponse {
        CardRecommendationsResponse(recommendations: [], userHasCards: false)
    }
    func getBillingStatus() async throws -> BillingStatus {
        BillingStatus(tier: "free", expiresAt: nil, isActive: false, entitlementId: nil)
    }
    func getAffiliateURL(
        productId: UUID?,
        retailerId: String,
        productURL: String
    ) async throws -> AffiliateURLResponse {
        AffiliateURLResponse(
            affiliateUrl: productURL,
            isAffiliated: false,
            network: nil,
            retailerId: retailerId
        )
    }
    func getAffiliateStats() async throws -> AffiliateStatsResponse {
        AffiliateStatsResponse(clicksByRetailer: [:], totalClicks: 0)
    }
}
