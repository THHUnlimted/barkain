import Foundation
@testable import Barkain

// MARK: - MockAutocompleteService

/// Test stand-in for `AutocompleteService`. Mirrors the `MockAPIClient`
/// shape: configurable result + call tracking + last-prefix capture.
final class MockAutocompleteService: AutocompleteServiceProtocol, @unchecked Sendable {

    var suggestionsResult: [String] = []
    var isReadyResult: Bool = true

    var suggestionsCallCount: Int = 0
    var lastPrefix: String?
    var lastLimit: Int?

    var isReady: Bool {
        get async { isReadyResult }
    }

    func suggestions(for prefix: String, limit: Int) async -> [String] {
        suggestionsCallCount += 1
        lastPrefix = prefix
        lastLimit = limit
        return Array(suggestionsResult.prefix(limit))
    }
}
