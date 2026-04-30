import SwiftUI

// MARK: - ProfileView

struct ProfileView: View {

    // MARK: - State

    @State private var profile: IdentityProfile?
    @State private var userCards: [UserCardSummary] = []
    @State private var affiliateStats: AffiliateStatsResponse?
    @State private var isLoading = false
    @State private var loadError: APIError?
    @State private var showEditSheet = false
    @State private var showCardSheet = false
    @State private var showPaywall = false
    @State private var showLocationSheet = false
    @State private var savedLocation: LocationPreferences.Stored?

    @Environment(SubscriptionService.self) private var subscription
    @Environment(FeatureGateService.self) private var featureGate

    @AppStorage("hasCompletedIdentityOnboarding")
    private var hasCompletedOnboarding: Bool = false

    private let apiClient: APIClientProtocol
    private let locationPreferences: LocationPreferences
    private let portalMembershipPreferences: PortalMembershipPreferences

    // Step 3g-B — local mirror of the portal-membership store. Read once
    // on appear, written through `setMember` so toggling persists +
    // refreshes the section row labels in the same flush.
    @State private var portalMemberships: [String: Bool] = [:]

    // MARK: - Init

    init(
        apiClient: APIClientProtocol = APIClient(),
        locationPreferences: LocationPreferences = LocationPreferences(),
        portalMembershipPreferences: PortalMembershipPreferences = PortalMembershipPreferences()
    ) {
        self.apiClient = apiClient
        self.locationPreferences = locationPreferences
        self.portalMembershipPreferences = portalMembershipPreferences
    }

    // MARK: - Body

