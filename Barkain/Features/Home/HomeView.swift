import SwiftUI

// MARK: - HomeView
//
// Landing surface for the app. Greets the user, gives them two big
// quick-action CTAs (Scan / Search), and shows a horizontal rail of the
// products they've resolved recently. Everything here is backed by real
// data — the rail reads from `RecentlyScannedStore`, and the identity
// CTA surfaces only if the user hasn't finished onboarding yet.
//
// No mock products. Empty states are honest — if the user hasn't
// scanned anything yet we say so and point them at the tools.

struct HomeView: View {

    // MARK: - Actions

    /// Called when the user taps one of the big hero quick-action tiles.
    /// Parent owns the `TabView` selection binding.
    let onSelectScan: () -> Void
    let onSelectSearch: () -> Void

    /// Called when the user taps a "Recently scanned" thumbnail. Parent
    /// (ContentView) switches to the Scan tab and reads the selected
    /// product via the shared `RecentlyScannedStore`. Optional so the
    /// Home tab stays composable for future contexts where tapping a
    /// thumb should do something different.
    var onSelectRecent: ((RecentlyScannedProduct) -> Void)? = nil

    // MARK: - Environment

    @Environment(\.recentlyScanned) private var recentlyScanned

    @AppStorage("hasCompletedIdentityOnboarding")
    private var hasCompletedOnboarding: Bool = false

    // MARK: - Body

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                heroSection
                quickActionsRow

                recentlyScannedSection

