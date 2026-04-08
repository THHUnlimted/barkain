import SwiftUI

// MARK: - PriceComparisonView

struct PriceComparisonView: View {

    // MARK: - Properties

    let product: Product
    let comparison: PriceComparison
    let viewModel: ScannerViewModel

    // MARK: - Body

    var body: some View {
        ScrollView {
            VStack(spacing: Spacing.lg) {
                ProductCard(product: product)
                savingsSection

                if viewModel.sortedPrices.isEmpty {
                    EmptyState(
                        icon: "bag.badge.questionmark",
                        title: "No prices found",
                        subtitle: "None of the \(comparison.totalRetailers) retailers had this product available.",
                        actionTitle: "Refresh"
                    ) {
                        Task { await viewModel.fetchPrices(forceRefresh: true) }
                    }
                } else {
                    sectionHeader
                    priceList
                }

                statusBar
                actionButtons
            }
            .padding(Spacing.lg)
        }
    }

    // MARK: - Savings

    @ViewBuilder
    private var savingsSection: some View {
        if let savings = viewModel.maxSavings, savings > 0,
           let highest = viewModel.sortedPrices.last {
            SavingsBadge(savedAmount: savings, originalPrice: highest.price)
        }
    }

    // MARK: - Section Header

    private var sectionHeader: some View {
        HStack {
            Text("Marketplace Comparison")
                .font(.barkainTitle2)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
            Spacer()
        }
    }

    // MARK: - Price List

    private var priceList: some View {
        VStack(spacing: Spacing.xs) {
            ForEach(Array(viewModel.sortedPrices.enumerated()), id: \.element.id) { index, retailerPrice in
                Button {
                    openRetailerURL(retailerPrice.url)
                } label: {
                    PriceRow(retailerPrice: retailerPrice)
                }
                .buttonStyle(.plain)
                .overlay(alignment: .topTrailing) {
                    if index == 0 {
                        bestBarkainBadge
                    }
                }
            }
        }
    }

    // MARK: - Best Barkain Badge

    private var bestBarkainBadge: some View {
        HStack(spacing: Spacing.xxs) {
            Image(systemName: "pawprint.fill")
                .font(.system(size: 10))
            Text("BEST BARKAIN")
                .font(.barkainLabel)
                .tracking(0.5)
        }
        .foregroundStyle(Color.barkainOnSurface)
        .padding(.horizontal, Spacing.sm)
        .padding(.vertical, 4)
        .background(Color.barkainPrimaryContainer)
        .clipShape(Capsule())
        .offset(x: -Spacing.sm, y: -Spacing.sm)
    }

    // MARK: - Status Bar

    private var statusBar: some View {
        HStack {
            Text("Showing \(comparison.retailersSucceeded) of \(comparison.totalRetailers) retailers")
                .font(.barkainCaption)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
            Spacer()
            if comparison.retailersFailed > 0 && !comparison.cached {
                Text("\(comparison.retailersFailed) unavailable")
                    .font(.barkainCaption)
                    .foregroundStyle(Color.barkainError)
            }
        }
        .padding(.horizontal, Spacing.xs)
    }

    // MARK: - Actions

    private var actionButtons: some View {
        VStack(spacing: Spacing.sm) {
            Button {
                Task { await viewModel.fetchPrices(forceRefresh: true) }
            } label: {
                HStack {
                    Image(systemName: "arrow.clockwise")
                    Text("Refresh Prices")
                }
                .font(.barkainHeadline)
                .foregroundStyle(Color.barkainPrimary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, Spacing.sm)
                .background(Color.barkainSurfaceContainerLow)
                .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadiusLarge))
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
    }

    // MARK: - Helpers

    private func openRetailerURL(_ urlString: String?) {
        guard let urlString, let url = URL(string: urlString) else { return }
        UIApplication.shared.open(url)
    }
}

// MARK: - Preview

#Preview {
    PriceComparisonView(
        product: Product(
            id: UUID(),
            upc: "012345678901",
            asin: "B0BSHF7WHN",
            name: "Sony WH-1000XM5",
            brand: "Sony",
            category: "headphones",
            imageUrl: nil,
            source: "gemini_upc"
        ),
        comparison: PriceComparison(
            productId: UUID(),
            productName: "Sony WH-1000XM5",
            prices: [
                RetailerPrice(retailerId: "amazon", retailerName: "Amazon", price: 298.00, originalPrice: 349.99, currency: "USD", url: nil, condition: "new", isAvailable: true, isOnSale: true, lastChecked: Date()),
                RetailerPrice(retailerId: "best_buy", retailerName: "Best Buy", price: 329.99, originalPrice: nil, currency: "USD", url: nil, condition: "new", isAvailable: true, isOnSale: false, lastChecked: Date()),
                RetailerPrice(retailerId: "walmart", retailerName: "Walmart", price: 299.99, originalPrice: nil, currency: "USD", url: nil, condition: "new", isAvailable: true, isOnSale: false, lastChecked: Date()),
            ],
            totalRetailers: 11,
            retailersSucceeded: 3,
            retailersFailed: 0,
            cached: false,
            fetchedAt: Date()
        ),
        viewModel: {
            let vm = ScannerViewModel(apiClient: PreviewAPIClient())
            return vm
        }()
    )
}

// MARK: - Preview Helper

private struct PreviewAPIClient: APIClientProtocol {
    func resolveProduct(upc: String) async throws -> Product {
        fatalError("Preview only")
    }
    func getPrices(productId: UUID, forceRefresh: Bool) async throws -> PriceComparison {
        fatalError("Preview only")
    }
}
