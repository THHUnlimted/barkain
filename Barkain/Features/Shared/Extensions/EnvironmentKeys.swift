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

private struct RecentlyScannedKey: EnvironmentKey {
    @MainActor static let defaultValue: RecentlyScannedStore = RecentlyScannedStore()
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

    var recentlyScanned: RecentlyScannedStore {
        get { self[RecentlyScannedKey.self] }
        set { self[RecentlyScannedKey.self] = newValue }
    }
}

// MARK: - Tab Selection (demo-prep-1 Item 2)
//
// Lightweight cross-tab navigation. Child views that need to jump the user
// to Scan or Search tap these closures; the root `ContentView` binds them
// to its `selection` state. Unbound closures are no-ops — direct
// NavigationStack instantiations (previews, standalone NavigationStack
// hosts) just ignore the tab-switch request. Also unblocks the
// "pill → Profile cross-tab nav" TODO noted in What's Next.

struct TabSelectionAction: Sendable {
    var onScan: @MainActor () -> Void
    var onSearch: @MainActor () -> Void
    var onProfile: @MainActor () -> Void

    static let noop = TabSelectionAction(onScan: {}, onSearch: {}, onProfile: {})
}

private struct TabSelectionActionKey: EnvironmentKey {
    static let defaultValue: TabSelectionAction = .noop
}

extension EnvironmentValues {
    var tabSelection: TabSelectionAction {
        get { self[TabSelectionActionKey.self] }
        set { self[TabSelectionActionKey.self] = newValue }
    }
}
