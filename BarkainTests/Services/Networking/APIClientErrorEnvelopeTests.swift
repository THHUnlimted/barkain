import Foundation
import Testing
@testable import Barkain

// MARK: - APIClientErrorEnvelopeTests (cross-pack carry-forward from #63)
//
// Pins the FastAPI error-envelope contract that demo-prep-1 (#63) restored.
//
// The backend emits `{"detail": {"error": {"code, message, details}}}` —
// nested under `detail` — but iOS's `APIErrorResponse` was decoding `{"error":
// ...}` at the root. The mismatch silently dropped every backend `message` for
// ~6 months; iOS callers always saw "Unknown error" / "Unexpected error".
//
// `APIClient.decodeErrorDetail(body:decoder:)` unwraps the outer container
// first. This file regression-tests that contract so a future refactor can't
// silently re-break it.
//
// Caveat (known, not fixed in this pack): the production 409
// RESOLUTION_NEEDS_CONFIRMATION envelope ships heterogeneous `details`
// (floats + nulls — see `backend/modules/m1_product/router.py:130`). Today
// `APIErrorDetail.details: [String: String]?` cannot decode mixed types, so
// the whole envelope falls back through `decodeErrorDetail` and the iOS
// SearchViewModel synthesizes confidence/threshold defaults from local state
// (APIClient.swift:230). These tests use string-only details to pin what
// works today; widening `details` to a heterogeneous container is a separate
// follow-up if Mike wants the real server-side details to flow through.

private final class APIErrorEnvelopeBundleAnchor {}

@Suite("APIClient error envelope unwrap (FastAPI nested shape)")
struct APIClientErrorEnvelopeTests {

    // MARK: - Helpers

    private func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    private func loadCanonicalFixture() throws -> Data {
        let url = try #require(
            Bundle(for: APIErrorEnvelopeBundleAnchor.self)
                .url(forResource: "api_error_envelope", withExtension: "json")
        )
        return try Data(contentsOf: url)
    }

    private func envelopeData(code: String, message: String, details: String) -> Data {
        let json = """
        {
          "detail": {
            "error": {
              "code": "\(code)",
              "message": "\(message)",
              "details": \(details)
            }
          }
        }
        """
        return Data(json.utf8)
    }

    // MARK: - Tests

    @Test("Canonical envelope unwraps `error.code`")
    func test_canonicalEnvelope_yieldsCode() throws {
        let body = try loadCanonicalFixture()
        let detail = try #require(
            APIClient.decodeErrorDetail(body: body, decoder: makeDecoder())
        )
        #expect(detail.code == "RECOMMEND_INSUFFICIENT_DATA")
    }

    @Test("Canonical envelope surfaces real `error.message` (not the legacy fallback)")
    func test_canonicalEnvelope_yieldsRealMessage() throws {
        let body = try loadCanonicalFixture()
        let detail = try #require(
            APIClient.decodeErrorDetail(body: body, decoder: makeDecoder())
        )
        #expect(detail.message == "Not enough price data for recommendation")
        // The whole point of #63's fix: the message is the backend's string,
        // never "Unknown error" or "Unexpected error" from APIError fallbacks.
        #expect(detail.message != "Unknown error")
        #expect(detail.message != "Unexpected error")
    }

    @Test("404 PRODUCT_NOT_FOUND envelope decodes via the same path")
    func test_productNotFoundEnvelope_decodes() {
        let body = envelopeData(
            code: "PRODUCT_NOT_FOUND",
            message: "We couldn't find that product",
            details: #"{"upc": "000000000001"}"#
        )
        let detail = APIClient.decodeErrorDetail(body: body, decoder: makeDecoder())
        #expect(detail?.code == "PRODUCT_NOT_FOUND")
        #expect(detail?.message == "We couldn't find that product")
    }

    @Test("409 RESOLUTION_NEEDS_CONFIRMATION envelope decodes (string-only details)")
    func test_resolutionNeedsConfirmationEnvelope_decodes() {
        // String-only details mirror the contract `APIErrorDetail.details`
        // can decode today. Production 409s carry floats — see file header
        // caveat.
        let body = envelopeData(
            code: "RESOLUTION_NEEDS_CONFIRMATION",
            message: "Low-confidence match — user confirmation required",
            details: #"{"device_name": "shokz openrun", "brand": "Shokz"}"#
        )
        let detail = APIClient.decodeErrorDetail(body: body, decoder: makeDecoder())
        #expect(detail?.code == "RESOLUTION_NEEDS_CONFIRMATION")
        #expect(detail?.message == "Low-confidence match — user confirmation required")
    }
}
