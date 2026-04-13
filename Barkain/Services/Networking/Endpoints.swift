import Foundation

// MARK: - HTTP Method

nonisolated enum HTTPMethod: String {
    case get = "GET"
    case post = "POST"
}

// MARK: - Endpoint

nonisolated enum Endpoint {
    case resolveProduct(upc: String)
    case getPrices(productId: UUID, forceRefresh: Bool = false)
    case streamPrices(productId: UUID, forceRefresh: Bool = false)
    case health

    // MARK: - Properties

    var path: String {
        switch self {
        case .resolveProduct:
            return "/api/v1/products/resolve"
        case .getPrices(let productId, _):
            return "/api/v1/prices/\(productId.uuidString)"
        case .streamPrices(let productId, _):
            return "/api/v1/prices/\(productId.uuidString)/stream"
        case .health:
            return "/api/v1/health"
        }
    }

    var method: HTTPMethod {
        switch self {
        case .resolveProduct:
            return .post
        case .getPrices, .streamPrices, .health:
            return .get
        }
    }

    var queryItems: [URLQueryItem]? {
        switch self {
        case .getPrices(_, true), .streamPrices(_, true):
            return [URLQueryItem(name: "force_refresh", value: "true")]
        default:
            return nil
        }
    }

    var body: Data? {
        switch self {
        case .resolveProduct(let upc):
            return try? JSONEncoder().encode(["upc": upc])
        default:
            return nil
        }
    }

    // MARK: - URL Builder

    func url(base: URL) -> URL {
        var components = URLComponents(url: base.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        components.queryItems = queryItems
        return components.url!
    }
}
