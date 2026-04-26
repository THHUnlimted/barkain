import Foundation
import os

// MARK: - Logger

private let sseLog = Logger(subsystem: "com.barkain.app", category: "SSE")

// MARK: - ScannerViewModel

@Observable
final class ScannerViewModel {

    // MARK: - State

    var scannedUPC: String?
    var product: Product?
    var isLoading = false
    var error: APIError?
    var priceComparison: PriceComparison?
    var isPriceLoading = false
    var priceError: APIError?

    // Step 2d: identity discounts reveal after the price stream finishes.
    // Populated from GET /api/v1/identity/discounts?product_id= on success;
    // cleared on each new scan. Failures here are non-fatal — they do NOT
    // set `priceError`, so the retailer list stays visible.
    var identityDiscounts: [EligibleDiscount] = []

    // Step 2e: best-card recommendation per retailer, chained after identity
    // discounts. Same non-fatal contract — failures log and clear the list,
    // never set `priceError`.
    var cardRecommendations: [CardRecommendation] = []
    var userHasCards: Bool = false

    // Step 2f: paywall presentation state. Set true when a free user hits
    // the daily scan cap; ScannerView observes this and presents PaywallHost.
    var showPaywall: Bool = false

    // MARK: - Step 3e: Recommendation hero (post-close gate)
    //
    // Recommendation fires only after ALL THREE have settled:
    //   • SSE stream closes (or fallback-to-batch succeeds)
    //   • /identity/discounts returns (success OR error)
    //   • /cards/recommendations returns (success OR error)
    // Tracked via three flags that flip true on each completion branch.
    // Flags reset on every new scan so a refresh starts clean.
    //
    // demo-prep-1 Item 1: lifted from `Recommendation?` to a three-way
    // `RecommendationState` so the UI can explicitly render an
    // "insufficient data" card instead of leaving the hero silently absent
    // (which was indistinguishable from "still loading" during F&F demos).
    var recommendationState: RecommendationState = .pending

    /// Happy-path view gate — unchanged shape for existing callers. Returns
    /// nil in both `.pending` and `.insufficientData` cases.
    var recommendation: Recommendation? {
        if case .loaded(let rec) = recommendationState { return rec }
        return nil
    }

    /// Non-nil only when the backend returned 422 `RECOMMEND_INSUFFICIENT_DATA`.
    /// Drives the fallback card in `PriceComparisonView`.
    var insufficientDataReason: String? {
        if case .insufficientData(let reason) = recommendationState { return reason }
        return nil
    }
    private var streamClosed = false
    private var identityLoaded = false
    private var cardsLoaded = false
    private var recommendationTask: Task<Void, Never>?

    /// Test-only hook to await the in-flight recommendation fetch. Production
    /// call sites should never need this — the observable `recommendation`
    /// property drives the UI. Used by RecommendationViewModelTests so the
    /// fire-and-forget Task can be awaited deterministically.
    func _awaitRecommendationTaskForTesting() async {
        await recommendationTask?.value
    }

    // MARK: - Dependencies

    private let apiClient: any APIClientProtocol
    private let featureGate: FeatureGateService
    private let locationPreferences: LocationPreferences
    private let portalMembershipPreferences: PortalMembershipPreferences
    private let identityCache: IdentityCache

    /// Step 3f: PriceComparisonView's PurchaseInterstitialSheet needs the
    /// same client for its affiliate-click call. Exposing this avoids
    /// injecting APIClient into the view env from two directions.
    var apiClientForInterstitial: any APIClientProtocol { apiClient }

    /// Step 3g-B: portal-membership prefs are read at fetch time so the
    /// sheet's "I'm a member" toggles in Profile bust the M6 cache via
    /// the `:p<hash>` segment without any explicit refresh wiring.
    var portalMembershipPreferencesForInterstitial: PortalMembershipPreferences {
        portalMembershipPreferences
    }

    // MARK: - Init

