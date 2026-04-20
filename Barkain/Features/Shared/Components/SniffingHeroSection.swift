import SwiftUI

// MARK: - SniffingHeroSection
//
// The "dog working" hero: big glowing paw, status line, rotating pun, and
// a small chip reassuring the user that discounts and cards are loading
// too. Used inline inside PriceComparisonView while SSE is streaming, and
// standalone (wrapped in `PriceLoadingHero`) during the pre-first-event
// window.
//
// Kept separate from the surrounding view chrome so it composes cleanly
// in both contexts and owns its own pun-rotation state.

struct SniffingHeroSection: View {

    // MARK: - Properties

    let productName: String

    // MARK: - State

    @State private var punIndex: Int = 0

    // MARK: - Puns

    private static let puns: [String] = [
        "Nose to the ground…",
        "Digging up a bargain…",
        "Marking the best territory…",
        "Fetching every price…",
        "Good dog, finding deals…"
    ]

    // MARK: - Body

    var body: some View {
        VStack(spacing: Spacing.md) {
            GlowingPawLogo(size: 160)

            VStack(spacing: Spacing.xs) {
                Text("Sniffing out deals for \(productName)…")
                    .font(.barkainHeadline)
                    .foregroundStyle(Color.barkainOnSurface)
                    .multilineTextAlignment(.center)

                Text(Self.puns[punIndex])
                    .font(.barkainBody)
                    .italic()
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
                    .multilineTextAlignment(.center)
                    .id(punIndex)
                    .transition(.opacity)
            }

            discountsChip
                .padding(.top, Spacing.xs)
        }
        .frame(maxWidth: .infinity)
        .task { await cyclePuns() }
    }

    // MARK: - Discounts chip

    private var discountsChip: some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: "ticket.fill")
                .font(.caption)
                .foregroundStyle(Color.barkainPrimary)
            Text("Checking your discounts & cards too")
                .font(.barkainCaption)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.xs)
        .background(
            Capsule(style: .continuous)
                .fill(Color.barkainPrimaryFixed.opacity(0.35))
        )
    }

    // MARK: - Pun cycling

    private func cyclePuns() async {
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(2.5))
            guard !Task.isCancelled else { return }
            withAnimation(.easeInOut(duration: 0.45)) {
                punIndex = (punIndex + 1) % Self.puns.count
            }
        }
    }
}
