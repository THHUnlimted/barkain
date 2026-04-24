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

    /// Set by `handleResultTap` when a Gemini result lacks a primary UPC
    /// or when the fallback yields a structural error (not a backend 404).
    /// The view surfaces this as a toast. Clean 404s route to
    /// `unresolvedAfterTap` instead (demo-prep-1 Item 2).
    var resolveFailureMessage: String?

    /// demo-prep-1 Item 2: set when BOTH the UPC path and the
    /// description-based fallback return 404 — "Barkain hasn't indexed
    /// this product yet." Surfaced INLINE via `UnresolvedProductView`
    /// rather than a toast-then-forget alert, so the user gets a clear
    /// next-step (scan, or try a different search).
    var unresolvedAfterTap: Bool = false

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
        // SwiftUI's `.searchable` binding setter fires with spurious
        // values on internal UI churn: same-value calls on re-render,
        // *empty-value* calls when the nav bar hides (the `.searchable`
        // UI detaches from layout and the binding's setter gets called
        // with "" as part of teardown). Both have been observed to kick
        // users out of PriceComparisonView mid-stream in ui-refresh-v2.
        //
        // Heuristic: a real user edit produces a non-empty query that
        // differs from the current value. Empty-value calls and no-op
        // same-value calls never dismiss the presented comparison view.
        // Users who genuinely want to clear the field keep the
        // comparison view visible until they actually type again.
        let isRealEdit = !newValue.isEmpty && newValue != query

        if newValue.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            != (lastDeepSearchedQuery?.lowercased() ?? "") {
            lastDeepSearchedQuery = nil
        }
        // Don't clobber `query` on spurious empty-value calls either —
        // if we set query="" here, the .searchable binding's getter
        // will read it back as "" on the next render, which can create
        // a feedback loop. Only update query when the edit is real or
        // when we're legitimately resetting to empty (user cleared the
        // field while no comparison view is presented).
        if isRealEdit || (newValue.isEmpty && presentedProductViewModel == nil) {
            query = newValue
        }
        error = nil

        // Editing the query dismisses any presented PriceComparisonView so
        // the suggestions list isn't hidden behind it.
        if isRealEdit, presentedProductViewModel != nil {
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
        unresolvedAfterTap = false

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
                let product = try await resolveTappedResult(result)
                let override: String? = result.source == .generic ? result.deviceName : nil
                await presentProduct(product, queryOverride: override)
            } catch APIError.notFound {
                // demo-prep-1 Item 2: both UPC path and the description
                // fallback 404'd. Route to the inline unresolved-product
                // view (dedicated copy + CTAs) instead of the legacy
                // toast which dismissed back to the same search state.
                searchLog.info("handleResultTap: unresolved after tap — surfacing inline view. query=\(self.query, privacy: .public) deviceName=\(result.deviceName, privacy: .public)")
                unresolvedAfterTap = true
            } catch let apiError as APIError {
                error = apiError
            } catch {
                self.error = .unknown(0, error.localizedDescription)
            }
        }
    }

    /// Called by the inline `UnresolvedProductView`'s "Try a different search"
    /// CTA. Clears the unresolved state so the search results re-render.
    func dismissUnresolvedAfterTap() {
        unresolvedAfterTap = false
    }

    /// Resolve a tapped search result to a `Product`. Prefers UPC lookup when
    /// available; falls back to the description-based endpoint on 404, which
    /// re-runs a targeted device→UPC derivation on the backend. Gemini often
    /// returns hallucinated UPCs that fail the UPC path — this fallback lets
    /// those results still resolve via the device_name/brand/model signal.
    private func resolveTappedResult(_ result: ProductSearchResult) async throws -> Product {
        if let upc = result.primaryUpc, !upc.isEmpty {
            do {
                return try await apiClient.resolveProduct(upc: upc)
            } catch APIError.notFound {
                // UPC path failed — fall through to description-based resolve.
            }
        }
        return try await apiClient.resolveProductFromSearch(
            deviceName: result.deviceName,
            brand: result.brand,
            model: result.model
        )
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
