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
                                .foregroundStyle(Color.barkainOnPrimaryFixed)
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

    // thumbnail-coverage-L1: when there's no `imageUrl` (Tier 3 Gemini
    // search rows, plus any tier where the upstream returned null
    // images) prefer brand initials on a warm-gold gradient over the
    // generic shippingbox icon. Reads more "result card", less
    // "missing image". Falls back to pawprint when no brand is
    // available — matches the rest of the app's empty-state iconography
    // (HomeView hero + RECENTLY SNIFFED list).
    @ViewBuilder
    private var placeholder: some View {
        if let initials = Self.brandInitials(from: result.brand), !initials.isEmpty {
            Text(initials)
                .font(.system(size: 18, weight: .bold, design: .rounded))
                .foregroundStyle(.white)
                .shadow(color: .black.opacity(0.18), radius: 1, x: 0, y: 1)
                .frame(width: 56, height: 56)
                .background(Color.barkainPrimaryGradient)
                .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadiusSmall, style: .continuous))
                .accessibilityIdentifier("searchResultRowInitials")
        } else {
            Image(systemName: "pawprint.fill")
                .font(.title3)
                .foregroundStyle(Color.barkainPrimary.opacity(0.55))
                .frame(width: 56, height: 56)
                .background(Color.barkainPrimaryFixed.opacity(0.45))
                .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadiusSmall, style: .continuous))
                .accessibilityIdentifier("searchResultRowPawprintPlaceholder")
        }
    }

    /// Pull up to two leading initials from a brand string. Returns nil
    /// for nil / empty input, and for inputs whose first non-whitespace
    /// glyph is non-alphabetic (e.g. "(generic)") so we don't render a
    /// useless "(" tile. Internal so unit tests can pin behavior.
    static func brandInitials(from brand: String?) -> String? {
        guard let raw = brand else { return nil }
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }

        // Tokenize on whitespace + hyphen so "Rust-Oleum" → ["Rust", "Oleum"]
        // and "Apple Inc" → ["Apple", "Inc"]. Drop empty pieces.
        let separators: CharacterSet = .whitespacesAndNewlines.union(CharacterSet(charactersIn: "-"))
        let tokens = trimmed
            .components(separatedBy: separators)
            .filter { !$0.isEmpty }

        // Multi-token: take first letter of the first two tokens that
        // start with a letter. e.g. "Rust-Oleum" → "RO", "Apple Inc" → "AI",
        // "3M Company" → "C" (skips digit-leading "3M" and lands on "Company").
        // Single-token: require the token to START with a letter, then
        // take up to two leading letters. "(generic)" / "123" / "—" return
        // nil so the caller falls back to the pawprint placeholder rather
        // than rendering "GE" / nothing / nothing.
        var initials: [Character] = []
        if tokens.count >= 2 {
            for token in tokens where initials.count < 2 {
                if let first = token.first, first.isLetter {
                    initials.append(Character(first.uppercased()))
                }
            }
        } else if let only = tokens.first, let firstChar = only.first, firstChar.isLetter {
            for ch in only.prefix(2) where initials.count < 2 {
                if ch.isLetter {
                    initials.append(Character(ch.uppercased()))
                }
            }
        }

        guard !initials.isEmpty else { return nil }
        return String(initials)
    }
}
