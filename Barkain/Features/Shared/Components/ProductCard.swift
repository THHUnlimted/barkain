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
            Spacer()
        }
        .padding(Spacing.md)
        .background(Color.barkainSurfaceContainerLowest)
        .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadius))
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
                            .aspectRatio(contentMode: .fit)
                    case .failure:
                        imagePlaceholder
                    case .empty:
                        ProgressView()
                    @unknown default:
                        imagePlaceholder
                    }
                }
            } else {
                imagePlaceholder
            }
        }
        .frame(width: 80, height: 80)
        .background(Color.barkainSurfaceContainerLow)
        .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadiusSmall))
    }

    private var imagePlaceholder: some View {
        Image(systemName: "photo")
            .font(.title2)
            .foregroundStyle(Color.barkainOutline)
    }

    private var productInfo: some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            if let brand = product.brand {
                Text(brand.uppercased())
                    .font(.barkainLabel)
                    .foregroundStyle(Color.barkainPrimary)
                    .tracking(1)
            }

            Text(product.name)
                .font(.barkainHeadline)
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
}
