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
    let viewModel: any PriceComparisonProviding
    // Step 2g + 2026-04-19 fix: browser sheet state is OWNED by the parent
    // (SearchView / ScannerView) and passed in as a binding. PriceComparisonView
    // is rendered inside a parent's `if let` conditional that re-evaluates on
    // every `priceComparison` mutation; if the sheet were `@State` here, the
    // sheet's presentation context could be torn down mid-presentation when the
    // conditional re-renders, leaving the user "kicked back" to the search list.
    // Anchoring the sheet on the stable parent fixes that race.
    @Binding var browserURL: IdentifiableURL?
    var onRequestOnboarding: (() -> Void)? = nil
    var onRequestAddCards: (() -> Void)? = nil
    var onRequestUpgrade: (() -> Void)? = nil
    /// Fires once when the user pulls the ScrollView past its top edge.
    /// SearchView uses this to reveal its hidden `.searchable` bar during
    /// the streaming phase. ScannerView leaves this nil.
    var onPullDown: (() -> Void)? = nil

    @Environment(FeatureGateService.self) private var featureGate

    @AppStorage("hasCompletedIdentityOnboarding")
    private var hasCompletedOnboarding: Bool = false

    // MARK: - Step 3f interstitial state
    //
    // Both entry paths — hero action button and any retailer row's buy tap
    // — route through `.sheet(item: $interstitialContext)`. Nil means no
    // sheet; setting a context slides the sheet up.
    @State private var interstitialContext: PurchaseInterstitialContext?

    /// Retailer id to briefly highlight after the alternatives-rail
    /// scroll-to (Pre-Fix #5). Reset on a 400 ms delay.
    @State private var highlightedRetailerId: String?

    /// Image URL to try when `product.imageUrl` either is nil OR fails to
    /// load. Picks the first scraper image_url that's *different* from the
    /// resolve-time URL — that distinct-URL guard is what rescues products
    /// where the primary URL is from a hotlink-blocked CDN like
    /// `demandware.net` (UPCitemdb hands those out for some SKUs and they
    /// return 403 to anyone without the right Referer header).
    private var heroFallbackImageUrl: String? {
        let prices = viewModel.priceComparison?.prices ?? []
        let primary = product.imageUrl
        let scraperImage = prices
            .compactMap { $0.imageUrl }
            .first { $0 != primary }
        return scraperImage ?? viewModel.priceComparison?.productImageUrl
    }

    // MARK: - Body

    var body: some View {
        ScrollViewReader { proxy in
            bodyContent(proxy: proxy)
        }
        .sheet(item: $interstitialContext) { ctx in
            PurchaseInterstitialSheet(
                context: ctx,
                apiClient: viewModel.apiClientForInterstitial,
                onDismiss: { interstitialContext = nil },
                onOpenActivation: { url in
                    // Close the sheet and open the issuer's activation URL
                    // via the shared browser sheet. The interstitial's
                    // onDismiss flow doesn't fire here — we drop the sheet
                    // ourselves before handing off to the browser.
                    interstitialContext = nil
                    browserURL = IdentifiableURL(url: url)
                },
                onContinue: { url in
                    interstitialContext = nil
                    browserURL = IdentifiableURL(url: url)
                }
            )
        }
    }

    @ViewBuilder
    private func bodyContent(proxy: ScrollViewProxy) -> some View {
        ScrollView {
            VStack(spacing: Spacing.lg) {
                // Invisible pull-down probe. When content is dragged past
                // the ScrollView's top edge (rubber-band region), fire
                // `onPullDown` so SearchView can reveal its search bar.
                Color.clear
                    .frame(height: 0)
                    .background(
                        GeometryReader { geo in
                            Color.clear
                                .onChange(
                                    of: geo.frame(in: .named("barkainScroll")).minY
                                ) { _, newValue in
                                    if newValue > 32 { onPullDown?() }
                                }
                        }
                    )

                ProductCard(
                    product: product,
                    fallbackImageUrl: heroFallbackImageUrl
                )

                // While streaming: the hero replaces savings + identity
                // discounts so the focus stays on the dog working. Rows
                // below still stream in and are fully interactive.
                if viewModel.isPriceLoading {
                    SniffingHeroSection(productName: product.name)
                        .transition(.opacity.combined(with: .move(edge: .top)))
                } else {
                    // Step 3e: the Best Barkain hero renders ONLY after
                    // SSE done + identity + cards have all settled (the
                    // ViewModel only sets `recommendationState = .loaded(...)`
                    // at that point). It replaces neither the savings badge
                    // nor the retailer list — both stay rendered beneath.
                    //
                    // demo-prep-1 Item 1: when the backend returns 422
                    // RECOMMEND_INSUFFICIENT_DATA, render the insufficient-data
                    // card in the same slot so the user sees an explicit
                    // signal instead of a silently-absent hero (retailer grid
                    // below remains populated from SSE).
                    if let recommendation = viewModel.recommendation {
                        RecommendationHero(
                            recommendation: recommendation,
                            onOpen: { winner in
                                // Step 3f — present the purchase interstitial
                                // instead of opening the browser directly. The
                                // sheet handles the affiliate-click round-trip.
                                interstitialContext = PurchaseInterstitialContext(
                                    winner: winner,
                                    productId: product.id,
                                    productName: product.name,
                                    cards: viewModel.cardRecommendations
                                )
                            },
                            onOpenCallout: { callout in
                                if let urlString = callout.purchaseUrlTemplate,
                                   let url = URL(string: urlString) {
                                    browserURL = IdentifiableURL(url: url)
                                }
                            },
                            onSelectAlternative: { alt in
                                // Step 3f Pre-Fix #5 — scroll to the tapped
                                // retailer's row, brief highlight pulse.
                                withAnimation(.spring(response: 0.4, dampingFraction: 0.8)) {
                                    proxy.scrollTo(alt.retailerId, anchor: .top)
                                }
                                highlightedRetailerId = alt.retailerId
                                Task {
                                    try? await Task.sleep(for: .milliseconds(400))
                                    await MainActor.run {
                                        highlightedRetailerId = nil
                                    }
                                }
                            }
                        )
                    } else if viewModel.insufficientDataReason != nil {
                        InsufficientRecommendationCard(productName: product.name)
                            .transition(.opacity.combined(with: .scale(scale: 0.96)))
                    }
                    savingsSection
                    identityDiscountsSection
                }

                sectionHeader
                if !viewModel.isPriceLoading {
                    cardUpgradeBanner
                }
                retailerList

                if !viewModel.isPriceLoading {
                    // 3n: misc-retailer slot. Self-contained — fetches its own
                    // data when `featureGate.isMiscRetailerEnabled`. Hidden
                    // when flag OFF or zero rows after server-side filter.
                    MiscRetailerCard(
                        productId: product.id,
                        queryOverride: nil,
                        browserURL: $browserURL
                    )
                    .transition(.opacity)
                    addCardsCTA
                        .transition(.opacity)
                    statusBar
                        .transition(.opacity)
                    actionButtons
                        .transition(.opacity)
                }
            }
            .padding(Spacing.lg)
            .animation(.easeInOut(duration: 0.3), value: viewModel.identityDiscounts)
            .animation(.easeInOut(duration: 0.3), value: viewModel.cardRecommendations)
            .animation(.easeInOut(duration: 0.45), value: viewModel.isPriceLoading)
        }
        .coordinateSpace(name: "barkainScroll")
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

        // Always price-sort — new arrivals shuffle into the cheapest slot
        // they belong in as soon as they land. Failures pin to the bottom
        // so they don't jostle the success rows around.
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
                        let card: CardRecommendation? = featureGate.canAccess(.cardRecommendations)
                            ? viewModel.cardRecommendations.first { $0.retailerId == retailerPrice.retailerId }
                            : nil
                        Button {
                            // Step 3f — retailer row tap now presents the
                            // interstitial (even on uncovered rows; the sheet
                            // just shows the direct-purchase variant).
                            interstitialContext = PurchaseInterstitialContext(
                                price: retailerPrice,
                                productId: product.id,
                                productName: product.name,
                                card: card
                            )
                        } label: {
                            PriceRow(
                                retailerPrice: retailerPrice,
                                cardRecommendation: card,
                                // Top row is always the current cheapest —
                                // it's accurate during streaming too.
                                isBest: index == 0
                            )
                            .background(
                                highlightedRetailerId == retailerPrice.retailerId
                                    ? Color.barkainPrimary.opacity(0.12)
                                    : Color.clear
                            )
                            .animation(.easeInOut(duration: 0.2), value: highlightedRetailerId)
                        }
                        .buttonStyle(.plain)
                        .id(retailerPrice.retailerId)
                        .accessibilityIdentifier("retailerRow_\(retailerPrice.retailerId)")
                    case .noMatch(let result):
                        inactiveRow(name: result.retailerName, label: "Not found")
                    case .unavailable(let result):
                        inactiveRow(name: result.retailerName, label: "Unavailable")
                    }
                }
                .transition(.asymmetric(
                    insertion: .move(edge: .top).combined(with: .opacity),
                    removal: .opacity
                ))
                .overlay(alignment: .topTrailing) {
                    if index == 0, case .success = row {
                        bestBarkainBadge
                    }
                }
            }
        }
        // Step 2c: animate row transitions as SSE events arrive.
        // Glide new rows in from the top, then smoothly resort when the
        // stream closes (isPriceLoading flips → allRetailerRows reorders).
        .animation(.spring(response: 0.45, dampingFraction: 0.85), value: comparison.retailerResults)
        .animation(.spring(response: 0.45, dampingFraction: 0.85), value: comparison.prices)
        .animation(.spring(response: 0.6, dampingFraction: 0.82), value: viewModel.isPriceLoading)
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
                Task { await viewModel.fetchPrices(forceRefresh: true, queryOverride: nil) }
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
        }(),
        browserURL: .constant(nil)
    )
    .environment(FeatureGateService(proTierProvider: { false }))
}

// MARK: - Preview Helper

private final class PreviewAPIClient: BarePreviewAPIClient, @unchecked Sendable {}