    /// `featureGate` is optional so existing test call sites
    /// (`ScannerViewModel(apiClient: mock)`) stay green without a migration.
    /// When omitted, the init constructs a free-only gate. Production call
    /// sites (ScannerView) inject the real gate from the SwiftUI environment.
    ///
    /// Default values can't reference `FeatureGateService.init` directly
    /// because the gate is `@MainActor`-isolated and Swift evaluates default
    /// parameter expressions in the caller's actor context — building the
    /// gate inside the `init` body sidesteps that.
    init(
        apiClient: any APIClientProtocol,
        featureGate: FeatureGateService? = nil,
        locationPreferences: LocationPreferences = LocationPreferences(),
        portalMembershipPreferences: PortalMembershipPreferences = PortalMembershipPreferences(),
        identityCache: IdentityCache = .shared
    ) {
        self.apiClient = apiClient
        self.featureGate = featureGate ?? FeatureGateService(proTierProvider: { false })
        self.locationPreferences = locationPreferences
        self.portalMembershipPreferences = portalMembershipPreferences
        self.identityCache = identityCache
    }

    // MARK: - Actions

    func handleBarcodeScan(upc: String) async {
        scannedUPC = upc
        product = nil
        error = nil
        priceComparison = nil
        priceError = nil
        identityDiscounts = []
        cardRecommendations = []
        recommendationState = .pending
        streamClosed = false
        identityLoaded = false
        cardsLoaded = false
        recommendationTask?.cancel()
        recommendationTask = nil
        isLoading = true

        do {
            let resolvedProduct = try await apiClient.resolveProduct(upc: upc)
            product = resolvedProduct
            isLoading = false

            // Step 2f: gate scan quota AFTER a successful resolve, not
            // before. We don't burn quota on barcode-read failures or
            // unknown UPCs — the user only "spent" a scan when they got
            // a real product. Pro users skip the gate entirely.
            if featureGate.scanLimitReached {
                showPaywall = true
                return
            }
            featureGate.recordScan()

            await fetchPrices()
        } catch let apiError as APIError {
            error = apiError
            isLoading = false
        } catch {
            self.error = .unknown(0, error.localizedDescription)
            isLoading = false
        }
    }

