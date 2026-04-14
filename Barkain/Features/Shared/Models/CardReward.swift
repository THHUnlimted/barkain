import Foundation

// MARK: - CardRewardProgram
// Snake-case keys are decoded via JSONDecoder's .convertFromSnakeCase strategy
// (configured in APIClient.swift). `category_bonuses` stays as raw dictionaries
// — the iOS side never inspects it, so `userSelectedAllowed` is flattened by
// the backend into a top-level field.

nonisolated struct CardRewardProgram: Codable, Equatable, Sendable, Identifiable, Hashable {
    let id: UUID
    let cardNetwork: String
    let cardIssuer: String
    let cardProduct: String
    let cardDisplayName: String
    let baseRewardRate: Double
    let rewardCurrency: String
    let pointValueCents: Double?
    let hasShoppingPortal: Bool
    let portalUrl: String?
    let annualFee: Double
    let userSelectedAllowed: [String]?
}

// MARK: - UserCardSummary

nonisolated struct UserCardSummary: Codable, Equatable, Sendable, Identifiable, Hashable {
    let id: UUID
    let cardProgramId: UUID
    let cardIssuer: String
    let cardProduct: String
    let cardDisplayName: String
    let nickname: String?
    let isPreferred: Bool
    let baseRewardRate: Double
    let rewardCurrency: String
}

// MARK: - AddCardRequest

nonisolated struct AddCardRequest: Codable, Equatable, Sendable {
    let cardProgramId: UUID
    let nickname: String?

    init(cardProgramId: UUID, nickname: String? = nil) {
        self.cardProgramId = cardProgramId
        self.nickname = nickname
    }
}

// MARK: - SetCategoriesRequest

nonisolated struct SetCategoriesRequest: Codable, Equatable, Sendable {
    let categories: [String]
    let quarter: String
}

// MARK: - CardRecommendation

nonisolated struct CardRecommendation: Codable, Equatable, Sendable, Identifiable, Hashable {
    var id: String { "\(retailerId)-\(userCardId.uuidString)" }
    let retailerId: String
    let retailerName: String
    let userCardId: UUID
    let cardProgramId: UUID
    let cardDisplayName: String
    let cardIssuer: String
    let rewardRate: Double
    let rewardAmount: Double
    let rewardCurrency: String
    let isRotatingBonus: Bool
    let isUserSelectedBonus: Bool
    let activationRequired: Bool
    let activationUrl: String?
}

// MARK: - CardRecommendationsResponse

nonisolated struct CardRecommendationsResponse: Codable, Equatable, Sendable {
    let recommendations: [CardRecommendation]
    let userHasCards: Bool
}
