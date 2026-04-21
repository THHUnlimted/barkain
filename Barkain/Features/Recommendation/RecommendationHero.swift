import SwiftUI

// MARK: - RecommendationHero (Step 3e)
//
// The capstone card at the top of PriceComparisonView. Renders ONLY after
// the SSE stream closes AND identity + cards both settle — the parent
// view uses `if let rec = viewModel.recommendation` to gate visibility,
// so this view never has a loading state.

struct RecommendationHero: View {

    // MARK: - Properties

    let recommendation: Recommendation

    /// Fired on the primary CTA tap. Parent wires this to the existing
    /// affiliate-click round-trip so the hero and retailer rows share
    /// the same in-app browser path.
    var onOpen: (StackedPath) -> Void = { _ in }

    /// Fired when the brand-direct callout is tapped (if present).
    var onOpenCallout: (BrandDirectCallout) -> Void = { _ in }

    /// Fired when an alternative pill is tapped. Parent scrolls the list
    /// to the tapped retailer's row rather than opening a second sheet.
    var onSelectAlternative: (StackedPath) -> Void = { _ in }

    // MARK: - Body

    var body: some View {
        VStack(spacing: Spacing.md) {
            heroCard
            if let callout = recommendation.brandDirectCallout {
                calloutPill(callout)
            }
            if !recommendation.alternatives.isEmpty {
                alternativesRail
            }
        }
        .transition(.opacity.combined(with: .scale(scale: 0.96)))
        .animation(.spring(duration: 0.35), value: recommendation)
        .accessibilityIdentifier("recommendationHero")
    }

    // MARK: - Hero card

    private var heroCard: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            eyebrow
            Text(recommendation.headline)
                .font(.barkainTitle2)
                .fontWeight(.semibold)
                .foregroundStyle(Color.barkainOnSurface)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("recommendationHeadline")

            priceBlock

            if !breakdownLayers.isEmpty {
                breakdownPills
            }

            Text(recommendation.why)
                .font(.barkainCaption)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
                .fixedSize(horizontal: false, vertical: true)