    func fetchPrices(forceRefresh: Bool = false, queryOverride: String? = nil) async {
        guard let product else { return }
        priceComparison = nil
        priceError = nil
        // Reset settle-flag state so a refresh re-gates the hero cleanly.
        recommendationState = .pending
        streamClosed = false
        identityLoaded = false
        cardsLoaded = false
        recommendationTask?.cancel()
        recommendationTask = nil
        isPriceLoading = true

        // Step 2c: consume the SSE stream. Each retailer_result event mutates
        // `priceComparison` in place (lazy-seeded on first event). On stream
        // failure, fall back to the batch endpoint.
        //
        // Pull the user's FB Marketplace location (if they've set one) and
        // forward the numeric ID + radius as query params. When absent,
        // the backend skips the per-location cache key and the
        // fb_marketplace container falls back to its env-default slug
        // (sanfrancisco).
        let storedLocation = locationPreferences.current()
        sseLog.info("fetchPrices: starting stream for product \(product.name, privacy: .public) forceRefresh=\(forceRefresh, privacy: .public) queryOverride=\(queryOverride ?? "<none>", privacy: .public) fbLocationId=\(storedLocation?.fbLocationId ?? "<default>", privacy: .public)")
        var sawDone = false
        var sawAnyEvent = false
        do {
            for try await event in apiClient.streamPrices(
                productId: product.id,
                forceRefresh: forceRefresh,
                queryOverride: queryOverride,
                fbLocationId: storedLocation?.fbLocationId,
                fbRadiusMiles: storedLocation?.radiusMiles
            ) {
                sawAnyEvent = true
                sseLog.info("fetchPrices: received event \(String(describing: event), privacy: .public)")
                switch event {
                case .retailerResult(let update):
                    apply(update, for: product)
                case .done(let summary):
                    apply(summary, for: product)
                    sawDone = true
                    sseLog.info("fetchPrices: sawDone=true succeeded=\(summary.retailersSucceeded, privacy: .public) failed=\(summary.retailersFailed, privacy: .public) cached=\(summary.cached, privacy: .public)")
                case .error(let err):
                    sseLog.error("fetchPrices: received error event code=\(err.code, privacy: .public) message=\(err.message, privacy: .public)")
                    priceComparison = nil
                    priceError = .server(err.message)
                    isPriceLoading = false
                    return
                }
            }
            if !sawDone {
                // Stream closed without a `done` event — treat as soft failure
                // and fall back to the batch endpoint.
                sseLog.warning("fetchPrices: stream closed without done — falling back to batch. sawAnyEvent=\(sawAnyEvent, privacy: .public)")
                let seenEvents = sawAnyEvent ? priceComparison : nil
                await fallbackToBatch(
                    product: product,
                    forceRefresh: forceRefresh,
                    preserveSeeded: seenEvents != nil
                )
                return
            }
        } catch let apiError as APIError {
            sseLog.warning("fetchPrices: stream threw APIError — falling back to batch. error=\(apiError.localizedDescription, privacy: .public) sawDone=\(sawDone, privacy: .public)")
            await fallbackToBatch(
                product: product,
                forceRefresh: forceRefresh,
                initialError: apiError
            )
            return
        } catch {
            sseLog.warning("fetchPrices: stream threw unknown error — falling back to batch. error=\(error.localizedDescription, privacy: .public) sawDone=\(sawDone, privacy: .public)")
            await fallbackToBatch(
                product: product,
                forceRefresh: forceRefresh,
                initialError: .unknown(0, error.localizedDescription)
            )
            return
        }

        sseLog.info("fetchPrices: stream completed successfully")
        streamClosed = true
        attemptFetchRecommendation()
        await fetchIdentityDiscounts(productId: product.id)
        isPriceLoading = false
    }

    // MARK: - Step 2d: Identity Discounts

    /// Fetch the list of identity discounts the user qualifies for, scoped to
    /// the currently scanned product so the backend can compute estimated
    /// savings against the best price.
    ///
    /// Non-fatal: any failure logs a warning and leaves `identityDiscounts`
    /// empty. We never set `priceError` here — the retailer list is the
    /// primary UX and must not be hidden by a secondary-feature failure.
    private func fetchIdentityDiscounts(productId: UUID) async {
        do {
            let response = try await identityCache.fetchIdentity(productId: productId, apiClient: apiClient)
            identityDiscounts = response.eligibleDiscounts
            sseLog.info("fetchIdentityDiscounts: received \(response.eligibleDiscounts.count, privacy: .public) discounts for \(response.identityGroupsActive.count, privacy: .public) active groups")
        } catch {
            sseLog.warning("fetchIdentityDiscounts failed: \(error.localizedDescription, privacy: .public)")
            identityDiscounts = []
        }
        identityLoaded = true
        attemptFetchRecommendation()
        await fetchCardRecommendations(productId: productId)
    }

    // MARK: - Step 2e: Card Recommendations

    /// Fetch the best card per retailer for the scanned product. Non-fatal on
    /// failure — the price list and identity discounts stay visible. The
    /// `userHasCards` flag drives the "Add your cards" CTA in
    /// `PriceComparisonView` when no cards are on file.
    private func fetchCardRecommendations(productId: UUID) async {
        do {
            let response = try await identityCache.fetchCards(productId: productId, apiClient: apiClient)
            cardRecommendations = response.recommendations
            userHasCards = response.userHasCards
            sseLog.info("fetchCardRecommendations: received \(response.recommendations.count, privacy: .public) recs userHasCards=\(response.userHasCards, privacy: .public)")
        } catch {
            sseLog.warning("fetchCardRecommendations failed: \(error.localizedDescription, privacy: .public)")
            cardRecommendations = []
        }
        cardsLoaded = true
        attemptFetchRecommendation()
    }

