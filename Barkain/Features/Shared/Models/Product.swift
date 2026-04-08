import Foundation

// MARK: - Product

nonisolated struct Product: Codable, Identifiable, Equatable, Sendable {
    let id: UUID
    let upc: String?
    let asin: String?
    let name: String
    let brand: String?
    let category: String?
    let imageUrl: String?
    let source: String
}
