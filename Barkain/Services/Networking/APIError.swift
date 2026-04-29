import Foundation

// MARK: - APIError

enum APIError: Error, Equatable, LocalizedError, Sendable {
    case network(URLError)
    case unauthorized
    /// 404 — product/UPC not found. Carries the backend's optional
    /// ``details["reasoning"]`` (cat-rel-1-L2-ux) when Gemini explained
    /// *why* it refused (multi-variant SKU, dealer-only stock, etc.) so
    /// iOS can surface it under the generic "couldn't find" copy.
    /// Existing `case .notFound:` patterns continue to match without
    /// changes since Swift allows ignoring associated values.
    case notFound(reason: String? = nil)
    case rateLimited
    case validation(String)
    case server(String)
    case decodingFailed(String)
    case unknown(Int, String)

    // MARK: - LocalizedError

    // savings-math-prominence Item 3: copy polish + backend error.message
    // audit. Engineer-tone strings replaced with friendly copy. Where a
    // backend `message` reaches here (validation/server/unknown), it's
    // surfaced directly — Item 3 also rewrote those source strings in
    // backend/modules/*/router.py so they read like product copy.

    var errorDescription: String? {
        switch self {
        case .network:
            return "Couldn't reach the server. Check your connection and try again."
        case .unauthorized:
            return "Please sign in again to continue."
        case .notFound(let reason):
            // cat-rel-1-L2-ux: when Gemini gave a reason, prefer it over
            // the generic copy. The reasoning is already user-readable
            // (Gemini phrases its "I refused because…" as a sentence).
            if let reason, !reason.isEmpty {
                return reason
            }
            return "Couldn't find this one."
        case .rateLimited:
            return "Too many requests in a row. Try again in a moment."
        case .validation(let message):
            return message
        case .server:
            return "Something went wrong on our end. Try again in a moment."
        case .decodingFailed:
            return "We got an unexpected response. Try again in a moment."
        case .unknown(_, let message):
            return message
        }
    }
}
