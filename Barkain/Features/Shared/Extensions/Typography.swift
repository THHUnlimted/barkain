import SwiftUI

// MARK: - Barkain Typography

extension Font {

    // MARK: - Headlines (approximates Plus Jakarta Sans)

    /// Large title — 34pt rounded bold
    static let barkainLargeTitle: Font = .system(.largeTitle, design: .rounded, weight: .black)

    /// Title — 28pt rounded bold
    static let barkainTitle: Font = .system(.title, design: .rounded, weight: .bold)

    /// Title 2 — 22pt rounded bold
    static let barkainTitle2: Font = .system(.title2, design: .rounded, weight: .bold)

    /// Headline — 17pt rounded semibold
    static let barkainHeadline: Font = .system(.headline, design: .rounded, weight: .semibold)

    // MARK: - Body (approximates Manrope)

    /// Body — 17pt medium
    static let barkainBody: Font = .system(.body, weight: .medium)

    /// Subheadline — 15pt regular
    static let barkainSubheadline: Font = .system(.subheadline, weight: .regular)

    /// Caption — 12pt medium
    static let barkainCaption: Font = .system(.caption, weight: .medium)

    /// Small label — 10pt bold uppercase
    static let barkainLabel: Font = .system(size: 10, weight: .bold, design: .default)
}
