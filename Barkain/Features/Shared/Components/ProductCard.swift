import SwiftUI

// MARK: - ProductCard

struct ProductCard: View {

    // MARK: - Properties

    let product: Product
    /// Tried after `product.imageUrl` either is nil OR fails to load. The
    /// fallback is typically the price-stream backfill URL
    /// (`PriceComparison.productImageUrl`), which originates from a
    /// scraper hit and is more permissive than third-party CDNs like
    /// `demandware.net` that UPCitemdb sometimes hands us — those return
    /// HTTP 403 to anyone without a hotlink-allowed referrer, so the
    /// primary URL silently fails on-device.
    var fallbackImageUrl: String?

    // Tracks whether the primary URL failed so we can promote the
    // fallback in-place without remounting.
    @State private var primaryFailed: Bool = false

    // MARK: - Body

    var body: some View {
        HStack(spacing: Spacing.md) {
            productImage
            productInfo
            Spacer(minLength: 0)
        }
        .padding(Spacing.md)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .fill(Color.barkainSurfaceContainerLowest)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .stroke(Color.barkainOutlineVariant.opacity(0.12), lineWidth: 1)
        )
        .barkainShadowSoft()
    }

    // MARK: - Subviews

    private var productImage: some View {
        Group {
            if let raw = effectiveImageUrl, let url = URL(string: raw) {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .aspectRatio(contentMode: .fill)
                    case .failure:
                        imagePlaceholder
                            .onAppear {
                                // Primary URL was non-nil but unreachable
                                // (403/404/CORS) — promote fallback if any.
                                if !primaryFailed,
                                   product.imageUrl != nil,
                                   fallbackImageUrl != nil {
                                    primaryFailed = true
                                }
                            }
                    case .empty:
                        ProgressView()
                            .tint(.barkainPrimary)
                    @unknown default:
                        imagePlaceholder
                    }
                }
                // Re-mount AsyncImage when we swap to the fallback so
                // the new URL is fetched.
                .id(raw)
            } else {
                imagePlaceholder
            }
        }
        .frame(width: 88, height: 88)
        .background(Color.barkainSurfaceContainerLow)
        .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadiusSmall, style: .continuous))
    }

    private var effectiveImageUrl: String? {
        if primaryFailed { return fallbackImageUrl }
        return product.imageUrl ?? fallbackImageUrl
    }

    private var imagePlaceholder: some View {
        Image(systemName: "photo")
            .font(.title2)
            .foregroundStyle(Color.barkainOutlineVariant)
    }

    private var productInfo: some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            if let brand = product.brand {
                Text(brand)
                    .barkainEyebrow()
            }

            Text(product.name)
                .font(.barkainTitle2)
                .foregroundStyle(Color.barkainOnSurface)
                .lineLimit(2)

            if let category = product.category {
                Text(category)
                    .font(.barkainCaption)
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
            }
        }
    }
}

// MARK: - Preview

#Preview {
    ProductCard(product: Product(
        id: UUID(),
        upc: "012345678901",
        asin: nil,
        name: "Sony WH-1000XM5 Wireless Headphones",
        brand: "Sony",
        category: "Headphones",
        imageUrl: nil,
        source: "gemini_upc"
    ))
    .padding()
    .background(Color.barkainSurface)
}
