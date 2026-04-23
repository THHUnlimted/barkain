import Foundation

// MARK: - PortalCTA (Step 3g-B)
//
// Mirrors `backend/modules/m13_portal/schemas.py::PortalCTA`. Snake-case
// decoding handled by `APIClient.decoder.keyDecodingStrategy =
// .convertFromSnakeCase` so no CodingKeys needed. `lastVerified` decodes
// via the custom date strategy that already handles ISO 8601 + Python
// isoformat fallback (see APIClient init).
//
// `mode` is intentionally a String (not a Swift enum) so an unknown value
// from a forward-rolled backend doesn't fail the whole Recommendation
// decode — iOS treats unknowns as guided_only at the rendering layer
// (lowest-information mode → safest fallback).

nonisolated struct PortalCTA: Codable, Equatable, Sendable, Identifiable, Hashable {
    let portalSource: String
    let displayName: String
    let mode: String              // "member_deeplink" | "signup_referral" | "guided_only"
    let bonusRatePercent: Double
    let bonusIsElevated: Bool
    let ctaUrl: String
    let ctaLabel: String
    let signupPromoCopy: String?
    let lastVerified: Date?
    let disclosureRequired: Bool

    var id: String { portalSource }

    // MARK: - Convenience

    /// True for SIGNUP_REFERRAL — drives the FTC disclosure caption.
    var isSignupReferral: Bool { mode == "signup_referral" }

    /// True for MEMBER_DEEPLINK — bolds the row in the interstitial.
    var isMemberDeeplink: Bool { mode == "member_deeplink" }
}
