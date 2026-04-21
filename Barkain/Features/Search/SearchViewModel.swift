import Foundation
import os

// MARK: - Logger

private let searchLog = Logger(subsystem: "com.barkain.app", category: "Search")

// MARK: - SearchViewModel

@Observable
@MainActor
final class SearchViewModel {

    // MARK: - State

    var query: String = ""
    var results: [ProductSearchResult] = []
    var isLoading: Bool = false
    var error: APIError?

    /// Mirror of the `RecentSearches` service so SwiftUI re-renders when
    /// the user adds or clears a recent. The service is the source of
    /// truth for persistence; this property is read-only externally.
    var recentSearches: [String] = []

    /// Live autocomplete suggestions for the current `query`. Driven by
    /// `onQueryChange` — recents when the field is empty, prefix matches
    /// otherwise.
    var suggestions: [String] = []

    /// Set by `handleResultTap` when a Gemini result lacks a primary UPC —
    /// the view surfaces this as a toast so the user knows to scan instead.
    var resolveFailureMessage: String?

    /// Present after a successful tap — the `PriceComparisonView` is driven
    /// by this ScannerViewModel (same destination as the Scanner tab uses).
    var presentedProductViewModel: ScannerViewModel?

    // MARK: - Dependencies

    @ObservationIgnored private let apiClient: any APIClientProtocol
    @ObservationIgnored private let featureGate: FeatureGateService
    @ObservationIgnored private let autocompleteService: any AutocompleteServiceProtocol
    @ObservationIgnored private let recents: RecentSearches

    @ObservationIgnored private var searchTask: Task<Void, Never>?
    @ObservationIgnored private var suggestionsTask: Task<Void, Never>?

    // MARK: - Constants

    static let defaultMaxResults = 10
    static let suggestionsLimit = 8

    // MARK: - Init

    init(
        apiClient: any APIClientProtocol,
        featureGate: FeatureGateService? = nil,
        autocompleteService: (any AutocompleteServiceProtocol)? = nil,
        recentSearches: RecentSearches? = nil
    ) {
        self.apiClient = apiClient
        self.featureGate = featureGate ?? FeatureGateService(proTierProvider: { false })
        self.autocompleteService = autocompleteService ?? NoopAutocompleteService()
        self.recents = recentSearches ?? RecentSearches()
        self.recentSearches = self.recents.all()
        self.suggestions = self.recentSearches
    }

    // MARK: - Search input

    /// Called whenever the search-bar text changes. Only updates the
    /// observable suggestions — the actual search is now submit-driven
    /// (via `.searchCompletion` taps or the return key) per Step 3d.
    func onQueryChange(_ newValue: String) async {
        // SwiftUI's `.searchable` binding setter can fire with the same
        // value on internal UI churn — e.g. when the nav bar hides or
        // shows as `hideNavDuringStream` flips during an SSE stream.
        // Only treat a non-identity call as a real user edit; spurious
        // same-value calls must not wipe `presentedProductViewModel`
        // (bug surfaced in ui-refresh-v2: the PriceComparisonView +
        // SniffingHero got dismissed mid-stream, leaving the user on
        // the results list with no prices).
        let isActualEdit = newValue != query

        if newValue.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            != (lastDeepSearchedQuery?.lowercased() ?? "") {
            lastDeepSearchedQuery = nil
        }
        query = newValue
        error = nil

        // Editing the query dismisses any presented PriceComparisonView so
        // the suggestions list isn't hidden behind it.
        if isActualEdit, presentedProductViewModel != nil {
            presentedProductViewModel = nil
        }

        let trimmed = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            suggestions = recentSearches
            return
        }

