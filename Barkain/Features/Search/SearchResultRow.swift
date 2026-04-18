import SwiftUI

// MARK: - SearchResultRow

struct SearchResultRow: View {

    // MARK: - Properties

    let result: ProductSearchResult
    let onTap: () -> Void

    // MARK: - Body

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: Spacing.md) {
                thumbnail

                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    HStack(spacing: Spacing.xs) {
                        Text(result.deviceName)
                            .font(.barkainHeadline)
                            .foregroundStyle(Color.barkainOnSurface)
                            .lineLimit(2)
                            .multilineTextAlignment(.leading)
                        if result.source == .generic {
                            Text("Any variant")
                                .font(.barkainCaption)
                                .padding(.horizontal, Spacing.xs)
                                .padding(.vertical, 2)
                                .background(Color.barkainPrimaryFixed)
                                .foregroundStyle(Color.barkainOnSurface)
                                .clipShape(Capsule())
                        }
                    }

                    HStack(spacing: Spacing.xs) {
                        if let brand = result.brand, !brand.isEmpty {
                            Text(brand)
                                .font(.barkainCaption)
                                .foregroundStyle(Color.barkainOnSurfaceVariant)
                        }
                        if let category = result.category, !category.isEmpty {
                            Text("·")
                                .foregroundStyle(Color.barkainOutlineVariant)
                            Text(category)
                                .font(.barkainCaption)
                                .foregroundStyle(Color.barkainOnSurfaceVariant)
                        }
                    }
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.caption)
                    .foregroundStyle(Color.barkainOutlineVariant)
            }
            .padding(.vertical, Spacing.sm)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("searchResultRow_\(result.id)")
    }

    // MARK: - Thumbnail

    @ViewBuilder
    private var thumbnail: some View {
        if let urlString = result.imageUrl, let url = URL(string: urlString) {
            AsyncImage(url: url) { phase in
                switch phase {
                case .success(let image):
                    image.resizable().scaledToFit()
                default:
                    placeholder
                }
            }
            .frame(width: 48, height: 48)
            .background(Color.barkainSurfaceContainer)
            .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadiusSmall))
        } else {
            placeholder
        }
    }

    private var placeholder: some View {
        Image(systemName: "shippingbox")
            .font(.title3)
            .foregroundStyle(Color.barkainOutlineVariant)
            .frame(width: 48, height: 48)
            .background(Color.barkainSurfaceContainer)
            .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadiusSmall))
    }
}
