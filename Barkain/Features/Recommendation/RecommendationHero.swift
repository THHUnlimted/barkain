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

    /// provisional-resolve: when true the hero renders an "approximate
    /// match" banner above the card and downgrades the BEST BARKAIN
    /// eyebrow to "APPROXIMATE MATCH" so the user knows the underlying
    /// Product was persisted as a best-effort row (no canonical UPC).
    /// Defaults to false so existing call sites keep their behavior.
    var isProvisional: Bool = false

    /// User's original search string, surfaced inside the provisional
    /// banner copy. Ignored when `isProvisional` is false.
    var searchQuery: String? = nil

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
            if isProvisional {
                provisionalBanner
            }
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

    // MARK: - Provisional banner (provisional-resolve)
    //
    // Soft, non-blocking banner above the hero card that tells the user
    // the underlying Product is a best-effort match — Gemini + UPCitemdb
    // couldn't pin a canonical UPC, so the price stream ran on the user's
    // original search string with the relevance gates as the safety net.
    // The banner sets expectation; the eyebrow downgrade ("APPROXIMATE
    // MATCH") + hidden BEST BARKAIN gold saturation reinforce it without
    // breaking the spending flow — the CTA still works.

    private var provisionalBanner: some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Image(systemName: "info.circle.fill")
                .foregroundStyle(Color.barkainPrimary)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(provisionalBannerHeadline)
                    .font(.barkainBody)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.barkainOnSurface)
                Text("Exact match unavailable — verify before tapping Open.")
                    .font(.barkainCaption)
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .padding(Spacing.md)
        .background(Color.barkainPrimaryFixed.opacity(0.18))
        .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous))
        .accessibilityIdentifier("provisionalMatchBanner")
        .accessibilityElement(children: .combine)
    }

    private var provisionalBannerHeadline: String {
        if let q = searchQuery, !q.isEmpty {
            return "Best results for \"\(q)\""
        }
        return "Approximate match"
    }

    // MARK: - Hero card
    //
    // savings-math-prominence Item 1: visual priority inverted so the
    // first thing the eye hits is the dollar amount SAVED, not the
    // dollar amount spent. Three centered lines:
    //   1. "Save $47" — barkainHero (48pt), warm gold — the memorable moment
    //   2. "$152.99 at Walmart" — 24pt regular — the effective price
    //   3. recommendation.why — 14pt secondary — the explanatory caption
    // Eyebrow + breakdown pills + CTA wrap them. When totalSavings is 0
    // the savings line hides entirely (no "Save $0") and line 2 becomes
    // the visual headline; pre-#63 the parent gates on whether a
    // recommendation exists at all, so this view never has to render
    // an empty state.

    private var heroCard: some View {
        VStack(alignment: .center, spacing: Spacing.md) {
            eyebrow
            savingsLine
            effectivePriceLine
            whyLine

            if receipt.hasAnyDiscount {
                StackingReceiptView(receipt: receipt)
            }

            actionButton
        }
        .padding(Spacing.lg)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadiusLarge, style: .continuous)
                .fill(Color.barkainHeroSurface)
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
            Image(systemName: isProvisional ? "magnifyingglass" : "pawprint.fill")
                .font(.system(size: 12, weight: .semibold))
            Text(isProvisional ? "APPROXIMATE MATCH" : "BEST BARKAIN")
                .font(.barkainLabel)
                .tracking(0.8)
        }
        .foregroundStyle(
            isProvisional ? Color.barkainOnSurfaceVariant : Color.barkainPrimary
        )
    }

    // MARK: - Hero lines (savings-math-prominence Item 1)

    /// Line 1 — the savings number. Hidden entirely when totalSavings ≤ 0
    /// (avoids the "Save $0" anti-pattern flagged in the pack).
    @ViewBuilder
    private var savingsLine: some View {
        if recommendation.winner.totalSavings > 0 {
            Text("Save \(formatMoney(recommendation.winner.totalSavings))")
                .font(.barkainHero)
                .barkainDisplayTracking()
                .foregroundStyle(Color.barkainPrimary)
                .multilineTextAlignment(.center)
                .accessibilityIdentifier("recommendationSavingsHeadline")
                .accessibilityLabel(
                    "You save \(formatMoney(recommendation.winner.totalSavings))"
                )
        }
    }

    /// Line 2 — the effective price + retailer. 24pt regular per pack.
    /// Uses `effectiveCost` not `finalPrice` so card + portal rebates
    /// actually pull this number down (matches the receipt's "Your price"
    /// row in Item 2).
    private var effectivePriceLine: some View {
        Text("\(formatMoney(recommendation.winner.effectiveCost)) at \(recommendation.winner.retailerName)")
            .font(.system(size: 24, weight: .regular, design: .rounded))
            .foregroundStyle(Color.barkainOnSurface)
            .multilineTextAlignment(.center)
            .accessibilityIdentifier("recommendationEffectivePrice")
    }

    /// Line 3 — the explanatory "why" copy. 14pt secondary.
    private var whyLine: some View {
        Text(recommendation.why)
            .font(.system(size: 14, weight: .regular))
            .foregroundStyle(Color.barkainOnSurfaceVariant)
            .multilineTextAlignment(.center)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityIdentifier("recommendationWhy")
    }

    // MARK: - Receipt (savings-math-prominence Item 2)

    private var receipt: StackingReceipt {
        StackingReceipt(stackedPath: recommendation.winner)
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
        Money.format(value)
    }
}