                if !hasCompletedOnboarding {
                    identityNudge
                }
            }
            .padding(.horizontal, Spacing.lg)
            .padding(.top, Spacing.sm)
            .padding(.bottom, Spacing.xxl)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.barkainSurface.ignoresSafeArea())
        .navigationTitle("Barkain")
    }

    // MARK: - Hero

    private var heroSection: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack(spacing: Spacing.xs) {
                Image(systemName: "pawprint.fill")
                    .foregroundStyle(Color.barkainPrimary)
                Text("Your loyal deal-finder")
                    .barkainEyebrow()
            }

            VStack(alignment: .leading, spacing: -6) {
                Text("Sniff Out")
                    .font(.system(size: 44, weight: .black, design: .rounded))
                    .foregroundStyle(Color.barkainOnSurface)
                Text("a Deal")
                    .font(.system(size: 44, weight: .black, design: .rounded).italic())
                    .foregroundStyle(Color.barkainPrimary)
            }

            Text("Scan a barcode or search by name — Barkain checks every retailer so you don't have to.")
                .font(.barkainBody)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Spacing.lg)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadiusLarge, style: .continuous)
                .fill(Color.barkainSurfaceContainerLow)
        )
        .overlay(alignment: .topTrailing) {
            Image(systemName: "pawprint.fill")
                .font(.system(size: 120))
                .foregroundStyle(Color.barkainPrimary.opacity(0.08))
                .rotationEffect(.degrees(15))
                .offset(x: 20, y: -20)
                .clipped()
        }
        .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadiusLarge, style: .continuous))
        .barkainShadowSoft()
    }

    // MARK: - Quick actions

    private var quickActionsRow: some View {
        HStack(spacing: Spacing.sm) {
            quickActionButton(
                title: "Scan",
                subtitle: "Point at a barcode",
                icon: "barcode.viewfinder",
                style: .primary,
                action: onSelectScan
            )
            .accessibilityIdentifier("homeScanButton")

            quickActionButton(
                title: "Search",
                subtitle: "Find by name",
                icon: "magnifyingglass",
                style: .secondary,
                action: onSelectSearch
            )
            .accessibilityIdentifier("homeSearchButton")
        }
    }

    private enum QuickActionStyle { case primary, secondary }

    private func quickActionButton(
        title: String,
        subtitle: String,
        icon: String,
        style: QuickActionStyle,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: Spacing.sm) {
                Image(systemName: icon)
                    .font(.title)
                    .foregroundStyle(style == .primary ? .white : Color.barkainPrimary)
                Spacer(minLength: Spacing.sm)
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(title)
                        .font(.barkainTitle2)
                        .foregroundStyle(style == .primary ? .white : Color.barkainOnSurface)
                    Text(subtitle)
                        .font(.barkainCaption)
                        .foregroundStyle(
                            style == .primary
                                ? .white.opacity(0.85)
                                : Color.barkainOnSurfaceVariant
                        )
                }
            }
            .frame(maxWidth: .infinity, minHeight: 120, alignment: .topLeading)
            .padding(Spacing.lg)
            .background(
                RoundedRectangle(cornerRadius: Spacing.cornerRadiusLarge, style: .continuous)
                    .fill(
                        style == .primary
                            ? AnyShapeStyle(Color.barkainPrimaryGradient)
                            : AnyShapeStyle(Color.barkainSurfaceContainerLowest)
                    )
            )
        }
        .buttonStyle(.plain)
        .modifier(QuickActionShadowModifier(style: style))
    }

    private struct QuickActionShadowModifier: ViewModifier {
        let style: QuickActionStyle

        func body(content: Content) -> some View {
            switch style {
            case .primary:
                content.barkainShadowGlow()
            case .secondary:
                content.barkainShadowSoft()
            }
        }
    }

    // MARK: - Recently scanned

    @ViewBuilder
    private var recentlyScannedSection: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack {
                Text("Recently sniffed")
                    .barkainEyebrow()
                Spacer()
                if !recentlyScanned.items.isEmpty {
                    Text("\(recentlyScanned.items.count)")
                        .font(.barkainCaption.weight(.bold))
                        .foregroundStyle(Color.barkainOnPrimaryFixed)
                        .padding(.horizontal, Spacing.sm)
                        .padding(.vertical, Spacing.xxs)
                        .background(Capsule().fill(Color.barkainPrimaryFixed))
                }
            }

            if recentlyScanned.items.isEmpty {
                recentlyScannedEmpty
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: Spacing.sm) {
                        ForEach(recentlyScanned.items) { item in
                            recentlyScannedCard(item)
                        }
                    }
                    .padding(.horizontal, Spacing.xxs)
                    .padding(.vertical, Spacing.xs)
                }
                .scrollClipDisabled()
            }
        }
    }

    private var recentlyScannedEmpty: some View {
        HStack(spacing: Spacing.md) {
            Image(systemName: "nose.fill")
                .font(.title2)
                .foregroundStyle(Color.barkainPrimary)
                .frame(width: 44, height: 44)
                .background(Circle().fill(Color.barkainPrimaryFixed.opacity(0.5)))

            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text("No trail yet")
                    .font(.barkainHeadline)
                    .foregroundStyle(Color.barkainOnSurface)
                Text("Scan or search for a product — it'll show up here for a quick re-sniff.")
                    .font(.barkainCaption)
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Spacing.lg)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .fill(Color.barkainSurfaceContainerLowest)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .stroke(Color.barkainOutlineVariant.opacity(0.3), style: StrokeStyle(lineWidth: 1, dash: [4, 4]))
        )
    }

    private func recentlyScannedCard(_ item: RecentlyScannedProduct) -> some View {
        Button {
            onSelectRecent?(item)
        } label: {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                thumbnail(for: item)
                    .frame(width: 140, height: 140)
                    .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous))

                VStack(alignment: .leading, spacing: 2) {
                    if let brand = item.brand, !brand.isEmpty {
                        Text(brand.uppercased())
                            .font(.caption2.weight(.bold))
                            .tracking(0.8)
                            .foregroundStyle(Color.barkainPrimary)
                            .lineLimit(1)
                    }
                    Text(item.name)
                        .font(.barkainCaption.weight(.semibold))
                        .foregroundStyle(Color.barkainOnSurface)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                }
                .frame(width: 140, alignment: .leading)
            }
            .padding(Spacing.sm)
            .background(
                RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                    .fill(Color.barkainSurfaceContainerLowest)
            )
            .barkainShadowSoft()
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private func thumbnail(for item: RecentlyScannedProduct) -> some View {
        if let urlString = item.imageUrl, let url = URL(string: urlString) {
            AsyncImage(url: url) { phase in
                switch phase {
                case .success(let image):
                    image.resizable().aspectRatio(contentMode: .fill)
                default:
                    thumbnailPlaceholder
                }
            }
        } else {
            thumbnailPlaceholder
        }
    }

    private var thumbnailPlaceholder: some View {
        ZStack {
            Color.barkainSurfaceContainer
            Image(systemName: "pawprint.fill")
                .font(.largeTitle)
                .foregroundStyle(Color.barkainPrimary.opacity(0.4))
        }
    }

    // MARK: - Identity nudge

    private var identityNudge: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack(spacing: Spacing.xs) {
                Image(systemName: "sparkles")
                    .foregroundStyle(Color.barkainPrimary)
                Text("Unlock more deals")
                    .barkainEyebrow()
            }
            Text("Add your identity profile in the Kennel tab — military, student, AAA, Costco and more each unlock their own retailer discounts.")
                .font(.barkainBody)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .fill(Color.barkainPrimaryFixed.opacity(0.45))
        )
    }
}

// MARK: - Preview

#Preview("Empty home") {
    NavigationStack {
        HomeView(onSelectScan: {}, onSelectSearch: {})
    }
}