    var body: some View {
        content
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.barkainSurface.ignoresSafeArea())
            .navigationTitle("The Kennel")
            .task {
                await loadProfile()
                await loadCards()
                await loadAffiliateStats()
                savedLocation = locationPreferences.current()
                portalMemberships = portalMembershipPreferences.current()
            }
            .sheet(isPresented: $showEditSheet, onDismiss: {
                Task { await loadProfile() }
            }) {
                IdentityOnboardingView(
                    viewModel: IdentityOnboardingViewModel(
                        apiClient: apiClient,
                        initial: profile
                    ),
                    hasCompletedOnboarding: $hasCompletedOnboarding
                )
            }
            .sheet(isPresented: $showCardSheet, onDismiss: {
                Task { await loadCards() }
            }) {
                CardSelectionView(apiClient: apiClient)
            }
            // Step 2f: paywall sheet for the "Upgrade to Pro" button below.
            .sheet(isPresented: $showPaywall) {
                PaywallHost()
            }
            .sheet(isPresented: $showLocationSheet, onDismiss: {
                savedLocation = locationPreferences.current()
            }) {
                LocationPickerSheet(preferences: locationPreferences)
            }
    }

    // MARK: - Content Switch

    @ViewBuilder
    private var content: some View {
        if isLoading && profile == nil {
            LoadingState(message: "Loading your profile…")
        } else if let loadError {
            EmptyState(
                icon: "exclamationmark.triangle",
                title: "Couldn't load profile",
                subtitle: loadError.localizedDescription,
                actionTitle: "Try again",
                action: { Task { await loadProfile() } }
            )
        } else if let profile, hasAnyFlag(profile) {
            profileSummary(profile)
        } else {
            ScrollView {
                VStack(spacing: Spacing.lg) {
                    kennelHeader
                    scentTrailsCard
                    emptyProfileCTA
                    subscriptionSection
                    marketplaceLocationSection
                    cardsSection
                    portalMembershipsSection
                }
                .padding(Spacing.lg)
            }
        }
    }

    // MARK: - Kennel Header (new)
    //
    // Hero banner for the Profile tab. Mirrors the prototype's "Welcome
    // back" card but keeps the copy honest — we don't have a user name,
    // so the subtitle addresses the subscription tier instead.

    private var kennelHeader: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.xs) {
                Image(systemName: "pawprint.fill")
                    .foregroundStyle(Color.barkainPrimary)
                Text("Welcome back")
                    .barkainEyebrow()
            }
            Text("The Kennel")
                .font(.barkainLargeTitle)
                .foregroundStyle(Color.barkainOnSurface)
            Text(kennelSubtitle)
                .font(.barkainBody)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Spacing.lg)
        .accessibilityIdentifier("kennelHeader")
    }

    private var kennelSubtitle: String {
        if subscription.isProUser {
            return "You're running Barkain Pro — unlimited sniffs, every deal."
        }
        return "Keep tabs on your identity profile, cards, and the deals we've fetched for you."
    }

    // MARK: - Scent Trails Card (new)
    //
    // Gradient hero showing real affiliate click totals. Replaces the
    // prototype's "Barkain Points" card — we don't have a loyalty
    // program yet, but `affiliate/stats.total_clicks` is a real number
    // that tracks how many deals the user actually followed through on.

    private var scentTrailsCard: some View {
        VStack(spacing: Spacing.md) {
            Text("Scent Trails Followed")
                .barkainEyebrow(color: .white.opacity(0.9))

            HStack(alignment: .lastTextBaseline, spacing: Spacing.xs) {
                Text("\(affiliateStats?.totalClicks ?? 0)")
                    .font(.system(size: 56, weight: .black, design: .rounded))
                    .foregroundStyle(.white)
                Image(systemName: "pawprint.fill")
                    .font(.title2)
                    .foregroundStyle(.white.opacity(0.85))
            }

            Text(scentTrailsSubtitle)
                .font(.barkainCaption)
                .foregroundStyle(.white.opacity(0.9))
                .multilineTextAlignment(.center)
                .padding(.horizontal, Spacing.md)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, Spacing.xl)
        .padding(.horizontal, Spacing.lg)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadiusLarge, style: .continuous)
                .fill(Color.barkainPrimaryGradient)
        )
        .overlay(alignment: .bottomTrailing) {
            Image(systemName: "pawprint.fill")
                .font(.system(size: 180))
                .foregroundStyle(.white.opacity(0.08))
                .rotationEffect(.degrees(-15))
                .offset(x: 30, y: 30)
                .clipped()
        }
        .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadiusLarge, style: .continuous))
        .barkainShadowGlow()
        .accessibilityIdentifier("scentTrailsCard")
    }

    private var scentTrailsSubtitle: String {
        let total = affiliateStats?.totalClicks ?? 0
        if total == 0 {
            return "Tap any retailer in a price comparison to follow the scent to a real deal."
        }
        let top = affiliateStats?.clicksByRetailer
            .max(by: { $0.value < $1.value })
            .map { $0.key.capitalized }
        if let top {
            return "You've sniffed out \(total) deal\(total == 1 ? "" : "s"). Top trail: \(top)."
        }
        return "You've sniffed out \(total) deal\(total == 1 ? "" : "s")."
    }

    // MARK: - Subscription (Step 2f)
    //
    // Tier badge + scan count + upgrade button (or Customer Center link
    // for Pro users). Reads `SubscriptionService` for the tier and
    // `FeatureGateService` for the daily scan tally.

    @ViewBuilder
    private var subscriptionSection: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack {
                Text("Subscription")
                    .barkainEyebrow()
                Spacer()
                tierBadge
            }

            if subscription.isProUser {
                NavigationLink {
                    CustomerCenterHost()
                } label: {
                    HStack {
                        Image(systemName: "gearshape")
                        Text("Manage subscription")
                            .font(.barkainBody)
                        Spacer()
                        Image(systemName: "chevron.right")
                            .foregroundStyle(Color.barkainOnSurfaceVariant)
                    }
                    .padding(Spacing.md)
                    .background(Color.barkainSurfaceContainerLow)
                    .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous))
                }
                .buttonStyle(.plain)
            } else {
                if let remaining = featureGate.remainingScans {
                    Text("Scans today: \(featureGate.dailyScanCount) / \(FeatureGateService.freeDailyScanLimit) — \(remaining) left")
                        .font(.barkainCaption)
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                }
                Button {
                    showPaywall = true
                } label: {
                    HStack {
                        Image(systemName: "pawprint.fill")
                        Text("Upgrade to Barkain Pro")
                            .font(.barkainHeadline)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Spacing.sm)
                }
                .buttonStyle(.borderedProminent)
                .tint(.barkainPrimary)
            }
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .fill(Color.barkainSurfaceContainerLowest)
        )
        .barkainShadowSoft()
        .accessibilityIdentifier("subscriptionSection")
    }

    // MARK: - Marketplace Location (fb-marketplace-location)
    //
    // Tap-through to `LocationPickerSheet`. Shows the persisted display
    // label + radius when set, or a "Not set" hint that explains what
    // the default (sanfrancisco) means. The sheet owns all permission
    // plumbing — this row is just an entry point.

    private var marketplaceLocationSection: some View {
        Button {
            showLocationSheet = true
        } label: {
            HStack(spacing: Spacing.sm) {
                Image(systemName: "mappin.and.ellipse")
                    .font(.title3)
                    .foregroundStyle(Color.barkainPrimary)
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text("Marketplace location")
                        .font(.barkainHeadline)
                        .foregroundStyle(Color.barkainOnSurface)
                    Text(marketplaceLocationSubtitle)
                        .font(.barkainCaption)
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                        .multilineTextAlignment(.leading)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .foregroundStyle(Color.barkainOnSurfaceVariant)
            }
            .padding(Spacing.lg)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                    .fill(Color.barkainSurfaceContainerLowest)
            )
            .barkainShadowSoft()
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("marketplaceLocationSection")
    }

    private var marketplaceLocationSubtitle: String {
        if let stored = savedLocation {
            return "\(stored.displayLabel) · \(stored.radiusMiles) mi"
        }
        return "Defaults to San Francisco. Tap to set your own city for Facebook Marketplace."
    }

    private var tierBadge: some View {
        Text(subscription.isProUser ? "Barkain Pro" : "Free Plan")
            .font(.barkainCaption.weight(.bold))
            .foregroundStyle(subscription.isProUser ? .white : Color.barkainOnPrimaryFixed)
            .padding(.horizontal, Spacing.md)
            .padding(.vertical, Spacing.xxs)
            .background(
                Capsule().fill(
                    subscription.isProUser
                        ? AnyShapeStyle(Color.barkainPrimaryGradient)
                        : AnyShapeStyle(Color.barkainPrimaryFixed)
                )
            )
    }

    // MARK: - Summary

    private func profileSummary(_ profile: IdentityProfile) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                kennelHeader
                scentTrailsCard

                subscriptionSection

                marketplaceLocationSection

                if !activeGroupChips(profile).isEmpty {
                    chipsSection(
                        title: "Identity groups",
                        chips: activeGroupChips(profile)
                    )
                }

                if !membershipChips(profile).isEmpty {
                    chipsSection(
                        title: "Memberships",
                        chips: membershipChips(profile)
                    )
                }

                if !verificationChips(profile).isEmpty {
                    chipsSection(
                        title: "Verification",
                        chips: verificationChips(profile)
                    )
                }

                cardsSection
                portalMembershipsSection

                Button {
                    showEditSheet = true
                } label: {
                    HStack {
                        Image(systemName: "pencil")
                        Text("Edit profile")
                            .font(.barkainHeadline)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Spacing.sm)
                }
                .buttonStyle(.borderedProminent)
                .tint(.barkainPrimary)
            }
            .padding(Spacing.lg)
        }
    }

    // MARK: - My Cards

    private var cardsSection: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack {
                Text("My Cards")
                    .barkainEyebrow()
                Spacer()
                Text("\(userCards.count)")
                    .font(.barkainCaption.weight(.bold))
                    .foregroundStyle(Color.barkainOnPrimaryFixed)
                    .padding(.horizontal, Spacing.sm)
                    .padding(.vertical, Spacing.xxs)
                    .background(
                        Capsule().fill(Color.barkainPrimaryFixed)
                    )
            }

            if userCards.isEmpty {
                VStack(alignment: .leading, spacing: Spacing.sm) {
                    Text("Add your credit cards to see which one earns the most at each retailer.")
                        .font(.barkainBody)
                        .foregroundStyle(Color.barkainOnSurfaceVariant)
                    Button {
                        showCardSheet = true
                    } label: {
                        HStack {
                            Image(systemName: "creditcard.and.123")
                            Text("Add cards")
                                .font(.barkainHeadline)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, Spacing.sm)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.barkainPrimary)
                }
            } else {
                FlowLayout(spacing: Spacing.xs) {
                    ForEach(userCards) { card in
                        HStack(spacing: Spacing.xxs) {
                            if card.isPreferred {
                                Image(systemName: "star.fill")
                                    .font(.caption2)
                                    .foregroundStyle(.yellow)
                            }
                            Text(card.cardDisplayName)
                                .font(.barkainCaption.weight(.semibold))
                        }
                        .foregroundStyle(Color.barkainOnPrimaryFixed)
                        .padding(.horizontal, Spacing.md)
                        .padding(.vertical, Spacing.xs)
                        .background(
                            Capsule(style: .continuous)
                                .fill(Color.barkainPrimaryFixed)
                        )
                        .overlay(
                            Capsule(style: .continuous)
                                .stroke(Color.barkainPrimaryContainer.opacity(0.4), lineWidth: 1)
                        )
                    }
                }

                Button {
                    showCardSheet = true
                } label: {
                    HStack {
                        Image(systemName: "plus.circle")
                        Text("Manage cards")
                            .font(.barkainHeadline)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Spacing.sm)
                }
                .buttonStyle(.bordered)
                .tint(.barkainPrimary)
            }
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .fill(Color.barkainSurfaceContainerLowest)
        )
        .barkainShadowSoft()
        .accessibilityIdentifier("cardsSection")
    }

    // MARK: - Portal memberships (Step 3g-B)
    //
    // Three toggles for the active shopping portals. Toggling persists
    // through `PortalMembershipPreferences.setMember`; the next
    // `/recommend` call picks up the change because the M6 cache key
    // includes a hash of active memberships. No fetch trigger here —
    // ScannerViewModel reads the prefs at fetch time.

    private var portalMembershipsSection: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack(spacing: Spacing.sm) {
                Image(systemName: "tag.fill")
                    .font(.title3)
                    .foregroundStyle(Color.barkainPrimary)
                Text("Portal memberships")
                    .font(.barkainHeadline)
                    .foregroundStyle(Color.barkainOnSurface)
            }
            Text(
                "Toggle on the cashback portals you're already a member "
                    + "of. We'll show you a 1-tap deeplink instead of a "
                    + "signup pitch when you check out."
            )
            .font(.barkainCaption)
            .foregroundStyle(Color.barkainOnSurfaceVariant)
            ForEach(PortalMembershipPreferences.knownPortals, id: \.self) { portal in
                portalMembershipToggle(for: portal)
            }
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .fill(Color.barkainSurfaceContainerLowest)
        )
        .barkainShadowSoft()
        .accessibilityIdentifier("portalMembershipsSection")
    }

    @ViewBuilder
    private func portalMembershipToggle(for portal: String) -> some View {
        let displayName = PortalMembershipPreferences.displayNames[portal] ?? portal
        let binding = Binding<Bool>(
            get: { portalMemberships[portal] == true },
            set: { newValue in
                portalMembershipPreferences.setMember(portal, isMember: newValue)
                portalMemberships[portal] = newValue
            }
        )
        Toggle(isOn: binding) {
            Text(displayName)
                .font(.barkainBody)
                .foregroundStyle(Color.barkainOnSurface)
        }
        .accessibilityIdentifier("portalMembershipToggle_\(portal)")
    }

    private func chipsSection(title: String, chips: [String]) -> some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text(title)
                .barkainEyebrow()

            FlowLayout(spacing: Spacing.xs) {
                ForEach(chips, id: \.self) { chip in
                    Text(chip)
                        .font(.barkainCaption)
                        .foregroundStyle(Color.barkainOnPrimaryFixed)
                        .padding(.horizontal, Spacing.md)
                        .padding(.vertical, Spacing.xs)
                        .background(
                            Capsule(style: .continuous)
                                .fill(Color.barkainPrimaryFixed)
                        )
                        .overlay(
                            Capsule(style: .continuous)
                                .stroke(Color.barkainPrimaryContainer.opacity(0.4), lineWidth: 1)
                        )
                }
            }
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .fill(Color.barkainSurfaceContainerLowest)
        )
        .barkainShadowSoft()
    }

    private var emptyProfileCTA: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack(spacing: Spacing.xs) {
                Image(systemName: "person.crop.circle.badge.plus")
                    .foregroundStyle(Color.barkainPrimary)
                Text("Your scent profile")
                    .barkainEyebrow()
            }
            Text("Tell Barkain who you are to unlock exclusive discounts at Samsung.com, Apple, HP, and more.")
                .font(.barkainBody)
                .foregroundStyle(Color.barkainOnSurfaceVariant)

            Button {
                showEditSheet = true
            } label: {
                HStack {
                    Image(systemName: "pawprint.fill")
                    Text("Set up profile")
                        .font(.barkainHeadline)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, Spacing.sm)
            }
            .buttonStyle(.borderedProminent)
            .tint(.barkainPrimary)
            .padding(.top, Spacing.xs)
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .fill(Color.barkainSurfaceContainerLowest)
        )
        .barkainShadowSoft()
    }

    // MARK: - Load

    private func loadProfile() async {
        isLoading = true
        defer { isLoading = false }
        do {
            profile = try await apiClient.getIdentityProfile()
            loadError = nil
        } catch let err as APIError {
            loadError = err
        } catch {
            loadError = .unknown(0, error.localizedDescription)
        }
    }

    private func loadCards() async {
        do {
            userCards = try await apiClient.getUserCards()
        } catch {
            // Non-fatal — profile still renders without the cards section.
            userCards = []
        }
    }

    private func loadAffiliateStats() async {
        // Non-fatal: if this fails, the Scent Trails card shows zero.
        affiliateStats = try? await apiClient.getAffiliateStats()
    }

    // MARK: - Helpers

    private func hasAnyFlag(_ p: IdentityProfile) -> Bool {
        p.isMilitary || p.isVeteran || p.isStudent || p.isTeacher
            || p.isFirstResponder || p.isNurse || p.isHealthcareWorker
            || p.isSenior || p.isGovernment || p.isAaaMember || p.isAarpMember
            || p.isCostcoMember || p.isPrimeMember || p.isSamsMember
            || p.idMeVerified || p.sheerIdVerified
    }

    private func activeGroupChips(_ p: IdentityProfile) -> [String] {
        var chips: [String] = []
        if p.isMilitary { chips.append("Military") }
        if p.isVeteran { chips.append("Veteran") }
        if p.isStudent { chips.append("Student") }
        if p.isTeacher { chips.append("Teacher") }
        if p.isFirstResponder { chips.append("First responder") }
        if p.isNurse { chips.append("Nurse") }
        if p.isHealthcareWorker { chips.append("Healthcare") }
        if p.isSenior { chips.append("Senior") }
        if p.isGovernment { chips.append("Government") }
        return chips
    }

    private func membershipChips(_ p: IdentityProfile) -> [String] {
        var chips: [String] = []
        if p.isAaaMember { chips.append("AAA") }
        if p.isAarpMember { chips.append("AARP") }
        if p.isCostcoMember { chips.append("Costco") }
        if p.isSamsMember { chips.append("Sam's Club") }
        if p.isPrimeMember { chips.append("Prime") }
        return chips
    }

    private func verificationChips(_ p: IdentityProfile) -> [String] {
        var chips: [String] = []
        if p.idMeVerified { chips.append("ID.me verified") }
        if p.sheerIdVerified { chips.append("SheerID verified") }
        return chips
    }
}

