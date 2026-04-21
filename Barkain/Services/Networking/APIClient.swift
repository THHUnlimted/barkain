import Foundation
import os

// MARK: - Logger

private let sseLog = Logger(subsystem: "com.barkain.app", category: "SSE")

// MARK: - APIClientProtocol

protocol APIClientProtocol: Sendable {
    func resolveProduct(upc: String) async throws -> Product
    func resolveProductFromSearch(deviceName: String, brand: String?, model: String?) async throws -> Product
    func searchProducts(query: String, maxResults: Int, forceGemini: Bool) async throws -> ProductSearchResponse
    func getPrices(productId: UUID, forceRefresh: Bool) async throws -> PriceComparison
    func streamPrices(productId: UUID, forceRefresh: Bool, queryOverride: String?) -> AsyncThrowingStream<RetailerStreamEvent, Error>
    func getIdentityProfile() async throws -> IdentityProfile
    func updateIdentityProfile(_ request: IdentityProfileRequest) async throws -> IdentityProfile
    func getEligibleDiscounts(productId: UUID?) async throws -> IdentityDiscountsResponse
    // Step 2e — Card portfolio
    func getCardCatalog() async throws -> [CardRewardProgram]
    func getUserCards() async throws -> [UserCardSummary]
    func addCard(_ request: AddCardRequest) async throws -> UserCardSummary
    func removeCard(userCardId: UUID) async throws
    func setPreferredCard(userCardId: UUID) async throws -> UserCardSummary
    func setCardCategories(userCardId: UUID, request: SetCategoriesRequest) async throws
    func getCardRecommendations(productId: UUID) async throws -> CardRecommendationsResponse
    // Step 2f — Billing
    func getBillingStatus() async throws -> BillingStatus
    // Step 2g — Affiliate
    func getAffiliateURL(
        productId: UUID?,
        retailerId: String,
        productURL: String
    ) async throws -> AffiliateURLResponse
    func getAffiliateStats() async throws -> AffiliateStatsResponse
    // Step 3e — Deterministic Recommendation Engine
    func fetchRecommendation(
        productId: UUID,
        forceRefresh: Bool
    ) async throws -> Recommendation?
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

    func resolveProductFromSearch(
        deviceName: String,
        brand: String? = nil,
        model: String? = nil
    ) async throws -> Product {
        try await request(
            endpoint: .resolveFromSearch(deviceName: deviceName, brand: brand, model: model)
        )
    }

    func searchProducts(query: String, maxResults: Int = 10, forceGemini: Bool = false) async throws -> ProductSearchResponse {
        try await request(endpoint: .searchProducts(query: query, maxResults: maxResults, forceGemini: forceGemini))
    }

    func getPrices(productId: UUID, forceRefresh: Bool = false) async throws -> PriceComparison {
        try await request(endpoint: .getPrices(productId: productId, forceRefresh: forceRefresh))
    }

    // MARK: - Identity (Step 2d)

    func getIdentityProfile() async throws -> IdentityProfile {
        try await request(endpoint: .getIdentityProfile)
    }

    func updateIdentityProfile(_ request: IdentityProfileRequest) async throws -> IdentityProfile {
        try await self.request(endpoint: .updateIdentityProfile(request))
    }

    func getEligibleDiscounts(productId: UUID?) async throws -> IdentityDiscountsResponse {
        try await request(endpoint: .getEligibleDiscounts(productId: productId))
    }

    // MARK: - Cards (Step 2e)

    func getCardCatalog() async throws -> [CardRewardProgram] {
        try await request(endpoint: .getCardCatalog)
    }

    func getUserCards() async throws -> [UserCardSummary] {
        try await request(endpoint: .getUserCards)
    }

    func addCard(_ request: AddCardRequest) async throws -> UserCardSummary {
        try await self.request(endpoint: .addCard(request))
    }

    func removeCard(userCardId: UUID) async throws {
        try await requestVoid(endpoint: .removeCard(userCardId: userCardId))
    }

    func setPreferredCard(userCardId: UUID) async throws -> UserCardSummary {
        try await request(endpoint: .setPreferredCard(userCardId: userCardId))
    }

    func setCardCategories(userCardId: UUID, request: SetCategoriesRequest) async throws {
        try await requestVoid(
            endpoint: .setCardCategories(userCardId: userCardId, request)
        )
    }

    func getCardRecommendations(productId: UUID) async throws -> CardRecommendationsResponse {
        try await request(endpoint: .getCardRecommendations(productId: productId))
    }

    // MARK: - Billing (Step 2f)

    func getBillingStatus() async throws -> BillingStatus {
        try await request(endpoint: .getBillingStatus)
    }

    // MARK: - Affiliate (Step 2g)

    func getAffiliateURL(
        productId: UUID?,
        retailerId: String,
        productURL: String
    ) async throws -> AffiliateURLResponse {
        let clickRequest = AffiliateClickRequest(
            productId: productId,
            retailerId: retailerId,
            productUrl: productURL
        )
        return try await request(endpoint: .getAffiliateURL(clickRequest))
    }

    func getAffiliateStats() async throws -> AffiliateStatsResponse {
        try await request(endpoint: .getAffiliateStats)
    }

    // MARK: - Recommendation (Step 3e)

    /// Deterministic recommendation post-close. Returns `nil` when the
    /// backend reports 422 `RECOMMEND_INSUFFICIENT_DATA` — the iOS caller
    /// interprets that as "not enough prices to say anything meaningful"
    /// and silently leaves the hero unrendered. All other errors propagate.
    func fetchRecommendation(
        productId: UUID,
        forceRefresh: Bool = false
    ) async throws -> Recommendation? {
        let body = RecommendationRequest(productId: productId, forceRefresh: forceRefresh)
        do {
            return try await request(endpoint: .getRecommendation(body)) as Recommendation
        } catch APIError.validation {
            return nil
        }
    }

