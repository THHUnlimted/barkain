import Foundation

// MARK: - APIClientProtocol

protocol APIClientProtocol: Sendable {
    func resolveProduct(upc: String) async throws -> Product
    func getPrices(productId: UUID, forceRefresh: Bool) async throws -> PriceComparison
}

// MARK: - APIClient

nonisolated final class APIClient: APIClientProtocol, @unchecked Sendable {

    // MARK: - Properties

    private let session: URLSession
    private let baseURL: URL
    private let decoder: JSONDecoder

    // MARK: - Init

    init(
        session: URLSession? = nil,
        baseURL: URL = AppConfig.apiBaseURL
    ) {
        // Live price aggregation can take 90-120s end-to-end (Best Buy container
        // is the slow leg). URLSession.shared defaults to 60s which trips the
        // iPhone before the backend finishes, so we build a dedicated session
        // with a 240s request timeout and a 300s resource ceiling.
        if let session {
            self.session = session
        } else {
            let config = URLSessionConfiguration.default
            config.timeoutIntervalForRequest = 240
            config.timeoutIntervalForResource = 300
            self.session = URLSession(configuration: config)
        }
        self.baseURL = baseURL

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let dateString = try container.decode(String.self)

            // Try ISO 8601 with fractional seconds first
            let isoFormatter = ISO8601DateFormatter()
            isoFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = isoFormatter.date(from: dateString) {
                return date
            }

            // Fallback: ISO 8601 without fractional seconds
            isoFormatter.formatOptions = [.withInternetDateTime]
            if let date = isoFormatter.date(from: dateString) {
                return date
            }

            // Fallback: Python's isoformat without timezone (2026-04-08T01:23:45.678901)
            let fallback = DateFormatter()
            fallback.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"
            fallback.locale = Locale(identifier: "en_US_POSIX")
            if let date = fallback.date(from: dateString) {
                return date
            }

            fallback.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
            if let date = fallback.date(from: dateString) {
                return date
            }

            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Cannot decode date: \(dateString)"
            )
        }
        self.decoder = decoder
    }

    // MARK: - APIClientProtocol

    func resolveProduct(upc: String) async throws -> Product {
        try await request(endpoint: .resolveProduct(upc: upc))
    }

    func getPrices(productId: UUID, forceRefresh: Bool = false) async throws -> PriceComparison {
        try await request(endpoint: .getPrices(productId: productId, forceRefresh: forceRefresh))
    }

    // MARK: - Private

    private func request<T: Decodable>(endpoint: Endpoint) async throws -> T {
        let url = endpoint.url(base: baseURL)
        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = endpoint.method.rawValue
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")

        // Stub auth — Clerk SDK integration in Phase 2
        // urlRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")

        if let body = endpoint.body {
            urlRequest.httpBody = body
        }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: urlRequest)
        } catch let urlError as URLError {
            throw APIError.network(urlError)
        }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.unknown(0, "Invalid response type")
        }

        switch httpResponse.statusCode {
        case 200..<300:
            do {
                return try decoder.decode(T.self, from: data)
            } catch {
                throw APIError.decodingFailed(error.localizedDescription)
            }

        case 401:
            throw APIError.unauthorized

        case 404:
            throw APIError.notFound

        case 422:
            if let errorResponse = try? decoder.decode(APIErrorResponse.self, from: data) {
                throw APIError.validation(errorResponse.error.message)
            }
            throw APIError.validation("Validation failed")

        case 429:
            throw APIError.rateLimited

        case 500...599:
            if let errorResponse = try? decoder.decode(APIErrorResponse.self, from: data) {
                throw APIError.server(errorResponse.error.message)
            }
            throw APIError.server("Internal server error")

        default:
            if let errorResponse = try? decoder.decode(APIErrorResponse.self, from: data) {
                throw APIError.unknown(httpResponse.statusCode, errorResponse.error.message)
            }
            throw APIError.unknown(httpResponse.statusCode, "Unexpected error")
        }
    }
}
