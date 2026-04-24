import SwiftUI

// MARK: - ScannerView

struct ScannerView: View {

    // MARK: - Properties

    @Environment(\.apiClient) private var apiClient
    @Environment(FeatureGateService.self) private var featureGate
    @Environment(\.recentlyScanned) private var recentlyScanned
    @Environment(\.tabSelection) private var tabSelection
    @State private var viewModel: ScannerViewModel?
    @State private var scanner = BarcodeScanner()
    @State private var scannerError: BarcodeScannerError?
    @State private var showManualEntry = false
    @State private var manualUPC = ""
    @State private var showOnboardingFromCTA = false
    @State private var showAddCardsFromCTA = false
    // Owned here so the .sheet survives any inline conditional re-render
    // in `scannerContent` — same fix as SearchView (2026-04-19).
    @State private var browserURL: IdentifiableURL?

    @AppStorage("hasCompletedIdentityOnboarding")
    private var hasCompletedOnboarding: Bool = false

    // MARK: - Body

    var body: some View {
        ZStack {
            Color.barkainSurface.ignoresSafeArea()

            if let viewModel {
                scannerContent(viewModel)
                    .animation(.easeInOut(duration: 0.45), value: viewModel.isPriceLoading)
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
                .accessibilityIdentifier("manualEntryButton")
            }
        }
        .sheet(isPresented: $showManualEntry) {
            manualEntrySheet
        }
        .sheet(isPresented: $showOnboardingFromCTA) {
            IdentityOnboardingView(
                viewModel: IdentityOnboardingViewModel(apiClient: apiClient),
                hasCompletedOnboarding: $hasCompletedOnboarding
            )
        }
        .sheet(isPresented: $showAddCardsFromCTA, onDismiss: {
            // Refresh recommendations so `userHasCards` reflects newly-added cards.
            // The stream path is short-circuited by the Redis cache.
            if let vm = viewModel, vm.product != nil {
                Task { await vm.fetchPrices() }
            }
        }) {
            CardSelectionView(apiClient: apiClient)
        }
        // Step 2f: present the RevenueCat paywall when the scan quota is hit.
        // Bound to viewModel.showPaywall — flipped true in handleBarcodeScan
        // when featureGate.scanLimitReached.
        .sheet(isPresented: paywallBinding) {
            PaywallHost(
                onPurchase: {
                    // Reset the scanner so the user can immediately re-scan
                    // after upgrading. Their pending UPC is unchanged.
                    scanner.clearLastScan()
                },
                onRestore: {
                    scanner.clearLastScan()
                }
            )
        }
        .sheet(item: $browserURL) { item in
            InAppBrowserView(url: item.url)
                .ignoresSafeArea()
        }
        .task {
            let vm = ScannerViewModel(apiClient: apiClient, featureGate: featureGate)
            viewModel = vm
            await startScanner(vm)
        }
        .onChange(of: viewModel?.scannedUPC) { _, newValue in
            if newValue == nil {
                scanner.clearLastScan()
            }
        }
        .onChange(of: viewModel?.product?.id) { _, newValue in
            // Record every successful resolve into the Home tab's
            // "Recently Scanned" rail. The store dedupes on id so
            // re-scanning the same product just moves it to the front.
            guard let product = viewModel?.product, product.id == newValue else { return }
            recentlyScanned.record(
                id: product.id,
                upc: product.upc,
                name: product.name,
                brand: product.brand,
                imageUrl: product.imageUrl
            )
        }
        .onDisappear {
            scanner.stopScanning()
        }
    }

    // MARK: - Paywall Binding (Step 2f)

