import Foundation

// MARK: - MockURLProtocol

final class MockURLProtocol: URLProtocol, @unchecked Sendable {

    // MARK: - Static Configuration

    nonisolated(unsafe) static var mockResponses: [String: (data: Data, statusCode: Int)] = [:]

    static func reset() {
        mockResponses = [:]
    }

    // MARK: - URLProtocol

    override class func canInit(with request: URLRequest) -> Bool {
        true
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        guard let url = request.url else {
            client?.urlProtocol(self, didFailWithError: URLError(.badURL))
            return
        }

        let key = url.path
        if let mock = MockURLProtocol.mockResponses[key] {
            let response = HTTPURLResponse(
                url: url,
                statusCode: mock.statusCode,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: mock.data)
        } else {
            let response = HTTPURLResponse(
                url: url,
                statusCode: 404,
                httpVersion: nil,
                headerFields: nil
            )!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: Data())
        }

        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