    // MARK: - Streaming (Step 2c)

    func streamPrices(
        productId: UUID,
        forceRefresh: Bool = false,
        queryOverride: String? = nil
    ) -> AsyncThrowingStream<RetailerStreamEvent, Error> {
        // Capture the parts the background Task needs up-front — `self` is
        // @unchecked Sendable but the closure body only needs these immutables.
        let session = self.session
        let baseURL = self.baseURL
        let decoder = self.decoder

        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let url = Endpoint.streamPrices(
                        productId: productId,
                        forceRefresh: forceRefresh,
                        queryOverride: queryOverride
                    ).url(base: baseURL)
                    var urlRequest = URLRequest(url: url)
                    urlRequest.httpMethod = "GET"
                    urlRequest.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                    urlRequest.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
                    // Bearer token placeholder — Clerk SDK integration in Phase 2.

                    sseLog.debug("SSE stream opening for product \(productId.uuidString, privacy: .public) forceRefresh=\(forceRefresh, privacy: .public)")
                    let (bytes, response) = try await session.bytes(for: urlRequest)

                    guard let httpResponse = response as? HTTPURLResponse else {
                        sseLog.error("SSE stream: invalid response type")
                        throw APIError.unknown(0, "Invalid response type")
                    }
                    sseLog.debug("SSE stream opened HTTP \(httpResponse.statusCode, privacy: .public)")

                    guard (200..<300).contains(httpResponse.statusCode) else {
                        // Drain error body for decoding — status-code mapping mirrors request<T>().
                        var body = Data()
                        for try await byte in bytes {
                            body.append(byte)
                            if body.count > 8_192 { break }
                        }
                        throw Self.apiErrorFor(statusCode: httpResponse.statusCode, body: body, decoder: decoder)
                    }

                    for try await sseEvent in SSEParser.events(from: bytes) {
                        sseLog.info("SSE parsed event: \(sseEvent.event ?? "nil", privacy: .public) dataLen=\(sseEvent.data.count, privacy: .public)")
                        guard let data = sseEvent.data.data(using: .utf8) else {
                            sseLog.error("SSE event data utf8 conversion failed")
                            continue
                        }
                        let streamEvent: RetailerStreamEvent
                        do {
                            switch sseEvent.event {
                            case "retailer_result":
                                let update = try decoder.decode(RetailerResultUpdate.self, from: data)
                                streamEvent = .retailerResult(update)
                            case "done":
                                let summary = try decoder.decode(StreamSummary.self, from: data)
                                streamEvent = .done(summary)
                            case "error":
                                let err = try decoder.decode(StreamError.self, from: data)
                                streamEvent = .error(err)
                            default:
                                sseLog.debug("SSE event unknown type: \(sseEvent.event ?? "nil", privacy: .public)")
                                continue
                            }
                        } catch let decodeError {
                            sseLog.error("SSE decode failed for event=\(sseEvent.event ?? "nil", privacy: .public) error=\(decodeError.localizedDescription, privacy: .public) payload=\(sseEvent.data, privacy: .public)")
                            throw decodeError
                        }
                        sseLog.info("SSE decoded: \(String(describing: streamEvent), privacy: .public)")
                        continuation.yield(streamEvent)
                    }
                    sseLog.info("SSE stream ended normally")
                    continuation.finish()
                } catch let apiError as APIError {
                    sseLog.error("SSE stream APIError: \(apiError.localizedDescription, privacy: .public)")
                    continuation.finish(throwing: apiError)
                } catch let urlError as URLError {
                    sseLog.error("SSE stream URLError code=\(urlError.code.rawValue, privacy: .public): \(urlError.localizedDescription, privacy: .public)")
                    continuation.finish(throwing: APIError.network(urlError))
                } catch let decodingError as DecodingError {
                    sseLog.error("SSE stream DecodingError: \(decodingError.localizedDescription, privacy: .public)")
                    continuation.finish(throwing: APIError.decodingFailed(decodingError.localizedDescription))
                } catch {
                    sseLog.error("SSE stream unknown error (\(String(describing: type(of: error)), privacy: .public)): \(error.localizedDescription, privacy: .public)")
                    continuation.finish(throwing: APIError.unknown(0, error.localizedDescription))
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    private static func apiErrorFor(
        statusCode: Int,
        body: Data,
        decoder: JSONDecoder
    ) -> APIError {
        switch statusCode {
        case 401:
            return .unauthorized
        case 404:
            return .notFound
        case 422:
            if let resp = try? decoder.decode(APIErrorResponse.self, from: body) {
                return .validation(resp.error.message)
            }
            return .validation("Validation failed")
        case 429:
            return .rateLimited
        case 500...599:
            if let resp = try? decoder.decode(APIErrorResponse.self, from: body) {
                return .server(resp.error.message)
            }
            return .server("Internal server error")
        default:
            if let resp = try? decoder.decode(APIErrorResponse.self, from: body) {
                return .unknown(statusCode, resp.error.message)
            }
            return .unknown(statusCode, "Unexpected error")
        }
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

    /// Fire-and-forget variant for endpoints that return 204 or `{"ok": true}`.
    /// Shares the same error-mapping path as `request<T>` but discards the body.
    private func requestVoid(endpoint: Endpoint) async throws {
        let url = endpoint.url(base: baseURL)
        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = endpoint.method.rawValue
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
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
            return
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
