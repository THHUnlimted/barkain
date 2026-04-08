import Foundation

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

        do {
            priceComparison = try await apiClient.getPrices(
                productId: product.id,
                forceRefresh: forceRefresh
            )
        } catch let apiError as APIError {
            priceError = apiError
        } catch {
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