        suggestionsTask?.cancel()
        let captured = trimmed
        let task = Task { [weak self] in
            guard let self else { return }
            let next = await self.autocompleteService.suggestions(
                for: captured, limit: Self.suggestionsLimit
            )
            if Task.isCancelled { return }
            self.suggestions = next
        }
        suggestionsTask = task
        await task.value
    }

    /// Tapping a `.searchCompletion(term)` row replaces the query and
    /// fires the search, then records the term as a recent.
    func onSuggestionTapped(_ term: String) async {
        let trimmed = term.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        query = trimmed
        suggestionsTask?.cancel()
        searchTask?.cancel()
        await performSearch(trimmed)
        recordRecent(trimmed)
    }

    /// Manual return-key submit (covers raw-typed queries, including the
    /// zero-match fallback row that submits the user's literal text).
    func onSearchSubmitted(_ term: String) async {
        let trimmed = term.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count >= 3 else { return }
        searchTask?.cancel()
        await performSearch(trimmed)
        recordRecent(trimmed)
    }

    // MARK: - Network search

    /// Direct (non-debounced) entry point — used by suggestion taps and
    /// manual submits. Sets `isLoading` for the duration of the API call.
    func performSearch(_ text: String, forceGemini: Bool = false) async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await apiClient.searchProducts(
                query: text,
                maxResults: Self.defaultMaxResults,
                forceGemini: forceGemini
            )
            if Task.isCancelled { return }
            results = response.results
            error = nil
        } catch let apiError as APIError {
            error = apiError
            results = []
        } catch {
            self.error = .unknown(0, error.localizedDescription)
            results = []
        }
    }

    /// Deep search — invoked when the user submits the keyboard (return key)
    /// after the regular search returned results that don't substring-match
    /// what they typed. Forces Gemini alongside Tier 2 and bypasses Redis.
    func deepSearch() async {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count >= 3 else { return }
        searchTask?.cancel()
        await performSearch(trimmed, forceGemini: true)
        lastDeepSearchedQuery = trimmed
    }

    /// True as soon as the user has typed 3+ characters AND we haven't
    /// already deep-searched the current query.
    var showDeepSearchHint: Bool {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count >= 3 else { return false }
        if let last = lastDeepSearchedQuery,
           last.lowercased() == trimmed.lowercased() {
            return false
        }
        return true
    }

    private var lastDeepSearchedQuery: String?

    // MARK: - Result tap

    /// Called when the user taps a result row. For DB-sourced rows the
    /// `Product` is constructed from the row fields directly (no extra
    /// request). For Gemini rows with a `primary_upc` we run
    /// `/products/resolve`; without a UPC we fall back to
    /// `/products/resolve-from-search`.
    func handleResultTap(_ result: ProductSearchResult) async {
        recordRecent(query)
        error = nil
        resolveFailureMessage = nil

        switch result.source {
        case .db:
            guard let productId = result.productId else {
                resolveFailureMessage = "Couldn't load this product — try again."
                return
            }
            let product = Product(
                id: productId,
                upc: result.primaryUpc,
                asin: nil,
                name: result.deviceName,
                brand: result.brand,
                category: result.category,
                imageUrl: result.imageUrl,
                source: "db"
            )
            await presentProduct(product)

        case .bestBuy, .upcitemdb, .gemini, .generic:
            isLoading = true
            defer { isLoading = false }
            do {
                let product: Product
                if let upc = result.primaryUpc, !upc.isEmpty {
                    product = try await apiClient.resolveProduct(upc: upc)
                } else {
                    product = try await apiClient.resolveProductFromSearch(
                        deviceName: result.deviceName,
                        brand: result.brand,
                        model: result.model
                    )
                }
                let override: String? = result.source == .generic ? result.deviceName : nil
                await presentProduct(product, queryOverride: override)
            } catch APIError.notFound {
                resolveFailureMessage = "Couldn't find a barcode for this product — try scanning it instead."
            } catch let apiError as APIError {
                error = apiError
            } catch {
                self.error = .unknown(0, error.localizedDescription)
            }
        }
    }

    private func presentProduct(_ product: Product, queryOverride: String? = nil) async {
        let vm = ScannerViewModel(apiClient: apiClient, featureGate: featureGate)
        vm.scannedUPC = product.upc
        vm.product = product
        presentedProductViewModel = vm
        await vm.fetchPrices(queryOverride: queryOverride)
    }

    // MARK: - Recent searches

    /// Wraps the `RecentSearches` service write + refreshes the local
    /// observable mirror so `recentSearches` (and any view bound to it)
    /// updates immediately.
    private func recordRecent(_ raw: String) {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count >= 3 else { return }
        recentSearches = recents.add(trimmed)
        if query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            suggestions = recentSearches
        }
    }

    func clearRecentSearches() {
        recents.clear()
        recentSearches = []
        if query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            suggestions = []
        }
    }

    func selectRecentSearch(_ text: String) {
        query = text
        presentedProductViewModel = nil
        searchTask?.cancel()
        searchTask = Task { [weak self] in
            guard let self else { return }
            await self.performSearch(text)
            self.recordRecent(text)
        }
    }
}

// MARK: - Noop autocomplete (used when no service is injected)

/// Returns nothing for every prefix. Used as a safe default in tests
/// that don't care about suggestions, so existing test setUps that only
/// pass `apiClient` continue to work.
private struct NoopAutocompleteService: AutocompleteServiceProtocol {
    var isReady: Bool { get async { false } }
    func suggestions(for prefix: String, limit: Int) async -> [String] { [] }
}
