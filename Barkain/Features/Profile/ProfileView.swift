import SwiftUI

// MARK: - ProfileView

struct ProfileView: View {

    // MARK: - State

    @State private var profile: IdentityProfile?
    @State private var isLoading = false
    @State private var loadError: APIError?
    @State private var showEditSheet = false

    @AppStorage("hasCompletedIdentityOnboarding")
    private var hasCompletedOnboarding: Bool = false

    private let apiClient: APIClientProtocol

    // MARK: - Init

    init(apiClient: APIClientProtocol = APIClient()) {
        self.apiClient = apiClient
    }

    // MARK: - Body

    var body: some View {
        content
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.barkainSurface.ignoresSafeArea())
            .navigationTitle("Profile")
            .task {
                await loadProfile()
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
            emptyProfileCTA
        }
    }

    // MARK: - Summary

    private func profileSummary(_ profile: IdentityProfile) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.lg) {
                headerCard(profile)

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

    private func headerCard(_ profile: IdentityProfile) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text("Your Barkain profile")
                .font(.barkainTitle2)
                .foregroundStyle(Color.barkainOnSurface)
            Text("Tap any discount you see in the Scan tab to verify through the retailer.")
                .font(.barkainBody)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Spacing.lg)
        .background(Color.barkainPrimaryFixed.opacity(0.4))
        .clipShape(RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous))
    }

    private func chipsSection(title: String, chips: [String]) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(title)
                .font(.barkainHeadline)
                .foregroundStyle(Color.barkainOnSurfaceVariant)

            FlowLayout(spacing: Spacing.xs) {
                ForEach(chips, id: \.self) { chip in
                    Text(chip)
                        .font(.barkainCaption)
                        .foregroundStyle(Color.barkainPrimary)
                        .padding(.horizontal, Spacing.sm)
                        .padding(.vertical, Spacing.xxs)
                        .background(Color.barkainPrimaryFixed.opacity(0.6))
                        .clipShape(Capsule())
                }
            }
        }
    }

    private var emptyProfileCTA: some View {
        EmptyState(
            icon: "person.crop.circle.badge.plus",
            title: "No profile yet",
            subtitle: "Set up your identity profile to unlock exclusive discounts at Samsung.com, Apple, HP, and more.",
            actionTitle: "Set up profile",
            action: { showEditSheet = true }
        )
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
}

#Preview("Veteran profile") {
    NavigationStack {
        ProfileView(apiClient: PreviewProfileAPIClient(flagSet: true))
    }
}

private struct PreviewProfileAPIClient: APIClientProtocol {
    let flagSet: Bool
    func resolveProduct(upc: String) async throws -> Product { fatalError("Preview only") }
    func getPrices(productId: UUID, forceRefresh: Bool) async throws -> PriceComparison { fatalError("Preview only") }
    func streamPrices(productId: UUID, forceRefresh: Bool) -> AsyncThrowingStream<RetailerStreamEvent, Error> {
        AsyncThrowingStream { $0.finish() }
    }
    func getIdentityProfile() async throws -> IdentityProfile {
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
    func updateIdentityProfile(_ request: IdentityProfileRequest) async throws -> IdentityProfile {
        fatalError("Preview only")
    }
    func getEligibleDiscounts(productId: UUID?) async throws -> IdentityDiscountsResponse {
        IdentityDiscountsResponse(eligibleDiscounts: [], identityGroupsActive: [])
    }
}
