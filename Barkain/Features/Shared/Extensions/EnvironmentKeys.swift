import SwiftUI

// MARK: - APIClient Environment Key

private struct APIClientKey: EnvironmentKey {
    static let defaultValue: any APIClientProtocol = APIClient()
}

extension EnvironmentValues {
    var apiClient: any APIClientProtocol {
        get { self[APIClientKey.self] }
        set { self[APIClientKey.self] = newValue }
    }
}

// MARK: - Autocomplete Environment Keys

private struct AutocompleteServiceKey: EnvironmentKey {
    static let defaultValue: any AutocompleteServiceProtocol = AutocompleteService()
}

private struct RecentSearchesKey: EnvironmentKey {
    @MainActor static let defaultValue: RecentSearches = RecentSearches()
}

extension EnvironmentValues {
    var autocompleteService: any AutocompleteServiceProtocol {
        get { self[AutocompleteServiceKey.self] }
        set { self[AutocompleteServiceKey.self] = newValue }
    }

    var recentSearches: RecentSearches {
        get { self[RecentSearchesKey.self] }
        set { self[RecentSearchesKey.self] = newValue }
    }
}
