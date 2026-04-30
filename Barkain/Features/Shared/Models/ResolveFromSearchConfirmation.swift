import Foundation

// MARK: - demo-prep-1 Item 3 wire types
//
// Companion types to the backend's `/resolve-from-search/confirm`
// endpoint. The request mirrors `ResolveFromSearchConfirmRequest` in
// `backend/modules/m1_product/schemas.py`; the response mirrors
// `ConfirmResolutionResponse` on the same module. `.convertToSnakeCase`
// handles the camel-to-snake mapping on the wire.
//
// The outcome enum below is the iOS-side union of the two 200 response
// shapes `/resolve-from-search` can now produce:
//
//   - `loaded(Product)` — happy path; backend resolved successfully.
//   - `needsConfirmation(...)` — backend returned 409
//     RESOLUTION_NEEDS_CONFIRMATION; the caller presents the confirmation
//     sheet and then re-calls with the user's choice through
//     `/resolve-from-search/confirm`.

nonisolated struct ResolveFromSearchConfirmRequest: Codable, Sendable, Equatable {
    let deviceName: String
    let brand: String?
    let model: String?
    let userConfirmed: Bool
    let query: String?
    /// Search-row thumbnail forwarded so the confirmed-resolve persists
    /// the user-tapped image when no upstream resolver supplies one.
    let fallbackImageURL: String?

    init(
        deviceName: String,
        brand: String?,
        model: String?,
        userConfirmed: Bool,
        query: String?,
        fallbackImageURL: String? = nil
    ) {
        self.deviceName = deviceName
        self.brand = brand
        self.model = model
        self.userConfirmed = userConfirmed
        self.query = query
        self.fallbackImageURL = fallbackImageURL
    }
}

/// Response from `/resolve-from-search/confirm`. `product` is non-nil on
/// `user_confirmed=true`, nil on `user_confirmed=false`. `logged=true`
/// always — it's an acknowledgement bit the backend writes so the
/// client can trust telemetry landed.
nonisolated struct ConfirmResolutionResponse: Codable, Sendable, Equatable {
    let product: Product?
    let logged: Bool
}

/// Outcome of `APIClient.resolveProductFromSearch`. 409 lifts out of the
/// APIError space into an explicit state the caller handles as a first-
/// class branch instead of an error. Non-409 errors still throw — this
/// is a success-vs-needs-confirmation split, not an error taxonomy.
enum ResolveFromSearchOutcome: Sendable, Equatable {
    case loaded(Product)
    case needsConfirmation(candidate: LowConfidenceCandidate)
}

/// The specific row the user just tapped. Carries the same (device_name,
/// brand, model, confidence) tuple back to the confirmation sheet so the
/// sheet can show it as the primary candidate. Alternative candidates
/// come from the in-memory search-results list on the view-model side.
nonisolated struct LowConfidenceCandidate: Sendable, Equatable {
    let deviceName: String
    let brand: String?
    let model: String?
    let confidence: Double
    let threshold: Double
}
