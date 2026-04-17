import Foundation

// MARK: - HTTP Method

nonisolated enum HTTPMethod: String {
    case get = "GET"
    case post = "POST"
    case put = "PUT"
    case delete = "DELETE"
}

// MARK: - Endpoint

nonisolated enum Endpoint {
    case resolveProduct(upc: String)
    case searchProducts(query: String, maxResults: Int)
    case getPrices(productId: UUID, forceRefresh: Bool = false)
    case streamPrices(productId: UUID, forceRefresh: Bool = false)
    case health
    case getIdentityProfile
    case updateIdentityProfile(IdentityProfileRequest)
    case getEligibleDiscounts(productId: UUID?)
    // Step 2e — Card portfolio
    case getCardCatalog
    case getUserCards
    case addCard(AddCardRequest)
    case removeCard(userCardId: UUID)
    case setPreferredCard(userCardId: UUID)
    case setCardCategories(userCardId: UUID, SetCategoriesRequest)
    case getCardRecommendations(productId: UUID)
    // Step 2f — Billing
    case getBillingStatus
    // Step 2g — Affiliate
    case getAffiliateURL(AffiliateClickRequest)
    case getAffiliateStats

    // MARK: - Properties

    var path: String {
        switch self {
        case .resolveProduct:
            return "/api/v1/products/resolve"
        case .searchProducts:
            return "/api/v1/products/search"
        case .getPrices(let productId, _):
            return "/api/v1/prices/\(productId.uuidString)"
        case .streamPrices(let productId, _):
            return "/api/v1/prices/\(productId.uuidString)/stream"
        case .health:
            return "/api/v1/health"
        case .getIdentityProfile, .updateIdentityProfile:
            return "/api/v1/identity/profile"
        case .getEligibleDiscounts:
            return "/api/v1/identity/discounts"
        case .getCardCatalog:
            return "/api/v1/cards/catalog"
        case .getUserCards, .addCard:
            return "/api/v1/cards/my-cards"
        case .removeCard(let id):
            return "/api/v1/cards/my-cards/\(id.uuidString)"
        case .setPreferredCard(let id):
            return "/api/v1/cards/my-cards/\(id.uuidString)/preferred"
        case .setCardCategories(let id, _):
            return "/api/v1/cards/my-cards/\(id.uuidString)/categories"
        case .getCardRecommendations:
            return "/api/v1/cards/recommendations"
        case .getBillingStatus:
            return "/api/v1/billing/status"
        case .getAffiliateURL:
            return "/api/v1/affiliate/click"
        case .getAffiliateStats:
            return "/api/v1/affiliate/stats"
        }
    }

    var method: HTTPMethod {
        switch self {
        case .resolveProduct, .searchProducts, .updateIdentityProfile, .addCard,
             .setCardCategories, .getAffiliateURL:
            return .post
        case .setPreferredCard:
            return .put
        case .removeCard:
            return .delete
        case .getPrices, .streamPrices, .health, .getIdentityProfile,
             .getEligibleDiscounts, .getCardCatalog, .getUserCards,
             .getCardRecommendations, .getBillingStatus, .getAffiliateStats:
            return .get
        }
    }

    var queryItems: [URLQueryItem]? {
        switch self {
        case .getPrices(_, true), .streamPrices(_, true):
            return [URLQueryItem(name: "force_refresh", value: "true")]
        case .getEligibleDiscounts(let productId):
            if let productId {
                return [URLQueryItem(name: "product_id", value: productId.uuidString)]
            }
            return nil
        case .getCardRecommendations(let productId):
            return [URLQueryItem(name: "product_id", value: productId.uuidString)]
        default:
            return nil
        }
    }

    var body: Data? {
        switch self {
        case .resolveProduct(let upc):
            return try? JSONEncoder().encode(["upc": upc])
        case .searchProducts(let query, let maxResults):
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            struct Body: Encodable {
                let query: String
                let maxResults: Int
            }
            return try? encoder.encode(Body(query: query, maxResults: maxResults))
        case .updateIdentityProfile(let request):
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            return try? encoder.encode(request)
        case .addCard(let request):
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            return try? encoder.encode(request)
        case .setCardCategories(_, let request):
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            return try? encoder.encode(request)
        case .getAffiliateURL(let request):
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            return try? encoder.encode(request)
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
