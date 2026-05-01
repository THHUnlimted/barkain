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

    /// cat-rel-1-L2-ux: optional Gemini reasoning surfaced under the
    /// generic "couldn't find" copy in `UnresolvedProductView`. Populated
    /// from the backend's 404 envelope (`details.reasoning`) when Gemini
    /// explained *why* it couldn't pin a UPC (multi-variant SKU,
    /// dealer-only stock, discontinued line). Nil when the 404 was a
    /// hard miss (UPCitemdb empty AND Gemini transport failure) or when
    /// the call site is `/resolve` (UPC scan, no reasoning available).
    var unresolvedReason: String?

    /// demo-prep-1 Item 3: set when the backend returns 409
    /// RESOLUTION_NEEDS_CONFIRMATION on `/resolve-from-search`. Carries
    /// the in-memory candidate bundle the confirmation sheet renders
    /// (the tapped row as the primary pick plus up to two alternative
    /// rows the user can switch to). Nil when no dialog is open.
    var pendingConfirmation: PendingConfirmation?

    /// The tapped row that a currently-open confirmation sheet will
    /// commit via `/resolve-from-search/confirm` if the user taps "Yes".
    /// Owned separately from `pendingConfirmation.primary` so the sheet's
    /// state can change without losing the user's original pick (the
    /// sheet lets users switch between alternatives before confirming).
    struct PendingConfirmation: Sendable, Equatable {
        /// The row the user originally tapped.
        let primary: ProductSearchResult
        /// Up to 2 alternative rows pulled from the current search
        /// results. May be empty when the results list only contains the
        /// primary pick.
        let alternatives: [ProductSearchResult]
        /// Backend's confidence threshold at the time of the 409 — passed
        /// through so the sheet can show "we're only 55% sure" copy
        /// against the 70% bar.
        let threshold: Double
    }

    /// Present after a successful tap — the `PriceComparisonView` is driven
    /// by this VM. Type lifted to the `PriceComparisonProviding` protocol in
    /// PR-2 so the optimistic-search-tap flow (`OptimisticPriceVM`) can flow
    /// through the same render path as the legacy `ScannerViewModel`.
    var presentedProductViewModel: (any PriceComparisonProviding)?

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
    /// fires the search, then records the term as a recent ONLY on success.
    /// Recording on failure persists garbage queries (overlong strings,
    /// XSS payloads) into the user's history forever.
    func onSuggestionTapped(_ term: String) async {
        let trimmed = term.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        query = trimmed
        suggestionsTask?.cancel()
        searchTask?.cancel()
        await performSearch(trimmed)
        if error == nil { recordRecent(trimmed) }
    }

    /// Manual return-key submit (covers raw-typed queries, including the
    /// zero-match fallback row that submits the user's literal text).
    /// Same success-only recording rule as `onSuggestionTapped`.
    func onSearchSubmitted(_ term: String) async {
        let trimmed = term.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count >= 3 else { return }
        searchTask?.cancel()
        await performSearch(trimmed)
        if error == nil { recordRecent(trimmed) }
    }

    // MARK: - Network search

    /// Direct (non-debounced) entry point — used by suggestion taps and
    /// manual submits. Sets `isLoading` for the duration of the API call.
    func performSearch(_ text: String, forceGemini: Bool = false) async {
        // 3o-C-rustoleum-ux-L1: dismiss any prior PriceComparisonView on a
        // fresh submit. Without this, a user who navigates to a product
        // (e.g. via a recent-search → resolves to product X) and then
        // searches for an unrelated query Y sees Y's results layered behind
        // X's still-presented comparison view, creating "I searched X but
        // got Y" misattribution. The dismiss-on-real-edit hook in
        // `onQueryChange` only fires on text-change events; explicit submit
        // paths (Return key, suggestion-row tap, deep-search) flow through
        // here, which is where the dismiss must happen.
        if presentedProductViewModel != nil {
            presentedProductViewModel = nil
        }
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
        unresolvedReason = nil
        pendingConfirmation = nil

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
            // PR-2: optimistic-search-tap (default-OFF experiment flag).
            // When enabled, navigate immediately to the PriceComparisonView
            // skeleton built from this row's hint and let OptimisticPriceVM
            // run resolve+stream in the background. The user sees the
            // product card + sniffing dog instead of a 3-7s spinner on the
            // search list.
            if featureGate.isOptimisticSearchTapEnabled {
                await presentOptimistic(result)
                return
            }
            isLoading = true
            defer { isLoading = false }
            do {
                let outcome = try await resolveTappedResult(result)
                switch outcome {
                case .loaded(let product):
                    let override: String? = result.source == .generic ? result.deviceName : nil
                    await presentProduct(product, queryOverride: override)
                case .needsConfirmation(let candidate):
                    // demo-prep-1 Item 3: backend gated on low confidence.
                    // Build the sheet payload from the current results —
                    // the primary is the tapped row; alternatives are the
                    // next two non-DB rows (DB rows don't need confirmation
                    // since they route through the direct path above).
                    searchLog.info("handleResultTap: needs confirmation — confidence=\(candidate.confidence, privacy: .public) threshold=\(candidate.threshold, privacy: .public)")
                    let alternatives = results
                        .filter { $0.deviceName != result.deviceName && $0.source != .db }
                        .prefix(2)
                    pendingConfirmation = PendingConfirmation(
                        primary: result,
                        alternatives: Array(alternatives),
                        threshold: candidate.threshold
                    )
                }
            } catch APIError.notFound(let reason) {
                // demo-prep-1 Item 2: both UPC path and the description
                // fallback 404'd. Route to the inline unresolved-product
                // view (dedicated copy + CTAs) instead of the legacy
                // toast which dismissed back to the same search state.
                // cat-rel-1-L2-ux: capture Gemini's stated reason (when
                // present) so the inline view can surface it under the
                // generic copy.
                searchLog.info("handleResultTap: unresolved after tap — surfacing inline view. query=\(self.query, privacy: .public) deviceName=\(result.deviceName, privacy: .public) reason=\(reason ?? "(none)", privacy: .public)")
                unresolvedReason = reason
                unresolvedAfterTap = true
            } catch let apiError as APIError {
                error = apiError
            } catch {
                self.error = .unknown(0, error.localizedDescription)
            }
        }
    }

    /// demo-prep-1 Item 3: called by the confirmation sheet's "Yes" CTA.
    /// Commits the user's pick via `/resolve-from-search/confirm` and
    /// presents the resolved product, or surfaces a structural failure
    /// through `resolveFailureMessage`. The sheet is dismissed before
    /// this runs so the user sees the LoadingState briefly.
    func confirmResolution(for pick: ProductSearchResult) async {
        let queryForTelemetry = query
        pendingConfirmation = nil
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await apiClient.resolveProductFromSearchConfirm(
                ResolveFromSearchConfirmRequest(
                    deviceName: pick.deviceName,
                    brand: pick.brand,
                    model: pick.model,
                    userConfirmed: true,
                    query: queryForTelemetry,
                    fallbackImageURL: pick.imageUrl
                )
            )
            if let product = response.product {
                let override: String? = pick.source == .generic ? pick.deviceName : nil
                await presentProduct(product, queryOverride: override)
            } else {
                // Defensive — backend is contractually required to return
                // a product on user_confirmed=true unless resolution fails
                // outright. Treat an empty product as an unresolved-after-tap.
                unresolvedAfterTap = true
            }
        } catch APIError.notFound(let reason) {
            // cat-rel-1-L2-ux: capture Gemini reasoning on the confirm
            // path too (the user said "yes" but the resolve still 404'd).
            unresolvedReason = reason
            unresolvedAfterTap = true
        } catch let apiError as APIError {
            error = apiError
        } catch {
            self.error = .unknown(0, error.localizedDescription)
        }
    }

    /// demo-prep-1 Item 3: called by the sheet's "No" CTA. Logs the
    /// rejection via `/confirm` (with user_confirmed=false) for server-
    /// side threshold-tuning telemetry, then clears the sheet state so
    /// the user returns to the search results with a fresh slate.
    func rejectResolution() async {
        guard let pending = pendingConfirmation else { return }
        let rejectedQuery = query
        pendingConfirmation = nil
        // Fire-and-forget telemetry — failures here are non-fatal.
        do {
            _ = try await apiClient.resolveProductFromSearchConfirm(
                ResolveFromSearchConfirmRequest(
                    deviceName: pending.primary.deviceName,
                    brand: pending.primary.brand,
                    model: pending.primary.model,
                    userConfirmed: false,
                    query: rejectedQuery
                )
            )
        } catch {
            searchLog.warning("confirm-reject telemetry failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    /// Called by the inline `UnresolvedProductView`'s "Try a different search"
    /// CTA. Clears the unresolved state so the search results re-render.
    func dismissUnresolvedAfterTap() {
        unresolvedAfterTap = false
        unresolvedReason = nil
    }

    /// Resolve a tapped search result to either a loaded Product or a
    /// `.needsConfirmation` outcome. Prefers UPC lookup when available;
    /// falls back to the description-based endpoint on 404. Forwards the
    /// row's `confidence` so the backend can apply the demo-prep-1 Item 3
    /// gate. UPC path hits never trigger the confidence gate — they
    /// return loaded or 404.
    private func resolveTappedResult(_ result: ProductSearchResult) async throws -> ResolveFromSearchOutcome {
        // Forward the search-row thumbnail (often supplied by the M1
        // thumbnail-backfill cascade — eBay → Serper) so the persisted
        // Product carries the same image the user just tapped. Backend
        // only adopts it when no upstream resolver supplies one.
        let fallbackImage = result.imageUrl
        if let upc = result.primaryUpc, !upc.isEmpty {
            do {
                let product = try await apiClient.resolveProduct(
                    upc: upc, fallbackImageURL: fallbackImage
                )
                return .loaded(product)
            } catch APIError.notFound {
                // UPC path failed — fall through to description-based resolve.
            }
        }
        // provisional-resolve: forward the user's original search string
        // so the backend can persist it on a provisional Product's
        // ``source_raw.search_query`` (the M2 stream's ``query_override``
        // auto-injection reads this). No-op when the backend resolves
        // canonically — the field is just ignored on the canonical path.
        return try await apiClient.resolveProductFromSearch(
            deviceName: result.deviceName,
            brand: result.brand,
            model: result.model,
            confidence: result.confidence,
            fallbackImageURL: fallbackImage,
            query: query
        )
    }

    private func presentProduct(_ product: Product, queryOverride: String? = nil) async {
        let vm = ScannerViewModel(apiClient: apiClient, featureGate: featureGate)
        vm.scannedUPC = product.upc
        vm.product = product
        presentedProductViewModel = vm
        await vm.fetchPrices(queryOverride: queryOverride)
    }

    // MARK: - PR-2: Optimistic search-tap

    /// Constructs an OptimisticPriceVM with the row's hint, navigates
    /// immediately, and lets the VM run resolve+stream in the background.
    /// On non-success resolve outcomes the VM reports back via callback;
    /// SearchVM tears down the optimistic VM and routes through its
    /// existing confirmation / unresolved / error sheets.
    private func presentOptimistic(_ result: ProductSearchResult) async {
        let vm = OptimisticPriceVM(
            result: result,
            query: query,
            apiClient: apiClient,
            featureGate: featureGate
        )
        vm.onResolveOutcome = { [weak self] outcome in
            self?.handleOptimisticOutcome(outcome, primary: result)
        }
        presentedProductViewModel = vm
        await vm.start()
    }

    private func handleOptimisticOutcome(
        _ outcome: OptimisticResolveOutcome,
        primary: ProductSearchResult
    ) {
        switch outcome {
        case .success:
            // VM continues internally — fetchPrices() drives the SSE +
            // identity + cards + recommend pipeline. Nothing to do here.
            return
        case .needsConfirmation(let candidate):
            // Tear down the optimistic skeleton and route through the
            // existing confirmation sheet. On confirm, presentProduct()
            // (the legacy path) takes over from confirmResolution().
            presentedProductViewModel = nil
            let alternatives = results
                .filter { $0.deviceName != primary.deviceName && $0.source != .db }
                .prefix(2)
            pendingConfirmation = PendingConfirmation(
                primary: primary,
                alternatives: Array(alternatives),
                threshold: candidate.threshold
            )
        case .unresolved(let reason):
            presentedProductViewModel = nil
            unresolvedReason = reason
            unresolvedAfterTap = true
        case .failed(let apiError):
            presentedProductViewModel = nil
            error = apiError
        }
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
