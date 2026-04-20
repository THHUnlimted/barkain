import Foundation

// MARK: - AutocompleteServiceProtocol

/// Provides on-device prefix suggestions for the Search tab. Backed by a
/// JSON vocabulary bundled at build time; no network calls per keystroke.
protocol AutocompleteServiceProtocol: Sendable {
    /// Returns up to `limit` display-cased terms whose normalized form
    /// starts with `prefix` (case-insensitive). Empty array on no match,
    /// load failure, or empty input.
    func suggestions(for prefix: String, limit: Int) async -> [String]

    /// True once the bundled vocab JSON has been loaded successfully.
    /// Remains false if the resource is missing or malformed.
    var isReady: Bool { get async }
}
