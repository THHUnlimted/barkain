import SwiftUI

// MARK: - ProductCard

struct ProductCard: View {

    // MARK: - Properties

    let product: Product

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
            if let imageUrl = product.imageUrl, let url = URL(string: imageUrl) {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .aspectRatio(contentMode: .fill)
                    case .failure:
                        imagePlaceholder
                    case .empty:
                        ProgressView()
                            .tint(.barkainPrimary)
                    @unknown default:
                        imagePlaceholder
                    }
                }
            } else {
                imagePlaceholder
            }
        }
        .frame(width: 88, height: 88)
        .background(Color.barkainSurfaceContainerLow)
        .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadiusSmall, style: .continuous))
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
