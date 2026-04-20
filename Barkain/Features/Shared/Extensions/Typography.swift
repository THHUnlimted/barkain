import SwiftUI

// MARK: - Barkain Typography
//
// System fonts only. Rounded design on headlines gives the brand its warmth
// without asking callers to bundle Plus Jakarta / Manrope.

extension Font {

    // MARK: - Headlines (rounded system)

    /// Display hero — 40pt black rounded. Pair with `.barkainDisplayTracking()`.
    static let barkainDisplay: Font = .system(size: 40, weight: .black, design: .rounded)

    /// Large title — 34pt black rounded.
    static let barkainLargeTitle: Font = .system(.largeTitle, design: .rounded, weight: .black)

    /// Title — 28pt bold rounded.
    static let barkainTitle: Font = .system(.title, design: .rounded, weight: .bold)

    /// Title 2 — 22pt bold rounded.
    static let barkainTitle2: Font = .system(.title2, design: .rounded, weight: .bold)

    /// Headline — 17pt semibold rounded.
    static let barkainHeadline: Font = .system(.headline, design: .rounded, weight: .semibold)

    // MARK: - Body (default system)

    /// Body — 17pt medium.
    static let barkainBody: Font = .system(.body, weight: .medium)

    /// Subheadline — 15pt regular.
    static let barkainSubheadline: Font = .system(.subheadline, weight: .regular)

    /// Caption — 12pt medium.
    static let barkainCaption: Font = .system(.caption, weight: .medium)

    /// Label — 10pt bold, intended for uppercase eyebrow tags. Pair with
    /// `.tracking(1.5)` and `.textCase(.uppercase)` or call `.barkainEyebrow()`.
    static let barkainLabel: Font = .system(size: 10, weight: .bold, design: .default)
}

// MARK: - Text Style Modifiers

extension View {

    /// Eyebrow label styling — uppercase, wide-tracked, primary-tinted.
    func barkainEyebrow(color: Color = .barkainPrimary) -> some View {
        self
            .font(.barkainLabel)
            .tracking(1.5)
            .textCase(.uppercase)
            .foregroundStyle(color)
    }

    /// Tight headline tracking for display-sized copy. Apply after `.font(...)`.
    func barkainDisplayTracking() -> some View {
        self.tracking(-0.8)
    }
}
