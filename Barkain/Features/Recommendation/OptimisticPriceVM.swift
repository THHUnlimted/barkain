import Foundation
import os

private let optimisticLog = Logger(subsystem: "com.barkain.app", category: "Optimistic")

// MARK: - OptimisticResolveOutcome

/// Reported back to `SearchViewModel` once `/resolve-from-search` returns.
/// SearchVM owns sheet/UI state for confirmation + unresolved + error flows;
/// OptimisticPriceVM only orchestrates the resolve→stream chain on success.
enum OptimisticResolveOutcome: Sendable {
    case success(Product)
    case needsConfirmation(LowConfidenceCandidate)
    /// 404 from `/resolve-from-search`. ``reason`` carries Gemini's stated
    /// explanation when the backend included it in the error envelope
    /// (cat-rel-1-L2-ux). Nil when the 404 was a hard miss or came from
    /// the UPC path.
    case unresolved(reason: String? = nil)
    case failed(APIError)
}

// MARK: - OptimisticPriceVM
//
// PR-2 of the "hide the latency" tranche. Used by SearchView when the user
// taps a non-DB result row with the `experiment.optimisticSearchTap` flag on.
//
// What it does:
//
//   1. On init, seeds an internal ScannerViewModel with a SYNTHETIC Product
//      built from the search-result hint (deviceName / brand / category /
//      imageUrl). PriceComparisonView's pre-first-event branch renders
//      immediately — the user sees the product card + sniffing-dog
//      animation the instant they tap, instead of staring at a spinner on
//      the search list for 3-7 seconds.
//
//   2. start() fires /resolve-from-search in the background. On success it
//      swaps the synthetic Product for the real one and delegates to the
//      inner ScannerViewModel.fetchPrices() — which then runs the existing
//      SSE stream + identity + cards + recommend pipeline unchanged.
//
//   3. On any non-success outcome (409 / 404 / network error) it reports
//      back to SearchViewModel via `onResolveOutcome`. SearchVM owns the
//      teardown + presents its existing confirmation sheet, unresolved view,
//      or error alert. OptimisticPriceVM never duplicates that UI surface.
//
// Design choice — composition over duplication:
//
//   The plan called for a fully separate state machine with hand-rolled SSE
//   consumption, identity/cards fetches, and recommendation gating. Doing
//   that would duplicate ~250 LOC from ScannerViewModel. Instead this VM
//   owns an inner ScannerViewModel and forwards every PriceComparisonProviding
//   member to it. The ONLY thing OptimisticPriceVM adds is the resolve-step
//   that runs BEFORE the existing pipeline. That keeps regression risk
//   small and the diff focused on the new behavior.
//
// Cancellation:
//
//   `cancelAll()` cancels the in-flight orchestration task. SearchView calls
//   this on dismissal. This does NOT actively kill an in-flight SSE stream
//   today — the inner ScannerViewModel doesn't expose a cancel hook for its
//   for-await loop. PR-4 (cancellation integration) plumbs that through.

@MainActor
@Observable
final class OptimisticPriceVM: PriceComparisonProviding {

    // MARK: - Identity for SwiftUI .task(id:)

    let id = UUID()

    // MARK: - Hint context

    let originalResult: ProductSearchResult
    let originalQuery: String

    // MARK: - Callback

    /// SearchViewModel sets this before calling `start()`. Fires exactly once
    /// per VM lifecycle, on the MainActor, when the resolve attempt settles.
    var onResolveOutcome: ((OptimisticResolveOutcome) -> Void)?

    // MARK: - Inner

    /// All the heavy lifting (SSE consumption, identity discounts, card
    /// recommendations, M6 hero gate) runs on this inner VM unchanged.
    private let inner: ScannerViewModel

    // MARK: - Tasks (for cancellation)

    private var orchestrationTask: Task<Void, Never>?

    // MARK: - Dependencies

    private let apiClient: any APIClientProtocol

    // MARK: - Init

    init(
        result: ProductSearchResult,
        query: String,
        apiClient: any APIClientProtocol,
        featureGate: FeatureGateService,
        locationPreferences: LocationPreferences = LocationPreferences(),
        portalMembershipPreferences: PortalMembershipPreferences = PortalMembershipPreferences(),
        identityCache: IdentityCache = .shared
    ) {
        self.originalResult = result
        self.originalQuery = query
        self.apiClient = apiClient
        self.inner = ScannerViewModel(
            apiClient: apiClient,
            featureGate: featureGate,
            locationPreferences: locationPreferences,
            portalMembershipPreferences: portalMembershipPreferences,
            identityCache: identityCache
        )
        // Seed a synthetic Product so PriceComparisonView's pre-first-event
        // branch can render the product card + sniffing-dog instantly. The
        // throwaway UUID is irrelevant — fetchPrices() is gated on the real
        // resolved Product (assigned in handleResolvedProduct below) and
        // stream start uses that real productId.
        inner.product = Product(
            id: UUID(),
            upc: result.primaryUpc,
            asin: nil,
            name: result.deviceName,
            brand: result.brand,
            category: result.category,
            imageUrl: result.imageUrl,
            source: "search_hint"
        )
        inner.isPriceLoading = true
    }

