import Foundation

// MARK: - ScannerViewModel

@Observable
final class ScannerViewModel {

    // MARK: - State

    var scannedUPC: String?
    var product: Product?
    var isLoading = false
    var error: APIError?

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
        isLoading = true

        do {
            let resolvedProduct = try await apiClient.resolveProduct(upc: upc)
            product = resolvedProduct
        } catch let apiError as APIError {
            error = apiError
        } catch {
            self.error = .unknown(0, error.localizedDescription)
        }

        isLoading = false
    }

    func reset() {
        scannedUPC = nil
        product = nil
        isLoading = false
        error = nil
    }
}