    /// Bridge `viewModel?.showPaywall` to a non-optional `Binding<Bool>` for
    /// the `.sheet` modifier. SwiftUI sheet bindings can't be optional, so
    /// we collapse the optional-vm case to false.
    private var paywallBinding: Binding<Bool> {
        Binding(
            get: { viewModel?.showPaywall ?? false },
            set: { viewModel?.showPaywall = $0 }
        )
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
                        .accessibilityIdentifier("upcTextField")
                    Button("Resolve") {
                        submitManual(manualUPC)
                    }
                    .accessibilityIdentifier("resolveButton")
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
        } else if let comparison = viewModel.priceComparison, let product = viewModel.product {
            // PriceComparisonView owns both the loading and loaded states —
            // it shows the hero above streaming retailer rows while loading,
            // and fades savings / discounts / cards in when loading closes.
            PriceComparisonView(
                product: product,
                comparison: comparison,
                viewModel: viewModel,
                browserURL: $browserURL,
                onRequestOnboarding: { showOnboardingFromCTA = true },
                onRequestAddCards: { showAddCardsFromCTA = true },
                onRequestUpgrade: { viewModel.showPaywall = true }
            )
            .transition(.opacity)
        } else if viewModel.isPriceLoading, let product = viewModel.product {
            // Pre-first-event fallback — brief window before the first SSE
            // event seeds `priceComparison`.
            PriceLoadingHero(product: product)
                .transition(.opacity)
        } else if viewModel.priceError != nil, let product = viewModel.product {
            priceErrorView(product: product, viewModel: viewModel)
        } else if viewModel.error == .notFound {
            unresolvedProductView(viewModel: viewModel)
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

            // Subtle dark gradient over the raw camera feed so our overlay
            // chrome reads clearly regardless of ambient brightness.
            LinearGradient(
                colors: [
                    Color.black.opacity(0.35),
                    Color.black.opacity(0.10),
                    Color.black.opacity(0.45)
                ],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea()

            scanOverlay
        }
    }

    private var scanOverlay: some View {
        VStack {
            topHeroBanner
            Spacer()
            viewfinderFrame
            Spacer()
            helpChip
                .padding(.bottom, Spacing.xxl)
        }
        .padding(.horizontal, Spacing.lg)
    }

    /// Gradient capsule at the top of the preview: brand pawprint + tagline.
    private var topHeroBanner: some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: "pawprint.fill")
                .font(.headline)
                .foregroundStyle(.white)
            Text("Sniff out a barcode")
                .font(.barkainHeadline)
                .foregroundStyle(.white)
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.sm)
        .background(
            Capsule(style: .continuous)
                .fill(Color.barkainPrimaryGradient)
        )
        .barkainShadowGlow()
        .padding(.top, Spacing.sm)
    }

    /// Corners-only rounded-rectangle viewfinder in brand gold. Gives the
    /// user a clear "aim here" target without dimming the camera feed.
    private var viewfinderFrame: some View {
        GeometryReader { geo in
            let side = min(geo.size.width, 320)
            ZStack {
                RoundedRectangle(cornerRadius: Spacing.cornerRadiusLarge, style: .continuous)
                    .stroke(Color.barkainPrimaryContainer.opacity(0.85), lineWidth: 3)
                    .frame(width: side, height: side * 0.58)
                    .position(x: geo.size.width / 2, y: geo.size.height / 2)
                    .barkainShadowGlow()
            }
        }
        .frame(height: 220)
    }

    /// Bottom hint chip — describes both camera + manual entry in one place.
    private var helpChip: some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: "barcode.viewfinder")
                .foregroundStyle(Color.barkainPrimaryContainer)
            Text("Point the camera at a barcode")
                .font(.barkainBody)
                .foregroundStyle(.white)
            Text("·")
                .foregroundStyle(.white.opacity(0.6))
            Text("or tap")
                .font(.barkainCaption)
                .foregroundStyle(.white.opacity(0.8))
            Image(systemName: "keyboard")
                .font(.caption)
                .foregroundStyle(.white.opacity(0.9))
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.sm)
        .background(
            Capsule(style: .continuous)
                .fill(.ultraThinMaterial)
        )
        .overlay(
            Capsule(style: .continuous)
                .stroke(Color.white.opacity(0.15), lineWidth: 1)
        )
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

    /// demo-prep-1 Item 2: dedicated view for the 404 "couldn't resolve
    /// this UPC" case. Split from `errorView` so the common "product
    /// Barkain hasn't indexed" scenario gets friendly copy and two clear
    /// next-step CTAs instead of a generic exclamation-triangle with
    /// "Try Again" on the same failing UPC.
    private func unresolvedProductView(viewModel: ScannerViewModel) -> some View {
        UnresolvedProductView(
            primaryActionTitle: "Scan another item",
            primaryAction: {
                scanner.clearLastScan()
                viewModel.reset()
            },
            secondaryActionTitle: "Search by name instead",
            secondaryAction: {
                scanner.clearLastScan()
                viewModel.reset()
                tabSelection.onSearch()
            }
        )
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
