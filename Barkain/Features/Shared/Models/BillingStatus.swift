import Foundation

// MARK: - BillingStatus
//
// Server-authoritative subscription status from GET /api/v1/billing/status.
// Used for reconciliation against the RevenueCat SDK's local view (see
// `SubscriptionService`). The iOS UI always gates on the SDK for offline /
// instant-update reasons — this model exists so a Profile screen can show
// what the *backend* sees and surface any drift.
//
// Decoded via `APIClient.request` which uses `.convertFromSnakeCase`, so
// `expires_at` → `expiresAt` etc. happens automatically; no CodingKeys needed.

struct BillingStatus: Decodable, Equatable, Sendable {
    let tier: String
    let expiresAt: Date?
    let isActive: Bool
    let entitlementId: String?
}
