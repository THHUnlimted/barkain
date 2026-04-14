import XCTest
@testable import Barkain

@MainActor
final class CardSelectionViewModelTests: XCTestCase {

    // MARK: - Fixtures

    private var mockClient: MockAPIClient!
    private var viewModel: CardSelectionViewModel!

    private let freedomFlex = CardRewardProgram(
        id: UUID(uuidString: "aaaaaaaa-1111-1111-1111-aaaaaaaaaaaa")!,
        cardNetwork: "mastercard",
        cardIssuer: "chase",
        cardProduct: "freedom_flex",
        cardDisplayName: "Chase Freedom Flex",
        baseRewardRate: 1.0,
        rewardCurrency: "ultimate_rewards",
        pointValueCents: 1.25,
        hasShoppingPortal: true,
        portalUrl: nil,
        annualFee: 0,
        userSelectedAllowed: nil
    )

    private let cashPlus = CardRewardProgram(
        id: UUID(uuidString: "bbbbbbbb-2222-2222-2222-bbbbbbbbbbbb")!,
        cardNetwork: "visa",
        cardIssuer: "us_bank",
        cardProduct: "cash_plus",
        cardDisplayName: "US Bank Cash+",
        baseRewardRate: 1.0,
        rewardCurrency: "cashback",
        pointValueCents: 1.0,
        hasShoppingPortal: false,
        portalUrl: nil,
        annualFee: 0,
        userSelectedAllowed: ["electronics_stores", "department_stores"]
    )

    override func setUp() {
        super.setUp()
        mockClient = MockAPIClient()
        viewModel = CardSelectionViewModel(apiClient: mockClient)
    }

    // MARK: - Load

    func test_load_populatesCatalogAndUserCards() async {
        mockClient.getCardCatalogResult = .success([freedomFlex, cashPlus])
        mockClient.getUserCardsResult = .success([])

        await viewModel.load()

        XCTAssertEqual(viewModel.catalog.count, 2)
        XCTAssertTrue(viewModel.userCards.isEmpty)
        XCTAssertNil(viewModel.error)
        XCTAssertEqual(mockClient.getCardCatalogCallCount, 1)
        XCTAssertEqual(mockClient.getUserCardsCallCount, 1)
    }

    func test_filteredGroups_groupsByIssuerAlphabetically() async {
        mockClient.getCardCatalogResult = .success([cashPlus, freedomFlex])
        mockClient.getUserCardsResult = .success([])

        await viewModel.load()
        let groups = viewModel.filteredGroups

        XCTAssertEqual(groups.count, 2)
        XCTAssertEqual(groups[0].issuer, "Chase")
        XCTAssertEqual(groups[1].issuer, "US Bank")
    }

    // MARK: - Add / Remove

    func test_addCard_callsAPIAndUpdatesPortfolio() async {
        mockClient.getCardCatalogResult = .success([freedomFlex])
        mockClient.getUserCardsResult = .success([])
        mockClient.addCardResult = .success(
            UserCardSummary(
                id: UUID(),
                cardProgramId: freedomFlex.id,
                cardIssuer: "chase",
                cardProduct: "freedom_flex",
                cardDisplayName: "Chase Freedom Flex",
                nickname: nil,
                isPreferred: false,
                baseRewardRate: 1.0,
                rewardCurrency: "ultimate_rewards"
            )
        )
        await viewModel.load()

        await viewModel.addCard(freedomFlex)

        XCTAssertEqual(mockClient.addCardCallCount, 1)
        XCTAssertEqual(mockClient.addCardLastRequest?.cardProgramId, freedomFlex.id)
        XCTAssertEqual(viewModel.userCards.count, 1)
        XCTAssertTrue(viewModel.isInPortfolio(freedomFlex))
        XCTAssertNil(viewModel.pendingCategorySelection,
                     "Freedom Flex has no user_selected bonus — no category sheet")
    }

    func test_addCard_userSelectedCard_opensCategorySheet() async {
        mockClient.getCardCatalogResult = .success([cashPlus])
        mockClient.getUserCardsResult = .success([])
        let added = UserCardSummary(
            id: UUID(),
            cardProgramId: cashPlus.id,
            cardIssuer: "us_bank",
            cardProduct: "cash_plus",
            cardDisplayName: "US Bank Cash+",
            nickname: nil,
            isPreferred: false,
            baseRewardRate: 1.0,
            rewardCurrency: "cashback"
        )
        mockClient.addCardResult = .success(added)
        await viewModel.load()

        await viewModel.addCard(cashPlus)

        XCTAssertEqual(viewModel.pendingCategorySelection?.id, added.id,
                       "Cash+ has a user_selected bonus → category sheet primed")
    }

