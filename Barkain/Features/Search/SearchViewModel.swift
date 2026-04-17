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
    var recentSearches: [String] = []

    /// Set by `handleResultTap` when a Gemini result lacks a primary UPC —
    /// the view surfaces this as a toast so the user knows to scan instead.
    var resolveFailureMessage: String?

    /// Present after a successful tap — the `PriceComparisonView` is driven
    /// by this ScannerViewModel (same destination as the Scanner tab uses).
    var presentedProductViewModel: ScannerViewModel?

    // MARK: - Dependencies

    @ObservationIgnored private let apiClient: any APIClientProtocol
    @ObservationIgnored private let featureGate: FeatureGateService
    @ObservationIgnored private let userDefaults: UserDefaults
    @ObservationIgnored private let debounceNanos: UInt64
    @ObservationIgnored private let clock: @Sendable () async throws -> Void

    @ObservationIgnored private var searchTask: Task<Void, Never>?

    // MARK: - Constants

    static let recentSearchesKey = "recentSearches"
    static let maxRecentSearches = 10
    static let defaultMaxResults = 10
    nonisolated static let defaultDebounceNanos: UInt64 = 300_000_000  // 300ms

    // MARK: - Init

    init(
        apiClient: any APIClientProtocol,
        featureGate: FeatureGateService? = nil,
        userDefaults: UserDefaults = .standard,
        debounceNanos: UInt64 = SearchViewModel.defaultDebounceNanos,
        clock: (@Sendable () async throws -> Void)? = nil
    ) {
        self.apiClient = apiClient
        self.featureGate = featureGate ?? FeatureGateService(proTierProvider: { false })
        self.userDefaults = userDefaults
        self.debounceNanos = debounceNanos
        let capturedDebounce = debounceNanos
        self.clock = clock ?? {
            try await Task.sleep(nanoseconds: capturedDebounce)
        }
        self.recentSearches = Self.loadRecentSearches(from: userDefaults)
    }

    // MARK: - Actions

    /// Called whenever the search-bar text changes. Cancels any in-flight
    /// search task, sleeps for the debounce interval, and then performs the
    /// search if the task is still live. On empty query, clears results.
    func queryChanged(_ newValue: String) {
        query = newValue
        error = nil
        searchTask?.cancel()

        // If a previous tap left a PriceComparisonView on screen, dismiss it
        // as soon as the user edits the search bar — otherwise the results
        // list is hidden behind the comparison view and typing feels dead.
        if presentedProductViewModel != nil {
            presentedProductViewModel = nil
        }

        let trimmed = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            results = []
            isLoading = false
            return
        }

        if trimmed.count < 3 {
            // Backend will 422; don't bother sending.
            results = []
            isLoading = false
            return
        }

        searchTask = Task { [weak self] in
            guard let self else { return }
            do {
                try await self.clock()
            } catch {
                return
            }
            if Task.isCancelled { return }
            await self.performSearch(trimmed)
        }
    }

    /// Direct (non-debounced) entry point used by recent-search taps + tests.
    func performSearch(_ text: String) async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await apiClient.searchProducts(
                query: text,
                maxResults: Self.defaultMaxResults
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

    /// Called when the user taps a result row. For DB-sourced rows the
    /// `Product` is constructed from the row fields directly (no extra
    /// request needed). For Gemini-sourced rows with a `primary_upc` we
    /// run the existing `/products/resolve` path so the Product is created
    /// or reused in the DB. Gemini rows without a UPC surface a toast —
    /// we don't have a safe way to price them without a canonical identifier.
    func handleResultTap(_ result: ProductSearchResult) async {
        addToRecentSearches(query)
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

        case .gemini:
            isLoading = true
            defer { isLoading = false }
            do {
                let product: Product
                if let upc = result.primaryUpc, !upc.isEmpty {
                    product = try await apiClient.resolveProduct(upc: upc)
                } else {
                    // Gemini returned this row without a UPC — run the tap-time
                    // device→UPC lookup via /resolve-from-search so older /
                    // discontinued SKUs still resolve to a persisted Product.
                    product = try await apiClient.resolveProductFromSearch(
                        deviceName: result.deviceName,
                        brand: result.brand,
                        model: result.model
                    )
                }
                await presentProduct(product)
            } catch APIError.notFound {
                resolveFailureMessage = "Couldn't find a barcode for this product — try scanning it instead."
            } catch let apiError as APIError {
                error = apiError
            } catch {
                self.error = .unknown(0, error.localizedDescription)
            }
        }
    }

    private func presentProduct(_ product: Product) async {
        let vm = ScannerViewModel(apiClient: apiClient, featureGate: featureGate)
        // Inject the already-resolved product so handleBarcodeScan's redundant
        // resolve call is skipped — jump straight to the price stream.
        vm.scannedUPC = product.upc
        vm.product = product
        presentedProductViewModel = vm
        await vm.fetchPrices()
    }

    // MARK: - Recent searches (@AppStorage-backed via UserDefaults)

    func addToRecentSearches(_ raw: String) {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count >= 3 else { return }

        var updated = recentSearches.filter { $0.lowercased() != trimmed.lowercased() }
        updated.insert(trimmed, at: 0)
        if updated.count > Self.maxRecentSearches {
            updated = Array(updated.prefix(Self.maxRecentSearches))
        }
        recentSearches = updated
        Self.saveRecentSearches(updated, to: userDefaults)
    }

    func clearRecentSearches() {
        recentSearches = []
        userDefaults.removeObject(forKey: Self.recentSearchesKey)
    }

    func selectRecentSearch(_ text: String) {
        query = text
        presentedProductViewModel = nil
        searchTask?.cancel()
        searchTask = Task { [weak self] in
            guard let self else { return }
            await self.performSearch(text)
        }
    }

    // MARK: - Persistence helpers

    private static func loadRecentSearches(from defaults: UserDefaults) -> [String] {
        guard let data = defaults.data(forKey: recentSearchesKey),
              let decoded = try? JSONDecoder().decode([String].self, from: data)
        else {
            return []
        }
        return decoded
    }

    private static func saveRecentSearches(_ searches: [String], to defaults: UserDefaults) {
        guard let data = try? JSONEncoder().encode(searches) else {
            searchLog.error("Failed to encode recent searches")
            return
        }
        defaults.set(data, forKey: recentSearchesKey)
    }
}
