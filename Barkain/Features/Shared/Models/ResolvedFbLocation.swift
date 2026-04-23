import Foundation

// MARK: - ResolveFbLocationRequest

/// Body for `POST /api/v1/fb-location/resolve`. State must be a USPS
/// two-letter code; backend rejects anything else at 422. `nonisolated`
/// so `Endpoint.body` (which is nonisolated enum context) can call
/// `Encodable` on this without hopping actors.
nonisolated struct ResolveFbLocationRequest: Encodable, Sendable {
    let city: String
    let state: String
    var country: String = "US"
}

// MARK: - ResolvedFbLocation

/// Response from `POST /api/v1/fb-location/resolve`.
///
/// `locationId` is FB's numeric Marketplace Page ID as a string. Backend
/// emits it as a string (not an integer) because these are bigints and
/// round-tripping through `JSONDecoder` → `Int` silently narrows for IDs
/// above 2^53. Keep it as a string end to end; we only ever concatenate
/// it into a URL or cache key.
///
/// `canonicalName` is what FB actually calls this area — e.g. for input
/// "Ding Dong, TX" FB's Marketplace redirects to Killeen and we lift
/// "Killeen, TX" from the search-result snippet. When `nil` the resolver
/// couldn't pull a name from context (still usable, just no
/// cross-check). When it differs from the user's input the picker shows
/// a banner so they know which metro they'll see listings from.
///
/// `verified` is true when the resolver got a canonical name back from a
/// search result (belt-and-suspenders signal that the ID is real), false
/// for tombstone responses or partial matches.
///
/// `resolutionPath` is the API-stable enum
/// `{cache, live, seed, unresolved, throttled}`. The backend collapses
/// engine-specific internal values (`startpage` / `ddg` / `brave` /
/// `user`) to `live` so we can swap or add resolver engines server-side
/// without bumping this Codable shape. Used for debug logging only;
/// no UI branches on it.
nonisolated struct ResolvedFbLocation: Codable, Equatable, Sendable {
    let locationId: String?
    let canonicalName: String?
    let verified: Bool
    let resolutionPath: String
}
