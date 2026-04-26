import Foundation
import os

// MARK: - CardSelectionViewModel

@MainActor
@Observable
final class CardSelectionViewModel {

    // MARK: - State

    var catalog: [CardRewardProgram] = []
    var userCards: [UserCardSummary] = []
    var searchQuery: String = ""
    var isLoading: Bool = false
    var error: APIError?

    /// The card whose category picker the user just tapped into, if any.
    /// `nil` when the picker sheet is dismissed.
    var pendingCategorySelection: UserCardSummary?

    private let apiClient: APIClientProtocol
    private let identityCache: IdentityCache
    private let log = Logger(subsystem: "com.barkain.app", category: "CardSelection")

    // MARK: - Init

    init(apiClient: APIClientProtocol, identityCache: IdentityCache = .shared) {
        self.apiClient = apiClient
        self.identityCache = identityCache
    }

    // MARK: - Load

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            async let catalogTask = apiClient.getCardCatalog()
            async let userCardsTask = apiClient.getUserCards()
            catalog = try await catalogTask
            userCards = try await userCardsTask
            error = nil
        } catch let err as APIError {
            error = err
        } catch {
            self.error = .unknown(0, error.localizedDescription)
        }
    }

    // MARK: - Derived

    var userCardProgramIds: Set<UUID> {
        Set(userCards.map(\.cardProgramId))
    }

    /// Returns cards grouped by issuer, filtered by the current search query,
    /// sorted alphabetically inside each group and issuers ordered A→Z.
    var filteredGroups: [(issuer: String, cards: [CardRewardProgram])] {
        let query = searchQuery.trimmingCharacters(in: .whitespaces).lowercased()
        let filtered = catalog.filter { card in
            guard !query.isEmpty else { return true }
            return card.cardDisplayName.lowercased().contains(query)
                || card.cardIssuer.lowercased().contains(query)
        }
        let grouped = Dictionary(grouping: filtered, by: \.cardIssuer)
        return grouped
            .map { (issuer: displayIssuer($0.key), cards: $0.value.sorted { $0.cardDisplayName < $1.cardDisplayName }) }
            .sorted { $0.issuer < $1.issuer }
    }

    func userCardForProgram(_ programId: UUID) -> UserCardSummary? {
        userCards.first { $0.cardProgramId == programId }
    }

    func isInPortfolio(_ program: CardRewardProgram) -> Bool {
        userCardProgramIds.contains(program.id)
    }

    func displayIssuer(_ issuer: String) -> String {
        switch issuer {
        case "bank_of_america": return "Bank of America"
        case "capital_one": return "Capital One"
        case "us_bank": return "US Bank"
        case "wells_fargo": return "Wells Fargo"
        default: return issuer.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }

    // MARK: - Mutations

    func addCard(_ program: CardRewardProgram) async {
        do {
            let added = try await apiClient.addCard(
                AddCardRequest(cardProgramId: program.id, nickname: nil)
            )
            // Replace any stale entry with the fresh one and append if absent.
            userCards.removeAll { $0.cardProgramId == program.id }
            userCards.append(added)
            identityCache.invalidateCards()
            error = nil
            // If the card supports user-selected categories, prompt immediately.
            if program.userSelectedAllowed?.isEmpty == false {
                pendingCategorySelection = added
            }
        } catch let err as APIError {
            log.error("addCard failed: \(err.localizedDescription, privacy: .public)")
            error = err
        } catch {
            log.error("addCard failed: \(error.localizedDescription, privacy: .public)")
            self.error = .unknown(0, error.localizedDescription)
        }
    }

    func removeCard(_ userCard: UserCardSummary) async {
        do {
            try await apiClient.removeCard(userCardId: userCard.id)
            userCards.removeAll { $0.id == userCard.id }
            identityCache.invalidateCards()
            error = nil
        } catch let err as APIError {
            error = err
        } catch {
            self.error = .unknown(0, error.localizedDescription)
        }
    }

    func togglePreferred(_ userCard: UserCardSummary) async {
        do {
            let updated = try await apiClient.setPreferredCard(userCardId: userCard.id)
            userCards = userCards.map {
                if $0.id == updated.id {
                    return updated
                }
                guard $0.isPreferred else { return $0 }
                return UserCardSummary(
                    id: $0.id,
                    cardProgramId: $0.cardProgramId,
                    cardIssuer: $0.cardIssuer,
                    cardProduct: $0.cardProduct,
                    cardDisplayName: $0.cardDisplayName,
                    nickname: $0.nickname,
                    isPreferred: false,
                    baseRewardRate: $0.baseRewardRate,
                    rewardCurrency: $0.rewardCurrency
                )
            }
            identityCache.invalidateCards()
            error = nil
        } catch let err as APIError {
            error = err
        } catch {
            self.error = .unknown(0, error.localizedDescription)
        }
    }

    func setCategories(for userCard: UserCardSummary, categories: [String], quarter: String) async {
        do {
            try await apiClient.setCardCategories(
                userCardId: userCard.id,
                request: SetCategoriesRequest(categories: categories, quarter: quarter)
            )
            identityCache.invalidateCards()
            error = nil
            pendingCategorySelection = nil
        } catch let err as APIError {
            error = err
        } catch {
            self.error = .unknown(0, error.localizedDescription)
        }
    }
}
