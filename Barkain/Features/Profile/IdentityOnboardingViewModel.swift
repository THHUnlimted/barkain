import Foundation

// MARK: - IdentityOnboardingViewModel

@MainActor
@Observable
final class IdentityOnboardingViewModel {

    // MARK: - Draft State

    /// Current draft of the request body. Toggles mutate this in place.
    var request = IdentityProfileRequest()

    // MARK: - UI State

    var isSaving = false
    var error: APIError?
    var saved = false

    // MARK: - Dependencies

    private let apiClient: APIClientProtocol

    // MARK: - Init

    /// Create a fresh onboarding draft. Pass `initial` to pre-populate for the
    /// "Edit Profile" flow — all 16 flags are copied out of the stored profile.
    init(apiClient: APIClientProtocol, initial: IdentityProfile? = nil) {
        self.apiClient = apiClient
        if let initial {
            self.request = IdentityProfileRequest(from: initial)
        }
    }

    // MARK: - Actions

    /// Persist the current draft to the backend. `saved` flips to true on success.
    func save() async {
        guard !isSaving else { return }
        isSaving = true
        defer { isSaving = false }

        do {
            _ = try await apiClient.updateIdentityProfile(request)
            error = nil
            saved = true
        } catch let apiError as APIError {
            error = apiError
            saved = false
        } catch {
            self.error = .unknown(0, error.localizedDescription)
            saved = false
        }
    }

    /// Semantically equivalent to `save()` with the current draft untouched.
    /// When invoked from the onboarding flow's "Skip" buttons, the draft is
    /// all-false by default, which persists a blank profile. This matches the
    /// prompt's "skip for now saves defaults" requirement.
    func skip() async {
        await save()
    }
}