// MARK: - FlowLayout
// Minimal wrap-HStack used for identity chips. Avoids pulling in a dependency.

private struct FlowLayout: Layout {
    var spacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var rowWidth: CGFloat = 0
        var totalHeight: CGFloat = 0
        var rowHeight: CGFloat = 0

        for sub in subviews {
            let size = sub.sizeThatFits(.unspecified)
            if rowWidth + size.width > maxWidth {
                totalHeight += rowHeight + spacing
                rowWidth = size.width + spacing
                rowHeight = size.height
            } else {
                rowWidth += size.width + spacing
                rowHeight = max(rowHeight, size.height)
            }
        }
        totalHeight += rowHeight
        return CGSize(width: maxWidth, height: totalHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let maxWidth = bounds.width
        var x: CGFloat = bounds.minX
        var y: CGFloat = bounds.minY
        var rowHeight: CGFloat = 0

        for sub in subviews {
            let size = sub.sizeThatFits(.unspecified)
            if x - bounds.minX + size.width > maxWidth {
                x = bounds.minX
                y += rowHeight + spacing
                rowHeight = 0
            }
            sub.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}

// MARK: - Preview

#Preview("Empty profile") {
    NavigationStack {
        ProfileView(apiClient: PreviewProfileAPIClient(flagSet: false))
    }
    .environment(SubscriptionService())
    .environment(FeatureGateService(proTierProvider: { false }))
}

#Preview("Veteran profile") {
    NavigationStack {
        ProfileView(apiClient: PreviewProfileAPIClient(flagSet: true))
    }
    .environment(SubscriptionService())
    .environment(FeatureGateService(proTierProvider: { false }))
}

private final class PreviewProfileAPIClient: BarePreviewAPIClient, @unchecked Sendable {
    let flagSet: Bool

    init(flagSet: Bool) {
        self.flagSet = flagSet
        super.init()
    }

    override func getIdentityProfile() async throws -> IdentityProfile {
        IdentityProfile(
            userId: "preview",
            isMilitary: false,
            isVeteran: flagSet,
            isStudent: flagSet,
            isTeacher: false,
            isFirstResponder: false,
            isNurse: false,
            isHealthcareWorker: false,
            isSenior: false,
            isGovernment: false,
            isYoungAdult: false,
            isAaaMember: false,
            isAarpMember: false,
            isCostcoMember: flagSet,
            isPrimeMember: false,
            isSamsMember: false,
            idMeVerified: flagSet,
            sheerIdVerified: false,
            createdAt: Date(),
            updatedAt: Date()
        )
    }
}
