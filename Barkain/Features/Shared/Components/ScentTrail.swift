import SwiftUI

// MARK: - ScentTrail
//
// The `.scent-trail` motif from the web style guide: a horizontal dotted
// line that evokes a scent track. Used as a divider after the "Scent
// Tracked" eyebrow tag and between alert timeline entries.
//
// Rendered as a row of `Circle` fills so it survives scaling cleanly.

struct ScentTrail: View {

    // MARK: - Properties

    var color: Color = .barkainOutlineVariant
    var dotSize: CGFloat = 2.5
    var spacing: CGFloat = 5.5

    // MARK: - Body

    var body: some View {
        GeometryReader { geo in
            let dotCount = max(1, Int(geo.size.width / (dotSize + spacing)))
            HStack(spacing: spacing) {
                ForEach(0..<dotCount, id: \.self) { _ in
                    Circle()
                        .fill(color)
                        .frame(width: dotSize, height: dotSize)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(height: dotSize)
    }
}

// MARK: - Best Barkain Badge
//
// The floating pill that marks the cheapest retailer row. Extracted from
// `PriceComparisonView.bestBarkainBadge` so other screens (e.g. Savings
// alerts) can reuse it without copy-pasting the geometry.

struct BestBarkainBadge: View {

    var body: some View {
        HStack(spacing: Spacing.xxs) {
            Image(systemName: "pawprint.fill")
                .font(.system(size: 10, weight: .bold))
            Text("BEST BARKAIN")
                .font(.barkainLabel)
                .tracking(1.2)
        }
        .foregroundStyle(Color.barkainOnPrimaryContainer)
        .padding(.horizontal, Spacing.sm)
        .padding(.vertical, 6)
        .background(
            Capsule(style: .continuous)
                .fill(Color.barkainPrimaryContainer)
        )
        .overlay(
            Capsule(style: .continuous)
                .stroke(Color.white.opacity(0.6), lineWidth: 1)
        )
        .barkainShadowSoft()
    }
}

// MARK: - Previews

#Preview("Scent trail") {
    VStack(spacing: Spacing.md) {
        ScentTrail()
        ScentTrail(color: .barkainPrimary, dotSize: 4, spacing: 8)
    }
    .padding()
    .background(Color.barkainSurface)
}

#Preview("Best Barkain badge") {
    BestBarkainBadge()
        .padding()
        .background(Color.barkainSurface)
}
