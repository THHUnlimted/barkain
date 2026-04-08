import SwiftUI

// MARK: - ScannerView

struct ScannerView: View {

    // MARK: - Properties

    @Environment(\.apiClient) private var apiClient
    @State private var viewModel: ScannerViewModel?
    @State private var scanner = BarcodeScanner()
    @State private var scannerError: BarcodeScannerError?

    // MARK: - Body

    var body: some View {
        ZStack {
            Color.barkainSurface.ignoresSafeArea()

            if let viewModel {
                scannerContent(viewModel)
            } else {
                LoadingState(message: "Preparing scanner...")
            }
        }
        .navigationTitle("Scan")
        .task {
            let vm = ScannerViewModel(apiClient: apiClient)
            viewModel = vm
            await startScanner(vm)
        }
        .onDisappear {
            scanner.stopScanning()
        }
    }

    // MARK: - Content

    @ViewBuilder
    private func scannerContent(_ viewModel: ScannerViewModel) -> some View {
        if viewModel.isLoading {
            LoadingState(message: "Resolving product...")
        } else if viewModel.isPriceLoading, let product = viewModel.product {
            priceLoadingView(product: product)
        } else if let comparison = viewModel.priceComparison, let product = viewModel.product {
            PriceComparisonView(
                product: product,
                comparison: comparison,
                viewModel: viewModel
            )
        } else if viewModel.priceError != nil, let product = viewModel.product {
            priceErrorView(product: product, viewModel: viewModel)
        } else if let error = viewModel.error {
            errorView(error, viewModel: viewModel)
        } else if let scannerError {
            cameraErrorView(scannerError)
        } else {
            cameraView(viewModel)
        }
    }

    // MARK: - Camera

    private func cameraView(_ viewModel: ScannerViewModel) -> some View {
        ZStack {
            CameraPreviewView(session: scanner.captureSession)
                .ignoresSafeArea()

            scanOverlay
        }
    }

    private var scanOverlay: some View {
        VStack {
            Spacer()
            VStack(spacing: Spacing.sm) {
                Image(systemName: "barcode.viewfinder")
                    .font(.system(size: 28))
                    .foregroundStyle(Color.barkainPrimaryContainer)
                Text("Point camera at a barcode")
                    .font(.barkainBody)
                    .foregroundStyle(.white)
            }
            .padding(Spacing.lg)
            .background(.ultraThinMaterial)
            .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadius))
            .padding(.bottom, Spacing.xxl)
        }
    }

    // MARK: - Price Loading

    private func priceLoadingView(product: Product) -> some View {
        ScrollView {
            VStack(spacing: Spacing.lg) {
                ProductCard(product: product)
                ProgressiveLoadingView(retailers: loadingRetailerItems)
            }
            .padding(Spacing.lg)
        }
    }

    private var loadingRetailerItems: [RetailerLoadingItem] {
        [
            ("amazon", "Amazon"),
            ("best_buy", "Best Buy"),
            ("walmart", "Walmart"),
            ("target", "Target"),
            ("home_depot", "Home Depot"),
            ("lowes", "Lowe's"),
            ("ebay_new", "eBay (New)"),
            ("ebay_used", "eBay (Used)"),
            ("sams_club", "Sam's Club"),
            ("backmarket", "BackMarket"),
            ("fb_marketplace", "Facebook Marketplace"),
        ].map { RetailerLoadingItem(id: $0.0, name: $0.1, status: .loading) }
    }

    // MARK: - Price Error

    private func priceErrorView(product: Product, viewModel: ScannerViewModel) -> some View {
        ScrollView {
            VStack(spacing: Spacing.lg) {
                ProductCard(product: product)

                EmptyState(
                    icon: "exclamationmark.triangle",
                    title: "Couldn't fetch prices",
                    subtitle: viewModel.priceError?.errorDescription ?? "An unknown error occurred.",
                    actionTitle: "Retry"
                ) {
                    Task { await viewModel.fetchPrices() }
                }

                Button {
                    viewModel.reset()
                } label: {
                    Text("Scan Another")
                        .font(.barkainBody)
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                }
            }
            .padding(Spacing.lg)
        }
    }

    // MARK: - Errors

    private func errorView(_ error: APIError, viewModel: ScannerViewModel) -> some View {
        EmptyState(
            icon: "exclamationmark.triangle",
            title: "Something went wrong",
            subtitle: error.errorDescription ?? "An unknown error occurred.",
            actionTitle: "Try Again"
        ) {
            viewModel.reset()
        }
    }

    private func cameraErrorView(_ error: BarcodeScannerError) -> some View {
        EmptyState(
            icon: "camera.fill",
            title: "Camera Unavailable",
            subtitle: error.errorDescription ?? "Cannot access camera."
        )
    }

    // MARK: - Scanner Setup

    private func startScanner(_ viewModel: ScannerViewModel) async {
        do {
            try await scanner.startScanning()
        } catch let error as BarcodeScannerError {
            scannerError = error
            return
        } catch {
            scannerError = .configurationFailed
            return
        }

        for await code in scanner.scannedCodes {
            await viewModel.handleBarcodeScan(upc: code)
        }
    }
}

// MARK: - Preview

#Preview {
    NavigationStack {
        ScannerView()
    }
}
