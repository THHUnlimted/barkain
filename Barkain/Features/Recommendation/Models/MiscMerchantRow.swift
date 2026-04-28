import Foundation

// MARK: - MiscMerchantRow (Step 3n)
//
// Wire shape from `GET /api/v1/misc/{product_id}`. Backend
// `m14_misc_retailer` caps the array at 3 rows server-side; we cap a
// second time iOS-side in `MiscRetailerCard` because defense-in-depth
// is cheap and a backend bug shouldn't blow up the layout.
//
// Snake-case Codable pitfall: `JSONDecoder.keyDecodingStrategy =
// .convertFromSnakeCase` lowercases the FIRST letter of each
// underscore-separated segment, so `source_normalized` becomes
// `sourceNormalized`, `price_cents` becomes `priceCents`, and
// `product_id` becomes `productId`. The CLAUDE.md reference for the
// PortalCTA "lowercase as" trap doesn't apply here — none of these
// fields contain capital-letter abbreviations — but the principle does:
// match what `.convertFromSnakeCase` produces, not what looks right.

struct MiscMerchantRow: Codable, Identifiable, Hashable, Sendable {

    // MARK: - Properties

    let title: String
    /// Display name as Serper provided it: "Chewy", "Pet Supplies Plus".
    let source: String
    /// Lowercase, whitespace-collapsed form. Backend uses this for the
    /// `KNOWN_RETAILER_DOMAINS` filter; iOS preserves it so views can
    /// group/filter without re-deriving.
    let sourceNormalized: String
    /// Google Shopping product page URL (NOT a direct merchant URL).
    /// Tap-through opens it in `SFSafariViewController`; Google handles
    /// the merchant redirect.
    let link: URL
    /// Raw price string from Serper, kept for display fidelity:
    /// "$20.98", "$1,049.00", "Free shipping".
    let price: String
    /// Parsed cents value for sorting. `nil` when the raw string was
    /// unparseable (sorts last via the comparator below).
    let priceCents: Int?
    let rating: Double?
    let ratingCount: Int?
    /// Google Shopping product id. Stable across calls for the same
    /// product on the same merchant.
    let productId: String?
    /// Serper's rank within the response. The service has already
    /// sorted by this value, but we keep it for telemetry / debugging.
    let position: Int

    // MARK: - Identifiable

    /// Stable identity for List/ForEach diffing. We pair `source` with
    /// `position` (and `productId` when available) because the same
    /// merchant can appear twice for variant SKUs.
    var id: String {
        "\(source)-\(position)-\(productId ?? "")"
    }
}