            actionButton
        }
        .padding(Spacing.lg)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadiusLarge, style: .continuous)
                .fill(Color.barkainPrimaryContainer.opacity(0.55))
        )
        .overlay(
            RoundedRectangle(cornerRadius: Spacing.cornerRadiusLarge, style: .continuous)
                .stroke(Color.barkainPrimary.opacity(0.25), lineWidth: 1)
        )
        .shadow(color: Color.black.opacity(0.08), radius: 18, x: 0, y: 8)
    }

    // MARK: - Eyebrow

    private var eyebrow: some View {
        HStack(spacing: Spacing.xxs) {
            Image(systemName: "pawprint.fill")
                .font(.system(size: 12, weight: .semibold))
            Text("BEST BARKAIN")
                .font(.barkainLabel)
                .tracking(0.8)
        }
        .foregroundStyle(Color.barkainPrimary)
    }

    // MARK: - Price block

    private var priceBlock: some View {
        HStack(alignment: .lastTextBaseline, spacing: Spacing.sm) {
            Text(formatMoney(recommendation.winner.finalPrice))
                .font(.system(size: 44, weight: .bold, design: .rounded))
                .foregroundStyle(Color.barkainOnSurface)
            if recommendation.winner.base_price_strikethroughEligible {
                Text(formatMoney(recommendation.winner.basePrice))
                    .font(.barkainBody)
                    .strikethrough()
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
            }
            Spacer(minLength: 0)
            if recommendation.hasStackableValue, recommendation.winner.totalSavings > 0 {
                savingsPill
            }
        }
    }

    private var savingsPill: some View {
        Text("Save \(formatMoney(recommendation.winner.totalSavings))")
            .font(.barkainLabel)
            .fontWeight(.semibold)
            .foregroundStyle(Color.barkainOnSurface)
            .padding(.horizontal, Spacing.sm)
            .padding(.vertical, 4)
            .background(Color.barkainPrimary.opacity(0.22))
            .clipShape(Capsule())
    }

    // MARK: - Breakdown pills

    private var breakdownLayers: [BreakdownLayer] {
        var out: [BreakdownLayer] = []
        let w = recommendation.winner
        if w.identitySavings > 0, let src = w.identitySource {
            out.append(.init(id: "identity", label: src, amount: w.identitySavings, icon: "checkmark.seal.fill"))
        }
        if w.portalSavings > 0, let src = w.portalSource {
            out.append(.init(id: "portal", label: src.capitalized, amount: w.portalSavings, icon: "bag.fill"))
        }
        if w.cardSavings > 0, let src = w.cardSource {
            out.append(.init(id: "card", label: src, amount: w.cardSavings, icon: "creditcard.fill"))
        }
        return out
    }

    private var breakdownPills: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            ForEach(breakdownLayers) { layer in
                HStack(spacing: Spacing.xs) {
                    Image(systemName: layer.icon)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(Color.barkainPrimary)
                    Text(layer.label)
                        .font(.barkainCaption)
                        .foregroundStyle(Color.barkainOnSurface)
                    Spacer(minLength: Spacing.xs)
                    Text("+\(formatMoney(layer.amount))")
                        .font(.barkainCaption)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.barkainPrimary)
                }
                .padding(.horizontal, Spacing.sm)
                .padding(.vertical, 6)
                .background(Color.barkainSurface.opacity(0.75))
                .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous))
            }
        }
    }

    // MARK: - Action button

    private var actionButton: some View {
        Button {
            onOpen(recommendation.winner)
        } label: {
            HStack {
                Text("Open \(recommendation.winner.retailerName)")
                    .font(.barkainHeadline)
                    .fontWeight(.semibold)
                Spacer()
                Image(systemName: "arrow.up.right")
            }
            .foregroundStyle(.white)
            .padding(.vertical, Spacing.sm)
            .padding(.horizontal, Spacing.md)
            .frame(maxWidth: .infinity)
            .background(Color.barkainPrimaryGradient)
            .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadiusLarge, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("recommendationActionButton")
    }

    // MARK: - Brand-direct callout

    private func calloutPill(_ callout: BrandDirectCallout) -> some View {
        Button {
            onOpenCallout(callout)
        } label: {
            HStack(spacing: Spacing.sm) {
                Image(systemName: "gift.fill")
                    .foregroundStyle(Color.barkainPrimary)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Also: \(Int(callout.discountValue))% off at \(callout.retailerName)")
                        .font(.barkainBody)
                        .foregroundStyle(Color.barkainOnSurface)
                    Text("with your \(callout.programName)")
                        .font(.barkainCaption)
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right")
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
            }
            .padding(Spacing.md)
            .background(Color.barkainPrimaryFixed.opacity(0.3))
            .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("brandDirectCallout")
    }

    // MARK: - Alternatives rail

    private var alternativesRail: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Spacing.sm) {
                ForEach(recommendation.alternatives) { alt in
                    Button {
                        onSelectAlternative(alt)
                    } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(alt.retailerName)
                                .font(.barkainLabel)
                                .fontWeight(.semibold)
                                .foregroundStyle(Color.barkainOnSurface)
                            Text(formatMoney(alt.finalPrice))
                                .font(.barkainCaption)
                                .foregroundStyle(Color.barkainOnSurfaceVariant)
                        }
                        .padding(.horizontal, Spacing.sm)
                        .padding(.vertical, Spacing.xs)
                        .background(Color.barkainSurfaceContainerLow)
                        .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous))
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("recommendationAlternativePill_\(alt.retailerId)")
                }
            }
            .padding(.horizontal, 2)
        }
    }

    // MARK: - Helpers

    private func formatMoney(_ value: Double) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        formatter.maximumFractionDigits = 2
        return formatter.string(from: NSNumber(value: value)) ?? "$\(value)"
    }

    // MARK: - Breakdown model

    private struct BreakdownLayer: Identifiable, Hashable {
        let id: String
        let label: String
        let amount: Double
        let icon: String
    }
}

// MARK: - StackedPath helpers

private extension StackedPath {
    /// Only show the strikethrough base price when there's an actual
    /// identity discount driving `final_price` below `base_price`.
    /// Card + portal rebates don't change the sticker — showing a
    /// strikethrough for them would be misleading.
    var base_price_strikethroughEligible: Bool {
        identitySavings > 0 && basePrice > finalPrice
    }
}
