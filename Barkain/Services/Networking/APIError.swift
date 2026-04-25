import Foundation

// MARK: - APIError

enum APIError: Error, Equatable, LocalizedError, Sendable {
    case network(URLError)
    case unauthorized
    case notFound
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
        case .notFound:
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
