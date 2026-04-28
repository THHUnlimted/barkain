import SwiftUI

// MARK: - MiscRetailerCard (Step 3n)
//
// 10th data-source slot — surfaces up to 3 retailers Barkain doesn't
// directly scrape (Chewy, Petco, Petflow, Tractor Supply, niche pet
// boutiques). Self-contained: holds its own fetch state and consults
// `FeatureGateService.isMiscRetailerEnabled` so an app-wide flag flip
// (canary 5 % → 50 % → 100 %) can dark-launch the section without
// touching the parent view.
//
// Hidden when:
//   - Feature flag OFF, OR
//   - Fetch failed (silently — this slot is supplementary, not load-bearing), OR
//   - Backend returned zero rows (post-filter / disabled adapter).
//
// Tap-through opens the row's `link` (a Google Shopping product page,
// NOT a direct merchant URL) in `SFSafariViewController` via the same
// `IdentifiableURL` binding the rest of `PriceComparisonView` uses for
// retailer rows. No `/affiliate/click` interception in v1 — the link
// is already a Google-Shopping URL; affiliate routing is a separate UX
// step the prompt explicitly defers.

struct MiscRetailerCard: View {

    // MARK: - Properties

    let productId: UUID
    /// Optional override sent to the backend as `?query=`. When the user
    /// arrived through the generic-search-tap flow we pass the bare
    /// search string so the misc-retailer cache scopes to the same
    /// `:q:<sha1>` bucket as the price stream.
    var queryOverride: String?
    @Binding var browserURL: IdentifiableURL?

    @Environment(FeatureGateService.self) private var featureGate
    @Environment(\.apiClient) private var apiClient

    @State private var rows: [MiscMerchantRow] = []
    @State private var didLoad: Bool = false

    // MARK: - Body

    var body: some View {
        // 3n: VStack containing an always-present Color.clear anchor + the
        // optional rendered card. SwiftUI elides `.task(id:)` when its host
        // is a conditional that resolves to EmptyView (a Group whose only
        // child is a hidden `if` trips this — verified live in sim against
        // a Royal-Canin pet query, where the card body printed but `.task`
        // never fired). A 0×0 Color.clear is a real concrete view, so the
        // task lifecycle reliably fires on first appear regardless of
        // whether `rows` is empty.
        VStack(spacing: 0) {
            Color.clear
                .frame(width: 0, height: 0)
                .accessibilityHidden(true)
                .task(id: productId) {
                    guard featureGate.isMiscRetailerEnabled else { return }
                    await loadIfNeeded()
                }
            if featureGate.isMiscRetailerEnabled, !rows.isEmpty {
                content
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        if !rows.isEmpty {
            VStack(alignment: .leading, spacing: Spacing.sm) {
                header
                ForEach(rows.prefix(3)) { row in
                    rowButton(row)
                    if row.id != rows.prefix(3).last?.id {
                        Divider()
                            .background(Color.barkainOutlineVariant.opacity(0.4))
                    }
                }
            }
            .padding(Spacing.md)
            .background(Color.barkainSurface)
            .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                    .stroke(Color.barkainOutlineVariant.opacity(0.6), lineWidth: 1)
            )
            .accessibilityIdentifier("miscRetailerCard")
        }
    }

    private var header: some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: "storefront")
                .foregroundStyle(Color.barkainPrimary)
            Text("More merchants")
                .font(.barkainHeadline)
                .foregroundStyle(Color.barkainOnSurface)
            Spacer(minLength: 0)
        }
    }

    @ViewBuilder
    private func rowButton(_ row: MiscMerchantRow) -> some View {
        Button {
            browserURL = IdentifiableURL(url: row.link)
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: Spacing.sm) {
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(row.source)
                        .font(.barkainBody)
                        .foregroundStyle(Color.barkainOnSurface)
                        .lineLimit(1)
                    Text(row.title)
                        .font(.barkainCaption)
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                        .lineLimit(2)
                }
                Spacer(minLength: Spacing.xs)
                Text(row.price)
                    .font(.barkainHeadline)
                    .foregroundStyle(Color.barkainOnSurface)
                Image(systemName: "arrow.up.right")
                    .font(.barkainCaption)
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("miscRetailerRow-\(row.id)")
    }

    // MARK: - Loading

    private func loadIfNeeded() async {
        // Single fetch per (productId, queryOverride). Re-runs on
        // `task(id:)` change when the parent re-mounts the card with a
        // different product.
        guard !didLoad else { return }
        didLoad = true
        do {
            let fetched = try await apiClient.getMiscRetailers(
                productId: productId,
                query: queryOverride
            )
            await MainActor.run { self.rows = fetched }
        } catch {
            // Slot is supplementary — failures stay invisible. Logged
            // at the APIClient layer; no user-facing error UI.
        }
    }
}
