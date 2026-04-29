import SwiftUI

// MARK: - UnresolvedProductView (demo-prep-1 Item 2)
//
// Graceful "couldn't find this one" view. Replaces the generic
// exclamation-triangle error card for the specific case where
// `/resolve` or `/resolve-from-search` returns 404. Shown both from
// ScannerView (barcode path) and SearchView (text tap path); the parent
// view supplies the context-appropriate CTA callbacks.
//
// Never shows raw UPC or error codes to the user — those stay in logs
// (`os_log` at `com.barkain.app/Resolve`) for diagnostics. The icon is
// intentionally a magnifying glass rather than a red exclamation mark —
// this is a "we searched and came back empty" state, not an error state.

struct UnresolvedProductView: View {

    // MARK: - Properties

    /// Shown in the iconographic well as a subtle reminder of what the
    /// user tried to resolve. Nil when the caller doesn't have a user-
    /// readable label (e.g. bare UPC in Scanner).
    var searchHint: String?

    /// cat-rel-1-L2-ux: optional Gemini-stated reason surfaced under the
    /// generic copy. Set by `SearchViewModel.unresolvedReason` when the
    /// `/resolve-from-search` 404 envelope carried `details.reasoning`
    /// (multi-variant SKUs, dealer-only stock, discontinued lines).
    /// Nil for the plain "we just don't have it" case — the original
    /// generic copy is still shown alone.
    var reasoning: String?

    /// Primary CTA — typically "Scan another item" from Search or
    /// "Try again" from Scanner.
    let primaryActionTitle: String
    let primaryAction: () -> Void

    /// Secondary CTA — deep-links to the other tab (Search in Scanner
    /// context, Scanner in Search context).
    let secondaryActionTitle: String
    let secondaryAction: () -> Void

    // MARK: - Body

    var body: some View {
        ScrollView {
            VStack(spacing: Spacing.lg) {
                iconWell
                    .padding(.top, Spacing.xxl)

                VStack(spacing: Spacing.xs) {
                    Text("Couldn't find this one")
                        .font(.barkainTitle)
                        .foregroundStyle(Color.barkainOnSurface)
                        .multilineTextAlignment(.center)
                        .accessibilityIdentifier("unresolvedProductTitle")

                    Text(friendlyCausesCopy)
                        .font(.barkainBody)
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.horizontal, Spacing.md)

                    // cat-rel-1-L2-ux: when the backend handed up a
                    // Gemini-authored reason, show it as a subtle
                    // explanation below the generic copy. Not styled as
                    // an error — just italic to mark it as a quoted
                    // explanation rather than app-authored copy.
                    if let reasoning, !reasoning.isEmpty {
                        Text(reasoning)
                            .font(.barkainCaption)
                            .italic()
                            .foregroundStyle(Color.barkainOnSurfaceVariant.opacity(0.85))
                            .multilineTextAlignment(.center)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(.horizontal, Spacing.md)
                            .padding(.top, Spacing.xs)
                            .accessibilityIdentifier("unresolvedReasoning")
                    }
                }

                VStack(spacing: Spacing.sm) {
                    primaryButton
                    secondaryButton
                }
                .padding(.top, Spacing.md)
            }
            .padding(.horizontal, Spacing.lg)
            .padding(.bottom, Spacing.xxl)
            .frame(maxWidth: .infinity)
        }
        .accessibilityIdentifier("unresolvedProductView")
    }

    // MARK: - Copy

    private var friendlyCausesCopy: String {
        "This happens with some food items, imports, and products Barkain hasn't indexed yet. Try a different approach and we'll sniff something out."
    }

    // MARK: - Subviews

    private var iconWell: some View {
        ZStack {
            Circle()
                .fill(Color.barkainPrimaryFixed.opacity(0.45))
                .frame(width: 120, height: 120)
            Circle()
                .fill(Color.barkainPrimaryFixed.opacity(0.25))
                .frame(width: 160, height: 160)
            Image(systemName: "magnifyingglass")
                .font(.system(size: 52, weight: .semibold))
                .foregroundStyle(Color.barkainPrimary)
        }
        .frame(width: 160, height: 160)
    }

    private var primaryButton: some View {
        Button(action: primaryAction) {
            Text(primaryActionTitle)
                .font(.barkainHeadline)
                .foregroundStyle(.white)
                .padding(.horizontal, Spacing.xl)
                .padding(.vertical, Spacing.md)
                .frame(maxWidth: .infinity)
                .background(
                    Capsule(style: .continuous)
                        .fill(Color.barkainPrimaryGradient)
                )
        }
        .buttonStyle(.plain)
        .barkainShadowGlow()
        .accessibilityIdentifier("unresolvedPrimaryCTA")
    }

    private var secondaryButton: some View {
        Button(action: secondaryAction) {
            Text(secondaryActionTitle)
                .font(.barkainHeadline)
                .foregroundStyle(Color.barkainPrimary)
                .padding(.horizontal, Spacing.xl)
                .padding(.vertical, Spacing.md)
                .frame(maxWidth: .infinity)
                .overlay(
                    Capsule(style: .continuous)
                        .stroke(Color.barkainPrimary, lineWidth: 1.5)
                )
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("unresolvedSecondaryCTA")
    }
}

// MARK: - Preview

#Preview("Default") {
    UnresolvedProductView(
        primaryActionTitle: "Scan another item",
        primaryAction: {},
        secondaryActionTitle: "Search by name instead",
        secondaryAction: {}
    )
    .background(Color.barkainSurface)
}

#Preview("Long-name context") {
    UnresolvedProductView(
        searchHint: "Sony WH-1000XM5 Wireless Noise-Cancelling Over-Ear Headphones",
        primaryActionTitle: "Try a different search",
        primaryAction: {},
        secondaryActionTitle: "Scan the barcode instead",
        secondaryAction: {}
    )
    .background(Color.barkainSurface)
}

#Preview("With Gemini reasoning (cat-rel-1-L2-ux)") {
    UnresolvedProductView(
        searchHint: "Husqvarna 460 Rancher chainsaw",
        reasoning: "Multiple SKU variants exist for this model — barcode scanning will pin the right one.",
        primaryActionTitle: "Try a different search",
        primaryAction: {},
        secondaryActionTitle: "Scan the barcode instead",
        secondaryAction: {}
    )
    .background(Color.barkainSurface)
}
