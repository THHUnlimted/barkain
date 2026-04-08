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
    }

    // MARK: - Content

    @ViewBuilder
    private func scannerContent(_ viewModel: ScannerViewModel) -> some View {
        if viewModel.isLoading {
            LoadingState(message: "Resolving product...")
        } else if let product = viewModel.product {
            productResult(product, viewModel: viewModel)
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

    // MARK: - Results

    private func productResult(_ product: Product, viewModel: ScannerViewModel) -> some View {
        ScrollView {
            VStack(spacing: Spacing.lg) {
                ProductCard(product: product)

                if let upc = viewModel.scannedUPC {
                    HStack {
                        Image(systemName: "barcode")
                            .foregroundStyle(Color.barkainOutline)
                        Text("UPC: \(upc)")
                            .font(.barkainCaption)
                            .foregroundStyle(Color.barkainOnSurfaceVariant)
                    }
                }

                Button {
                    viewModel.reset()
                } label: {
                    Text("Scan Another")
                        .font(.barkainHeadline)
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, Spacing.sm)
                        .background(Color.barkainPrimaryGradient)
                        .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadiusLarge))
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