    // MARK: - Step 3e: Recommendation gate

    /// Called on every settle-flag flip. Fires the recommendation fetch only
    /// once per product lifecycle — hero never renders during streaming or
    /// while identity/cards are in flight.
    private func attemptFetchRecommendation() {
        guard streamClosed, identityLoaded, cardsLoaded else { return }
        // Re-fetch guard: skip when a task is in flight or a terminal state
        // has already been reached (loaded OR insufficientData — both are
        // final for this product lifecycle).
        guard recommendationTask == nil, case .pending = recommendationState else {
            return
        }
        guard let product else { return }
        recommendationTask = Task { [weak self] in
            await self?.fetchRecommendation(productId: product.id)
        }
    }

    /// Non-fatal: non-422 failures log to `com.barkain.app`/`Recommendation`
    /// and leave `recommendationState = .pending` (silent-fail contract
    /// preserved — same as identity discounts). A 422 sets
    /// `.insufficientData(reason:)` so the view can render an explicit
    /// "couldn't recommend" card (demo-prep-1 Item 1).
    private func fetchRecommendation(productId: UUID) async {
        let log = Logger(subsystem: "com.barkain.app", category: "Recommendation")
        // Step 3g-B: snapshot membership prefs at fetch time. nil when no
        // portals are toggled on so the request body stays small.
        let memberships = portalMembershipPreferences.current()
        let activeMemberships = memberships.filter { $0.value }
        let userMemberships: [String: Bool]? = activeMemberships.isEmpty
            ? nil : activeMemberships
        do {
            let outcome = try await apiClient.fetchRecommendation(
                productId: productId,
                forceRefresh: false,
                userMemberships: userMemberships
            )
            switch outcome {
            case .loaded(let rec):
                recommendationState = .loaded(rec)
                log.info("recommend: winner=\(rec.winner.retailerId, privacy: .public) savings=\(rec.winner.totalSavings, privacy: .public) compute_ms=\(rec.computeMs, privacy: .public) cached=\(rec.cached, privacy: .public)")
            case .insufficientData(let reason):
                recommendationState = .insufficientData(reason: reason)
                log.info("recommend: insufficient data — rendering fallback card. reason=\(reason, privacy: .public)")
            }
        } catch {
            log.warning("recommend fetch failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    private func apply(_ update: RetailerResultUpdate, for product: Product) {
        var comparison = priceComparison ?? PriceComparison(
            productId: product.id,
            productName: product.name,
            prices: [],
            retailerResults: [],
            totalRetailers: 0,
            retailersSucceeded: 0,
            retailersFailed: 0,
            cached: false,
            fetchedAt: Date()
        )
        let result = RetailerResult(
            retailerId: update.retailerId,
            retailerName: update.retailerName,
            status: update.status
        )
        if let idx = comparison.retailerResults.firstIndex(where: { $0.retailerId == update.retailerId }) {
            comparison.retailerResults[idx] = result
        } else {
            comparison.retailerResults.append(result)
        }
        if update.status == .success, let price = update.price {
            if let idx = comparison.prices.firstIndex(where: { $0.retailerId == price.retailerId }) {
                comparison.prices[idx] = price
            } else {
                comparison.prices.append(price)
            }
        }
        priceComparison = comparison
    }

    private func apply(_ summary: StreamSummary, for product: Product) {
        var comparison = priceComparison ?? PriceComparison(
            productId: product.id,
            productName: product.name,
            prices: [],
            retailerResults: [],
            totalRetailers: 0,
            retailersSucceeded: 0,
            retailersFailed: 0,
            cached: false,
            fetchedAt: Date()
        )
        comparison.totalRetailers = summary.totalRetailers
        comparison.retailersSucceeded = summary.retailersSucceeded
        comparison.retailersFailed = summary.retailersFailed
        comparison.cached = summary.cached
        comparison.fetchedAt = summary.fetchedAt
        priceComparison = comparison
    }

    private func fallbackToBatch(
        product: Product,
        forceRefresh: Bool,
        initialError: APIError? = nil,
        preserveSeeded: Bool = false
    ) async {
        do {
            let batch = try await apiClient.getPrices(
                productId: product.id,
                forceRefresh: forceRefresh
            )
            sseLog.info("fallbackToBatch: batch returned \(batch.prices.count, privacy: .public) prices, \(batch.retailerResults.count, privacy: .public) retailer results")
            priceComparison = batch
            priceError = nil
            // Batch success is equivalent to SSE `done` for the hero gate.
            streamClosed = true
            attemptFetchRecommendation()
            await fetchIdentityDiscounts(productId: product.id)
        } catch let apiError as APIError {
            // Clear any partial seed so callers see a clean failure state.
            if !preserveSeeded {
                priceComparison = nil
            }
            priceError = apiError
        } catch {
            if !preserveSeeded {
                priceComparison = nil
            }
            priceError = .unknown(0, error.localizedDescription)
        }
        isPriceLoading = false
    }

    func reset() {
        scannedUPC = nil
        product = nil
        isLoading = false
        error = nil
        priceComparison = nil
        isPriceLoading = false
        priceError = nil
        identityDiscounts = []
        cardRecommendations = []
        userHasCards = false
        recommendationState = .pending
        streamClosed = false
        identityLoaded = false
        cardsLoaded = false
        recommendationTask?.cancel()
        recommendationTask = nil
    }

    // MARK: - Step 2g: Affiliate URL resolution
    //
    // Called by `PriceComparisonView` when a retailer row is tapped. Fetches
    // the tagged URL from the backend (POST /api/v1/affiliate/click) and
    // returns it. Falls back to the original URL on any thrown error — the
    // user is never blocked from clicking through, even offline or during a
    // backend outage. Returns nil only if the retailer row has no URL.
    func resolveAffiliateURL(for retailerPrice: RetailerPrice) async -> URL? {
        guard let rawUrlString = retailerPrice.url, !rawUrlString.isEmpty else {
            return nil
        }
        return await resolveAffiliateURL(
            retailerId: retailerPrice.retailerId, rawUrlString: rawUrlString
        )
    }

    /// Step 3e — same round-trip for the hero's winner button.
    func resolveAffiliateURL(for path: StackedPath) async -> URL? {
        guard let rawUrlString = path.productUrl, !rawUrlString.isEmpty else {
            return nil
        }
        return await resolveAffiliateURL(
            retailerId: path.retailerId, rawUrlString: rawUrlString
        )
    }

    private func resolveAffiliateURL(
        retailerId: String, rawUrlString: String
    ) async -> URL? {
        let fallback = URL(string: rawUrlString)
        do {
            let response = try await apiClient.getAffiliateURL(
                productId: priceComparison?.productId,
                retailerId: retailerId,
                productURL: rawUrlString
            )
            return URL(string: response.affiliateUrl) ?? fallback
        } catch {
            sseLog.warning(
                "resolveAffiliateURL failed, falling back to original URL: \(error.localizedDescription, privacy: .public)"
            )
            return fallback
        }
    }

    // MARK: - Computed

    var sortedPrices: [RetailerPrice] {
        priceComparison?.prices
            .filter(\.isAvailable)
            .sorted { $0.price < $1.price } ?? []
    }

    var bestPrice: RetailerPrice? {
        sortedPrices.first
    }

    var maxSavings: Double? {
        guard let lowest = sortedPrices.first,
              let highest = sortedPrices.last,
              highest.price > lowest.price else {
            return nil
        }
        return highest.price - lowest.price
    }
}
