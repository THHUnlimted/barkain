import SwiftUI

// MARK: - ScannerView

struct ScannerView: View {

    // MARK: - Properties

    @Environment(\.apiClient) private var apiClient
    @State private var viewModel: ScannerViewModel?
    @State private var scanner = BarcodeScanner()
    @State private var scannerError: BarcodeScannerError?
    @State private var showManualEntry = false
    @State private var manualUPC = ""

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
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    showManualEntry = true
                } label: {
                    Image(systemName: "keyboard")
                        .accessibilityLabel("Enter UPC manually")
                }
            }
        }
        .sheet(isPresented: $showManualEntry) {
            manualEntrySheet
        }
        .task {
            let vm = ScannerViewModel(apiClient: apiClient)
            viewModel = vm
            await startScanner(vm)
        }
        .onChange(of: viewModel?.scannedUPC) { _, newValue in
            if newValue == nil {
                scanner.clearLastScan()
            }
        }
        .onDisappear {
            scanner.stopScanning()
        }
    }

    // MARK: - Manual Entry

    private var manualEntrySheet: some View {
        NavigationStack {
            Form {
                Section("Enter UPC") {
                    TextField("12 or 13 digit UPC", text: $manualUPC)
                        .font(.system(.body, design: .monospaced))
                        .autocorrectionDisabled(true)
                        .textInputAutocapitalization(.never)
                        .submitLabel(.go)
                        .onSubmit { submitManual(manualUPC) }
                    Button("Resolve") {
                        submitManual(manualUPC)
                    }
                }

                Section("Quick picks — untested UPCs") {
                    ForEach(manualUPCPresets, id: \.upc) { preset in
                        Button {
                            submitManual(preset.upc)
                        } label: {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(preset.label)
                                    .font(.barkainBody)
                                    .foregroundStyle(Color.barkainOnSurface)
                                Text(preset.upc)
                                    .font(.system(.caption, design: .monospaced))
                                    .foregroundStyle(Color.barkainOnSurfaceVariant)
                            }
                        }
                    }
                }
            }
            .navigationTitle("Manual UPC")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { showManualEntry = false }
                }
            }
        }
    }

    private func submitManual(_ upc: String) {
        let trimmed = upc
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .filter(\.isNumber)
        guard !trimmed.isEmpty, let viewModel else { return }
        showManualEntry = false
        manualUPC = ""
        Task { await viewModel.handleBarcodeScan(upc: trimmed) }
    }

    private var manualUPCPresets: [(upc: String, label: String)] {
        [
            ("194252818381", "Apple AirPods 3rd Gen (MagSafe)"),
            ("190199098428", "Apple AirPods 2nd Gen"),
            ("887276546810", "Samsung Galaxy Buds 2 (Graphite)"),
            ("887276303987", "Samsung Galaxy Buds (Black)"),
            ("050036359306", "JBL Flip 5 (Teal)"),
            ("050036325455", "JBL Flip 3 (Black)"),
            ("840080537252", "Amazon Fire TV Stick 3rd Gen"),
            ("840080588964", "Amazon Fire TV Stick 4K"),
            ("829610001999", "Roku Streaming Stick+"),
        ]
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
            scanner.clearLastScan()
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
