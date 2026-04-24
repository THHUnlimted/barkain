import SwiftUI

// MARK: - ConfirmationPromptView (demo-prep-1 Item 3)
//
// Modal sheet the user sees when a tapped search result returns from
// the backend as 409 RESOLUTION_NEEDS_CONFIRMATION. Shows the primary
// pick the user tapped plus up to two alternatives from the current
// in-memory search results. Three actions: confirm, pick an
// alternative as the new primary then confirm, or reject entirely.
//
// The copy intentionally avoids mentioning "confidence scores" — the
// user doesn't need to know the machinery, just that we want to make
// sure before committing. Threshold + measured confidence are exposed
// in DEBUG builds only via an overlay badge for bench tuning.

struct ConfirmationPromptView: View {

    // MARK: - Properties

    let pending: SearchViewModel.PendingConfirmation
    let onConfirm: (ProductSearchResult) -> Void
    let onReject: () -> Void
    let onDismiss: () -> Void

    @State private var selection: ProductSearchResult

    init(
        pending: SearchViewModel.PendingConfirmation,
        onConfirm: @escaping (ProductSearchResult) -> Void,
        onReject: @escaping () -> Void,
        onDismiss: @escaping () -> Void
    ) {
        self.pending = pending
        self.onConfirm = onConfirm
        self.onReject = onReject
        self.onDismiss = onDismiss
        self._selection = State(initialValue: pending.primary)
    }

    // MARK: - Body

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: Spacing.lg) {
                    headerCopy
                    primaryCandidateCard
                    if !pending.alternatives.isEmpty {
                        alternativesSection
                    }
                    actionButtons
                }
                .padding(Spacing.lg)
            }
            .background(Color.barkainSurface)
            .navigationTitle("Is this right?")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { onDismiss() }
                        .accessibilityIdentifier("confirmationCancelButton")
                }
            }
        }
        .accessibilityIdentifier("confirmationPromptView")
    }

    // MARK: - Subviews

    private var headerCopy: some View {
        VStack(spacing: Spacing.xs) {
            Image(systemName: "questionmark.circle.fill")
                .font(.system(size: 44, weight: .semibold))
                .foregroundStyle(Color.barkainPrimary)

            Text("Is this the product you mean?")
                .font(.barkainTitle2)
                .fontWeight(.semibold)
                .foregroundStyle(Color.barkainOnSurface)
                .multilineTextAlignment(.center)
                .accessibilityIdentifier("confirmationHeadline")

            Text("We want to make sure before pulling prices — tap the right one, or \"Not quite\" to search again.")
                .font(.barkainBody)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, Spacing.md)
        }
    }

    private var primaryCandidateCard: some View {
        candidateRow(for: pending.primary, isPrimary: true)
            .accessibilityIdentifier("confirmationPrimaryCandidate")
    }

    private var alternativesSection: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text("Or did you mean one of these?")
                .font(.barkainCaption)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
                .textCase(.uppercase)

            ForEach(pending.alternatives) { alt in
                candidateRow(for: alt, isPrimary: false)
                    .accessibilityIdentifier("confirmationAlternative_\(alt.deviceName)")
            }
        }
    }

    private func candidateRow(for candidate: ProductSearchResult, isPrimary: Bool) -> some View {
        let isSelected = candidate.deviceName == selection.deviceName
        return Button {
            selection = candidate
        } label: {
            HStack(alignment: .top, spacing: Spacing.md) {
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(candidate.deviceName)
                        .font(.barkainHeadline)
                        .foregroundStyle(Color.barkainOnSurface)
                        .multilineTextAlignment(.leading)
                    if let brand = candidate.brand, !brand.isEmpty {
                        Text(brand)
                            .font(.barkainBody)
                            .foregroundStyle(Color.barkainOnSurfaceVariant)
                    }
                }
                Spacer(minLength: 0)
                if isSelected {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.title3)
                        .foregroundStyle(Color.barkainPrimary)
                }
            }
            .padding(Spacing.md)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                    .fill(isPrimary || isSelected
                          ? Color.barkainPrimaryFixed.opacity(0.35)
                          : Color.barkainSurfaceContainerLow)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                    .stroke(isSelected ? Color.barkainPrimary : Color.clear, lineWidth: 2)
            )
        }
        .buttonStyle(.plain)
    }

    private var actionButtons: some View {
        VStack(spacing: Spacing.sm) {
            Button {
                onConfirm(selection)
            } label: {
                Text("Yes, that's it")
                    .font(.barkainHeadline)
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Spacing.md)
                    .background(
                        Capsule(style: .continuous)
                            .fill(Color.barkainPrimaryGradient)
                    )
            }
            .buttonStyle(.plain)
            .barkainShadowGlow()
            .accessibilityIdentifier("confirmationConfirmButton")

            Button {
                onReject()
            } label: {
                Text("Not quite — let me search again")
                    .font(.barkainBody)
                    .foregroundStyle(Color.barkainPrimary)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Spacing.md)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("confirmationRejectButton")
        }
    }
}

// MARK: - Preview

#Preview("Three candidates") {
    let primary = ProductSearchResult(
        deviceName: "Sony WH-1000XM5",
        model: nil,
        brand: "Sony",
        category: nil,
        confidence: 0.55,
        primaryUpc: nil,
        source: .gemini,
        productId: nil,
        imageUrl: nil
    )
    let alt1 = ProductSearchResult(
        deviceName: "Sony WH-1000XM4",
        model: nil,
        brand: "Sony",
        category: nil,
        confidence: 0.44,
        primaryUpc: nil,
        source: .gemini,
        productId: nil,
        imageUrl: nil
    )
    let alt2 = ProductSearchResult(
        deviceName: "Sony MDR-XB550AP",
        model: nil,
        brand: "Sony",
        category: nil,
        confidence: 0.39,
        primaryUpc: nil,
        source: .gemini,
        productId: nil,
        imageUrl: nil
    )
    return ConfirmationPromptView(
        pending: .init(primary: primary, alternatives: [alt1, alt2], threshold: 0.70),
        onConfirm: { _ in },
        onReject: {},
        onDismiss: {}
    )
}
