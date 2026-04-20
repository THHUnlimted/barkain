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
                                .font(.barkainLabel)
                                .tracking(0.6)
                                .textCase(.uppercase)
                                .padding(.horizontal, Spacing.xs)
                                .padding(.vertical, 3)
                                .background(
                                    Capsule(style: .continuous)
                                        .fill(Color.barkainPrimaryFixed)
                                )
                                .foregroundStyle(Color.barkainOnPrimaryContainer)
                        }
                    }

                    HStack(spacing: Spacing.xs) {
                        if let brand = result.brand, !brand.isEmpty {
                            Text(brand)
                                .barkainEyebrow(color: .barkainPrimary)
                        }
                        if let category = result.category, !category.isEmpty {
                            if result.brand?.isEmpty == false {
                                Circle()
                                    .fill(Color.barkainOutlineVariant)
                                    .frame(width: 3, height: 3)
                            }
                            Text(category)
                                .font(.barkainCaption)
                                .foregroundStyle(Color.barkainOnSurfaceVariant)
                        }
                    }
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(Color.barkainOutline)
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
                    image.resizable().scaledToFill()
                default:
                    placeholder
                }
            }
            .frame(width: 56, height: 56)
            .background(Color.barkainSurfaceContainer)
            .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadiusSmall, style: .continuous))
        } else {
            placeholder
        }
    }

    private var placeholder: some View {
        Image(systemName: "shippingbox")
            .font(.title3)
            .foregroundStyle(Color.barkainOutlineVariant)
            .frame(width: 56, height: 56)
            .background(Color.barkainSurfaceContainer)
            .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadiusSmall, style: .continuous))
    }
}
