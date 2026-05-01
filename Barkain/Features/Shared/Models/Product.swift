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
    /// Backend's classification of this Product:
    /// * `"exact"` — canonical UPC-resolved row.
    /// * `"provisional"` — best-effort row persisted by
    ///   `/resolve-from-search` when no UPC could be derived (gated by
    ///   the `PROVISIONAL_RESOLVE_ENABLED` server flag).
    /// Optional for forward-compat: older backends omit the field and we
    /// default to `"exact"` so existing clients keep their behavior.
    let matchQuality: String?

    /// True when the backend tagged this row as a best-effort provisional
    /// match (no canonical UPC). Drives the "approximate match" hero
    /// banner and the Recently Sniffed exclusion.
    var isProvisional: Bool { matchQuality == "provisional" }

    init(
        id: UUID,
        upc: String?,
        asin: String?,
        name: String,
        brand: String?,
        category: String?,
        imageUrl: String?,
        source: String,
        matchQuality: String? = nil
    ) {
        self.id = id
        self.upc = upc
        self.asin = asin
        self.name = name
        self.brand = brand
        self.category = category
        self.imageUrl = imageUrl
        self.source = source
        self.matchQuality = matchQuality
    }
}