    func test_removeCard_softDeletesLocally() async {
        let userCard = UserCardSummary(
            id: UUID(),
            cardProgramId: freedomFlex.id,
            cardIssuer: "chase",
            cardProduct: "freedom_flex",
            cardDisplayName: "Chase Freedom Flex",
            nickname: nil,
            isPreferred: false,
            baseRewardRate: 1.0,
            rewardCurrency: "ultimate_rewards"
        )
        mockClient.getCardCatalogResult = .success([freedomFlex])
        mockClient.getUserCardsResult = .success([userCard])
        mockClient.removeCardResult = .success(())
        await viewModel.load()
        XCTAssertEqual(viewModel.userCards.count, 1)

        await viewModel.removeCard(userCard)

        XCTAssertEqual(mockClient.removeCardCallCount, 1)
        XCTAssertEqual(mockClient.removeCardLastId, userCard.id)
        XCTAssertTrue(viewModel.userCards.isEmpty)
        XCTAssertFalse(viewModel.isInPortfolio(freedomFlex))
    }

    // MARK: - Preferred

    func test_togglePreferred_unsetsOthers() async {
        let card1 = UserCardSummary(
            id: UUID(), cardProgramId: UUID(), cardIssuer: "chase",
            cardProduct: "csp", cardDisplayName: "Chase Sapphire Preferred",
            nickname: nil, isPreferred: true, baseRewardRate: 1.0,
            rewardCurrency: "ultimate_rewards"
        )
        let card2 = UserCardSummary(
            id: UUID(), cardProgramId: UUID(), cardIssuer: "chase",
            cardProduct: "ff", cardDisplayName: "Chase Freedom Flex",
            nickname: nil, isPreferred: false, baseRewardRate: 1.0,
            rewardCurrency: "ultimate_rewards"
        )
        mockClient.getCardCatalogResult = .success([])
        mockClient.getUserCardsResult = .success([card1, card2])
        mockClient.setPreferredCardResult = .success(
            UserCardSummary(
                id: card2.id, cardProgramId: card2.cardProgramId,
                cardIssuer: "chase", cardProduct: "ff",
                cardDisplayName: "Chase Freedom Flex", nickname: nil,
                isPreferred: true, baseRewardRate: 1.0,
                rewardCurrency: "ultimate_rewards"
            )
        )
        await viewModel.load()

        await viewModel.togglePreferred(card2)

        let preferred = viewModel.userCards.filter(\.isPreferred)
        XCTAssertEqual(preferred.count, 1)
        XCTAssertEqual(preferred.first?.id, card2.id)
        XCTAssertEqual(mockClient.setPreferredCardCallCount, 1)
    }

    // MARK: - Categories

    func test_setCategories_callsAPIWithQuarter() async {
        let userCard = UserCardSummary(
            id: UUID(), cardProgramId: cashPlus.id, cardIssuer: "us_bank",
            cardProduct: "cash_plus", cardDisplayName: "US Bank Cash+",
            nickname: nil, isPreferred: false, baseRewardRate: 1.0,
            rewardCurrency: "cashback"
        )
        mockClient.getCardCatalogResult = .success([cashPlus])
        mockClient.getUserCardsResult = .success([userCard])
        mockClient.setCardCategoriesResult = .success(())
        await viewModel.load()
        viewModel.pendingCategorySelection = userCard

        await viewModel.setCategories(
            for: userCard,
            categories: ["electronics_stores"],
            quarter: "2026-Q2"
        )

        XCTAssertEqual(mockClient.setCardCategoriesCallCount, 1)
        XCTAssertEqual(mockClient.setCardCategoriesLastId, userCard.id)
        XCTAssertEqual(mockClient.setCardCategoriesLastRequest?.categories, ["electronics_stores"])
        XCTAssertEqual(mockClient.setCardCategoriesLastRequest?.quarter, "2026-Q2")
        XCTAssertNil(viewModel.pendingCategorySelection,
                     "pending sheet is cleared once save completes")
    }
}