    // MARK: - PriceComparisonProviding (forward to inner)

    var product: Product? { inner.product }
    var priceComparison: PriceComparison? { inner.priceComparison }
    var isPriceLoading: Bool { inner.isPriceLoading }
    var sortedPrices: [RetailerPrice] { inner.sortedPrices }
    var maxSavings: Double? { inner.maxSavings }
    var identityDiscounts: [EligibleDiscount] { inner.identityDiscounts }
    var cardRecommendations: [CardRecommendation] { inner.cardRecommendations }
    var userHasCards: Bool { inner.userHasCards }
    var recommendation: Recommendation? { inner.recommendation }
    var insufficientDataReason: String? { inner.insufficientDataReason }
    var apiClientForInterstitial: any APIClientProtocol { inner.apiClientForInterstitial }

    func fetchPrices(forceRefresh: Bool, queryOverride: String?) async {
        await inner.fetchPrices(forceRefresh: forceRefresh, queryOverride: queryOverride)
    }

    func reset() {
        inner.reset()
    }

    func resolveAffiliateURL(for retailerPrice: RetailerPrice) async -> URL? {
        await inner.resolveAffiliateURL(for: retailerPrice)
    }

    func resolveAffiliateURL(for path: StackedPath) async -> URL? {
        await inner.resolveAffiliateURL(for: path)
    }

    // MARK: - Optimistic entry point

    /// Kicks off the resolve-then-stream chain. Reports the outcome to
    /// `onResolveOutcome` exactly once. On `.success` the inner VM
    /// continues with fetchPrices() in the background.
    func start() async {
        guard orchestrationTask == nil else {
            optimisticLog.debug("start() called twice — ignoring second call")
            return
        }
        orchestrationTask = Task { [weak self] in
            await self?.runStartChain()
        }
        await orchestrationTask?.value
    }

    private func runStartChain() async {
        let outcome = await runResolve()
        onResolveOutcome?(outcome)
        if case .success(let realProduct) = outcome {
            let queryOverride: String? =
                originalResult.source == .generic ? originalResult.deviceName : nil
            await handleResolvedProduct(realProduct, queryOverride: queryOverride)
        }
    }

    private func runResolve() async -> OptimisticResolveOutcome {
        do {
            try Task.checkCancellation()
            let outcome = try await resolveTappedResult(originalResult)
            switch outcome {
            case .loaded(let product):
                return .success(product)
            case .needsConfirmation(let candidate):
                return .needsConfirmation(candidate)
            }
        } catch is CancellationError {
            optimisticLog.info("resolve cancelled by parent")
            return .failed(.unknown(0, "cancelled"))
        } catch APIError.notFound(let reason) {
            optimisticLog.info("resolve 404 — surfacing unresolved reason=\(reason ?? "(none)", privacy: .public)")
            inner.isPriceLoading = false
            return .unresolved(reason: reason)
        } catch let apiError as APIError {
            optimisticLog.warning(
                "resolve failed with APIError — \(apiError.localizedDescription, privacy: .public)"
            )
            inner.isPriceLoading = false
            return .failed(apiError)
        } catch {
            optimisticLog.warning(
                "resolve failed with unknown error — \(error.localizedDescription, privacy: .public)"
            )
            inner.isPriceLoading = false
            return .failed(.unknown(0, error.localizedDescription))
        }
    }

    /// Mirrors `SearchViewModel.resolveTappedResult`. Prefers UPC lookup when
    /// available, falls back to description-based resolve. Forwards the row's
    /// confidence so the backend can apply the demo-prep-1 Item 3 gate.
    private func resolveTappedResult(
        _ result: ProductSearchResult
    ) async throws -> ResolveFromSearchOutcome {
        // Forward the search-row thumbnail through to the resolver so the
        // persisted Product carries the user-tapped image (same pattern as
        // SearchViewModel.resolveTappedResult).
        let fallbackImage = result.imageUrl
        if let upc = result.primaryUpc, !upc.isEmpty {
            do {
                let product = try await apiClient.resolveProduct(
                    upc: upc, fallbackImageURL: fallbackImage
                )
                return .loaded(product)
            } catch APIError.notFound {
                // Fall through to description-based resolve.
            }
        }
        return try await apiClient.resolveProductFromSearch(
            deviceName: result.deviceName,
            brand: result.brand,
            model: result.model,
            confidence: result.confidence,
            fallbackImageURL: fallbackImage
        )
    }

    private func handleResolvedProduct(_ realProduct: Product, queryOverride: String?) async {
        inner.scannedUPC = realProduct.upc
        inner.product = realProduct
        await inner.fetchPrices(queryOverride: queryOverride)
    }

    // MARK: - Cancellation

    /// Called by SearchView when the user backs out of the optimistic
    /// skeleton. Cancels the in-flight orchestration task.
    func cancelAll() {
        orchestrationTask?.cancel()
        orchestrationTask = nil
    }
}
