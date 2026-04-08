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

    var errorDescription: String? {
        switch self {
        case .network(let error):
            return "Network error: \(error.localizedDescription)"
        case .unauthorized:
            return "You are not authorized. Please sign in again."
        case .notFound:
            return "Product not found."
        case .rateLimited:
            return "Too many requests. Please try again in a moment."
        case .validation(let message):
            return "Invalid request: \(message)"
        case .server(let message):
            return "Server error: \(message)"
        case .decodingFailed(let message):
            return "Failed to read response: \(message)"
        case .unknown(let code, let message):
            return "Unexpected error (\(code)): \(message)"
        }
    }
}
