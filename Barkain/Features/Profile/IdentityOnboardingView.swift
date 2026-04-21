import SwiftUI

// MARK: - IdentityOnboardingView

struct IdentityOnboardingView: View {

    // MARK: - State

    @State private var step: Step = .identityGroups
    @State var viewModel: IdentityOnboardingViewModel
    @Binding var hasCompletedOnboarding: Bool
    @Environment(\.dismiss) private var dismiss

    // MARK: - Types

    enum Step: Int, CaseIterable {
        case identityGroups
        case memberships
        case verification

        var title: String {
            switch self {
            case .identityGroups: return "Who you are"
            case .memberships: return "Memberships"
            case .verification: return "Verification"
            }
        }

        var subtitle: String {
            switch self {
            case .identityGroups:
                return "Tell us which groups you belong to. Each unlocks discounts at participating retailers."
            case .memberships:
                return "Any warehouse clubs, AAA, or AARP membership you hold can unlock additional savings."
            case .verification:
                return "If you've already verified through ID.me or SheerID, check below to fast-track discounts."
            }
        }
    }

    // MARK: - Body

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.lg) {
                    header
                    stepContent
                    Spacer(minLength: Spacing.xl)
                }
                .padding(Spacing.lg)
            }
            .background(Color.barkainSurface.ignoresSafeArea())
            .safeAreaInset(edge: .bottom) { actionBar }
            .navigationTitle(step.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") { dismiss() }
                        .tint(.barkainPrimary)
                }
            }
            .alert("Couldn't save profile", isPresented: errorBinding, presenting: viewModel.error) { _ in
                Button("OK", role: .cancel) { viewModel.error = nil }
            } message: { err in
                Text(err.localizedDescription)
            }
        }
    }

    // MARK: - Header

    private var header: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack(spacing: Spacing.xs) {
                Image(systemName: "pawprint.fill")
                    .font(.caption)
                    .foregroundStyle(Color.barkainPrimary)
                Text("Step \(step.rawValue + 1) of \(Step.allCases.count)")
                    .barkainEyebrow()
            }
            stepIndicator
            Text(step.subtitle)
                .font(.barkainBody)
                .foregroundStyle(Color.barkainOnSurfaceVariant)
                .padding(.top, Spacing.xxs)
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .fill(Color.barkainPrimaryFixed.opacity(0.35))
        )
    }

    private var stepIndicator: some View {
        HStack(spacing: Spacing.xxs) {
            ForEach(Step.allCases, id: \.rawValue) { s in
                Capsule()
                    .fill(
                        s.rawValue <= step.rawValue
                            ? AnyShapeStyle(Color.barkainPrimaryGradient)
                            : AnyShapeStyle(Color.barkainOutlineVariant.opacity(0.5))
                    )
                    .frame(height: 6)
            }
        }
    }

    // MARK: - Step Content

    @ViewBuilder
    private var stepContent: some View {
        switch step {
        case .identityGroups: identityGroupsContent
        case .memberships: membershipsContent
        case .verification: verificationContent
        }
    }

    private var identityGroupsContent: some View {
        VStack(spacing: Spacing.sm) {
            toggleRow(title: "Military (active duty)", isOn: $viewModel.request.isMilitary)
            toggleRow(title: "Veteran", isOn: $viewModel.request.isVeteran)
            toggleRow(title: "Student (college)", isOn: $viewModel.request.isStudent)
            toggleRow(title: "Teacher / educator", isOn: $viewModel.request.isTeacher)
            toggleRow(title: "First responder", isOn: $viewModel.request.isFirstResponder)
            toggleRow(title: "Nurse", isOn: $viewModel.request.isNurse)
            toggleRow(title: "Healthcare worker", isOn: $viewModel.request.isHealthcareWorker)
            toggleRow(title: "Senior (50+)", isOn: $viewModel.request.isSenior)
            toggleRow(title: "Government employee", isOn: $viewModel.request.isGovernment)
        }
    }

    private var membershipsContent: some View {
        VStack(spacing: Spacing.sm) {
            toggleRow(title: "AAA member", isOn: $viewModel.request.isAaaMember)
            toggleRow(title: "AARP member", isOn: $viewModel.request.isAarpMember)
            toggleRow(title: "Costco member", isOn: $viewModel.request.isCostcoMember)
            toggleRow(title: "Sam's Club member", isOn: $viewModel.request.isSamsMember)
            toggleRow(title: "Amazon Prime member", isOn: $viewModel.request.isPrimeMember)
        }
    }

    private var verificationContent: some View {
        VStack(spacing: Spacing.sm) {
            toggleRow(title: "Verified with ID.me", isOn: $viewModel.request.idMeVerified)
            toggleRow(title: "Verified with SheerID", isOn: $viewModel.request.sheerIdVerified)
        }
    }

    private func toggleRow(title: String, isOn: Binding<Bool>) -> some View {
        Toggle(isOn: isOn) {
            Text(title)
                .font(.barkainBody)
                .foregroundStyle(Color.barkainOnSurface)
        }
        .tint(.barkainPrimary)
        .padding(Spacing.md)
        .background(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .fill(Color.barkainSurfaceContainerLowest)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Spacing.cornerRadius, style: .continuous)
                .stroke(
                    isOn.wrappedValue ? Color.barkainPrimaryContainer.opacity(0.6) : Color.barkainOutlineVariant.opacity(0.4),
                    lineWidth: isOn.wrappedValue ? 1.5 : 1
                )
        )
        .barkainShadowSoft()
    }

    // MARK: - Action Bar

    private var actionBar: some View {
        HStack(spacing: Spacing.sm) {
            Button(role: .cancel) {
                Task { await handleSkip() }
            } label: {
                Text("Skip")
                    .font(.barkainHeadline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Spacing.sm)
            }
            .buttonStyle(.bordered)
            .tint(.barkainOnSurfaceVariant)
            .disabled(viewModel.isSaving)

            Button {
                Task { await handleContinue() }
            } label: {
                HStack {
                    if viewModel.isSaving && step == .verification {
                        ProgressView().tint(.white)
                    }
                    Text(step == .verification ? "Save" : "Continue")
                        .font(.barkainHeadline)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, Spacing.sm)
            }
            .buttonStyle(.borderedProminent)
            .tint(.barkainPrimary)
            .disabled(viewModel.isSaving)
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.sm)
        .background(.regularMaterial)
    }

    // MARK: - Navigation Logic

    private func handleContinue() async {
        if step == .verification {
            await viewModel.save()
            if viewModel.saved {
                hasCompletedOnboarding = true
                dismiss()
            }
        } else if let next = Step(rawValue: step.rawValue + 1) {
            withAnimation(.easeInOut(duration: 0.25)) {
                step = next
            }
        }
    }

    private func handleSkip() async {
        if step == .verification {
            // Skipping the final step saves whatever draft state we have
            // (which may be all-false if the user skipped every step).
            await viewModel.save()
            if viewModel.saved {
                hasCompletedOnboarding = true
                dismiss()
            }
        } else if let next = Step(rawValue: step.rawValue + 1) {
            withAnimation(.easeInOut(duration: 0.25)) {
                step = next
            }
        }
    }

    private var errorBinding: Binding<Bool> {
        Binding(
            get: { viewModel.error != nil },
            set: { if !$0 { viewModel.error = nil } }
        )
    }
}

