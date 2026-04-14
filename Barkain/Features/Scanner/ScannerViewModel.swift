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

    // MARK: - Dependencies

    private let apiClient: any APIClientProtocol

    // MARK: - Init

    init(apiClient: any APIClientProtocol) {
        self.apiClient = apiClient
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
        isLoading = true

        do {
            let resolvedProduct = try await apiClient.resolveProduct(upc: upc)
            product = resolvedProduct
            isLoading = false
            await fetchPrices()
        } catch let apiError as APIError {
            error = apiError
            isLoading = false
        } catch {
            self.error = .unknown(0, error.localizedDescription)
            isLoading = false
        }
    }

    func fetchPrices(forceRefresh: Bool = false) async {
        guard let product else { return }
        priceComparison = nil
        priceError = nil
        isPriceLoading = true

        // Step 2c: consume the SSE stream. Each retailer_result event mutates
        // `priceComparison` in place (lazy-seeded on first event). On stream
        // failure, fall back to the batch endpoint.
        sseLog.info("fetchPrices: starting stream for product \(product.name, privacy: .public) forceRefresh=\(forceRefresh, privacy: .public)")
        var sawDone = false
        var sawAnyEvent = false
        do {
            for try await event in apiClient.streamPrices(
                productId: product.id,
                forceRefresh: forceRefresh
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
            let response = try await apiClient.getEligibleDiscounts(productId: productId)
            identityDiscounts = response.eligibleDiscounts
            sseLog.info("fetchIdentityDiscounts: received \(response.eligibleDiscounts.count, privacy: .public) discounts for \(response.identityGroupsActive.count, privacy: .public) active groups")
        } catch {
            sseLog.warning("fetchIdentityDiscounts failed: \(error.localizedDescription, privacy: .public)")
            identityDiscounts = []
        }
        await fetchCardRecommendations(productId: productId)
    }

    // MARK: - Step 2e: Card Recommendations

    /// Fetch the best card per retailer for the scanned product. Non-fatal on
    /// failure — the price list and identity discounts stay visible. The
    /// `userHasCards` flag drives the "Add your cards" CTA in
    /// `PriceComparisonView` when no cards are on file.
    private func fetchCardRecommendations(productId: UUID) async {
        do {
            let response = try await apiClient.getCardRecommendations(productId: productId)
            cardRecommendations = response.recommendations
            userHasCards = response.userHasCards
            sseLog.info("fetchCardRecommendations: received \(response.recommendations.count, privacy: .public) recs userHasCards=\(response.userHasCards, privacy: .public)")
        } catch {
            sseLog.warning("fetchCardRecommendations failed: \(error.localizedDescription, privacy: .public)")
            cardRecommendations = []
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
