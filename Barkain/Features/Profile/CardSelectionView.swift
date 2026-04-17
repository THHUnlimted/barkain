import SwiftUI

// MARK: - CardSelectionView

struct CardSelectionView: View {

    // MARK: - State

    @State private var viewModel: CardSelectionViewModel
    @Environment(\.dismiss) private var dismiss

    // MARK: - Init

    init(apiClient: APIClientProtocol) {
        _viewModel = State(initialValue: CardSelectionViewModel(apiClient: apiClient))
    }

    // MARK: - Body

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Add Cards")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button("Done") { dismiss() }
                            .font(.barkainHeadline)
                    }
                }
                .task { await viewModel.load() }
                .sheet(item: $viewModel.pendingCategorySelection) { userCard in
                    if let program = viewModel.catalog.first(where: {
                        $0.id == userCard.cardProgramId
                    }), let allowed = program.userSelectedAllowed, !allowed.isEmpty {
                        CategorySelectionSheet(
                            card: userCard,
                            program: program,
                            allowed: allowed
                        ) { categories in
                            await viewModel.setCategories(
                                for: userCard,
                                categories: categories,
                                quarter: currentQuarter()
                            )
                        }
                    }
                }
        }
    }

    // MARK: - Content

    @ViewBuilder
    private var content: some View {
        if viewModel.isLoading && viewModel.catalog.isEmpty {
            LoadingState(message: "Loading card catalog…")
        } else if let error = viewModel.error, viewModel.catalog.isEmpty {
            EmptyState(
                icon: "creditcard",
                title: "Couldn't load cards",
                subtitle: error.localizedDescription,
                actionTitle: "Try again",
                action: { Task { await viewModel.load() } }
            )
        } else {
            list
        }
    }

    private var list: some View {
        List {
            Section {
                TextField("Search issuer or card name", text: $viewModel.searchQuery)
                    .textFieldStyle(.roundedBorder)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
            }

            if !viewModel.userCards.isEmpty {
                Section("My Cards") {
                    ForEach(viewModel.userCards) { card in
                        userCardRow(card)
                    }
                }
            }

            ForEach(viewModel.filteredGroups, id: \.issuer) { group in
                Section(group.issuer) {
                    ForEach(group.cards) { program in
                        programRow(program)
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
    }

    // MARK: - Rows

    private func programRow(_ program: CardRewardProgram) -> some View {
        let isAdded = viewModel.isInPortfolio(program)
        return Button {
            Task {
                if isAdded {
                    if let uc = viewModel.userCardForProgram(program.id) {
                        await viewModel.removeCard(uc)
                    }
                } else {
                    await viewModel.addCard(program)
                }
            }
        } label: {
            HStack(alignment: .center, spacing: Spacing.sm) {
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(program.cardDisplayName)
                        .font(.barkainHeadline)
                        .foregroundStyle(Color.barkainOnSurface)
                    Text(baseRateLabel(program))
                        .font(.barkainCaption)
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                }
                Spacer()
                if isAdded {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(Color.barkainPrimary)
                        .font(.title3)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func userCardRow(_ userCard: UserCardSummary) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(userCard.cardDisplayName)
                    .font(.barkainHeadline)
                    .foregroundStyle(Color.barkainOnSurface)
                if let nickname = userCard.nickname, !nickname.isEmpty {
                    Text(nickname)
                        .font(.barkainCaption)
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                }
            }
            Spacer()
            Button {
                Task { await viewModel.togglePreferred(userCard) }
            } label: {
                Image(systemName: userCard.isPreferred ? "star.fill" : "star")
                    .foregroundStyle(userCard.isPreferred ? .yellow : Color.barkainOnSurfaceVariant)
                    .font(.title3)
            }
            .buttonStyle(.plain)
        }
        .swipeActions(edge: .trailing, allowsFullSwipe: true) {
            Button(role: .destructive) {
                Task { await viewModel.removeCard(userCard) }
            } label: {
                Label("Remove", systemImage: "trash")
            }
        }
    }

    // MARK: - Helpers

    private func baseRateLabel(_ program: CardRewardProgram) -> String {
        let rateString: String
        if program.baseRewardRate.truncatingRemainder(dividingBy: 1) == 0 {
            rateString = String(format: "%.0fx", program.baseRewardRate)
        } else {
            rateString = String(format: "%.1fx", program.baseRewardRate)
        }
        return "\(rateString) base · \(prettyCurrency(program.rewardCurrency))"
    }

    private func prettyCurrency(_ currency: String) -> String {
        switch currency {
        case "cashback": return "Cash back"
        case "ultimate_rewards": return "Ultimate Rewards"
        case "membership_rewards": return "Membership Rewards"
        case "venture_miles": return "Venture Miles"
        case "thank_you_points": return "ThankYou Points"
        case "points": return "Points"
        default: return currency.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }

    private func currentQuarter() -> String {
        let now = Date()
        let cal = Calendar(identifier: .gregorian)
        let year = cal.component(.year, from: now)
        let month = cal.component(.month, from: now)
        let q = ((month - 1) / 3) + 1
        return "\(year)-Q\(q)"
    }
}

// MARK: - CategorySelectionSheet

struct CategorySelectionSheet: View {
    let card: UserCardSummary
    let program: CardRewardProgram
    let allowed: [String]
    let onSave: ([String]) async -> Void

    @State private var selection: Set<String> = []
    @State private var isSaving = false
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Text("Pick the categories that earn your bonus rate on \(card.cardDisplayName).")
                        .font(.barkainBody)
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                }
                Section("Categories") {
                    ForEach(allowed, id: \.self) { category in
                        Button {
                            if selection.contains(category) {
                                selection.remove(category)
                            } else {
                                selection.insert(category)
                            }
                        } label: {
                            HStack {
                                Text(category.replacingOccurrences(of: "_", with: " ").capitalized)
                                    .font(.barkainBody)
                                    .foregroundStyle(Color.barkainOnSurface)
                                Spacer()
                                if selection.contains(category) {
                                    Image(systemName: "checkmark")
                                        .foregroundStyle(Color.barkainPrimary)
                                }
                            }
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .navigationTitle("Pick categories")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Skip") { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(isSaving ? "Saving…" : "Save") {
                        Task {
                            isSaving = true
                            await onSave(Array(selection))
                            isSaving = false
                            dismiss()
                        }
                    }
                    .disabled(selection.isEmpty || isSaving)
                }
            }
        }
    }
}

// MARK: - Preview

#Preview("Card Selection") {
    CardSelectionView(apiClient: PreviewCardAPIClient())
}

