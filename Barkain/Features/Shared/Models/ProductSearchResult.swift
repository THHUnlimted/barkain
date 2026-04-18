import Foundation

// MARK: - ProductSearchSource

nonisolated enum ProductSearchSource: String, Codable, Sendable {
    case db
    case bestBuy = "best_buy"
    case upcitemdb
    case gemini
    case generic
}

// MARK: - ProductSearchResult

nonisolated struct ProductSearchResult: Codable, Identifiable, Equatable, Sendable {
    let deviceName: String
    let model: String?
    let brand: String?
    let category: String?
    let confidence: Double
    let primaryUpc: String?
    let source: ProductSearchSource
    let productId: UUID?
    let imageUrl: String?

    // MARK: - Identifiable

    var id: String {
        if let productId {
            return "db-\(productId.uuidString)"
        }
        return "\(source.rawValue)-\(deviceName)|\(model ?? "")"
    }
}

// MARK: - ProductSearchResponse

nonisolated struct ProductSearchResponse: Codable, Equatable, Sendable {
    let query: String
    let results: [ProductSearchResult]
    let totalResults: Int
    let cached: Bool
}