// MARK: - Preview

#Preview {
    IdentityOnboardingView(
        viewModel: IdentityOnboardingViewModel(apiClient: PreviewOnboardingAPIClient()),
        hasCompletedOnboarding: .constant(false)
    )
}

private struct PreviewOnboardingAPIClient: APIClientProtocol {
    func resolveProduct(upc: String) async throws -> Product { fatalError("Preview only") }
    func resolveProductFromSearch(deviceName: String, brand: String?, model: String?) async throws -> Product { fatalError("Preview only") }
    func searchProducts(query: String, maxResults: Int, forceGemini: Bool) async throws -> ProductSearchResponse {
        ProductSearchResponse(query: query, results: [], totalResults: 0, cached: false)
    }
    func getPrices(productId: UUID, forceRefresh: Bool) async throws -> PriceComparison { fatalError("Preview only") }
    func streamPrices(productId: UUID, forceRefresh: Bool, queryOverride: String?) -> AsyncThrowingStream<RetailerStreamEvent, Error> {
        AsyncThrowingStream { $0.finish() }
    }
    func getIdentityProfile() async throws -> IdentityProfile { fatalError("Preview only") }
    func updateIdentityProfile(_ request: IdentityProfileRequest) async throws -> IdentityProfile {
        IdentityProfile(
            userId: "preview",
            isMilitary: request.isMilitary,
            isVeteran: request.isVeteran,
            isStudent: request.isStudent,
            isTeacher: request.isTeacher,
            isFirstResponder: request.isFirstResponder,
            isNurse: request.isNurse,
            isHealthcareWorker: request.isHealthcareWorker,
            isSenior: request.isSenior,
            isGovernment: request.isGovernment,
            isAaaMember: request.isAaaMember,
            isAarpMember: request.isAarpMember,
            isCostcoMember: request.isCostcoMember,
            isPrimeMember: request.isPrimeMember,
            isSamsMember: request.isSamsMember,
            idMeVerified: request.idMeVerified,
            sheerIdVerified: request.sheerIdVerified,
            createdAt: Date(),
            updatedAt: Date()
        )
    }
    func getEligibleDiscounts(productId: UUID?) async throws -> IdentityDiscountsResponse {
        IdentityDiscountsResponse(eligibleDiscounts: [], identityGroupsActive: [])
    }
    func getCardCatalog() async throws -> [CardRewardProgram] { [] }
    func getUserCards() async throws -> [UserCardSummary] { [] }
    func addCard(_ request: AddCardRequest) async throws -> UserCardSummary { fatalError("Preview only") }
    func removeCard(userCardId: UUID) async throws {}
    func setPreferredCard(userCardId: UUID) async throws -> UserCardSummary { fatalError("Preview only") }
    func setCardCategories(userCardId: UUID, request: SetCategoriesRequest) async throws {}
    func getCardRecommendations(productId: UUID) async throws -> CardRecommendationsResponse {
        CardRecommendationsResponse(recommendations: [], userHasCards: false)
    }
    func getBillingStatus() async throws -> BillingStatus {
        BillingStatus(tier: "free", expiresAt: nil, isActive: false, entitlementId: nil)
    }
    func getAffiliateURL(
        productId: UUID?,
        retailerId: String,
        productURL: String
    ) async throws -> AffiliateURLResponse {
        AffiliateURLResponse(
            affiliateUrl: productURL,
            isAffiliated: false,
            network: nil,
            retailerId: retailerId
        )
    }
    func getAffiliateStats() async throws -> AffiliateStatsResponse {
        AffiliateStatsResponse(clicksByRetailer: [:], totalClicks: 0)
    }
}