private struct PreviewCardAPIClient: APIClientProtocol {
    func resolveProduct(upc: String) async throws -> Product { fatalError("Preview only") }
    func resolveProductFromSearch(deviceName: String, brand: String?, model: String?) async throws -> Product { fatalError("Preview only") }
    func searchProducts(query: String, maxResults: Int) async throws -> ProductSearchResponse {
        ProductSearchResponse(query: query, results: [], totalResults: 0, cached: false)
    }
    func getPrices(productId: UUID, forceRefresh: Bool) async throws -> PriceComparison { fatalError("Preview only") }
    func streamPrices(productId: UUID, forceRefresh: Bool) -> AsyncThrowingStream<RetailerStreamEvent, Error> {
        AsyncThrowingStream { $0.finish() }
    }
    func getIdentityProfile() async throws -> IdentityProfile { fatalError("Preview only") }
    func updateIdentityProfile(_ request: IdentityProfileRequest) async throws -> IdentityProfile { fatalError("Preview only") }
    func getEligibleDiscounts(productId: UUID?) async throws -> IdentityDiscountsResponse {
        IdentityDiscountsResponse(eligibleDiscounts: [], identityGroupsActive: [])
    }
    func getCardCatalog() async throws -> [CardRewardProgram] {
        [
            CardRewardProgram(
                id: UUID(), cardNetwork: "visa", cardIssuer: "chase",
                cardProduct: "freedom_flex", cardDisplayName: "Chase Freedom Flex",
                baseRewardRate: 1.0, rewardCurrency: "ultimate_rewards",
                pointValueCents: 1.25, hasShoppingPortal: true,
                portalUrl: nil, annualFee: 0, userSelectedAllowed: nil
            ),
            CardRewardProgram(
                id: UUID(), cardNetwork: "visa", cardIssuer: "us_bank",
                cardProduct: "cash_plus", cardDisplayName: "US Bank Cash+",
                baseRewardRate: 1.0, rewardCurrency: "cashback",
                pointValueCents: 1.0, hasShoppingPortal: false,
                portalUrl: nil, annualFee: 0,
                userSelectedAllowed: ["electronics_stores", "department_stores"]
            ),
        ]
    }
    func getUserCards() async throws -> [UserCardSummary] { [] }
    func addCard(_ request: AddCardRequest) async throws -> UserCardSummary {
        UserCardSummary(
            id: UUID(), cardProgramId: request.cardProgramId,
            cardIssuer: "chase", cardProduct: "preview",
            cardDisplayName: "Preview Card", nickname: request.nickname,
            isPreferred: false, baseRewardRate: 1.0,
            rewardCurrency: "cashback"
        )
    }
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
