import XCTest
@testable import Barkain

@MainActor
final class IdentityDiscountCardTests: XCTestCase {

    // MARK: - Helpers

    private func makeDiscount(
        verificationUrl: String? = nil,
        url: String? = nil
    ) -> EligibleDiscount {
        EligibleDiscount(
            programId: UUID(),
            retailerId: "samsung_direct",
            retailerName: "Samsung",
            programName: "Military Discount",
            eligibilityType: "military",
            discountType: "percentage",
            discountValue: 30,
            discountMaxValue: nil,
            discountDetails: "30% off",
            verificationMethod: "id_me",
            verificationUrl: verificationUrl,
            url: url,
            estimatedSavings: 100
        )
    }

    // MARK: - Step 2g: resolvedURL selection

    func test_resolvedURL_prefersVerificationURL() {
        // Given — a discount carries BOTH verificationUrl and a fallback url.
        let card = IdentityDiscountCard(
            discount: makeDiscount(
                verificationUrl: "https://id.me/verify",
                url: "https://samsung.com/military"
            ),
            onOpen: { _ in }
        )

        // Then — verification URL wins.
        XCTAssertEqual(
            card.resolvedURL?.absoluteString,
            "https://id.me/verify"
        )
    }

    func test_resolvedURL_fallsBackToURLWhenVerificationMissing() {
        // Given — no verificationUrl; only the brand URL.
        let card = IdentityDiscountCard(
            discount: makeDiscount(
                verificationUrl: nil,
                url: "https://samsung.com/military"
            ),
            onOpen: { _ in }
        )

        // Then — the fallback URL is used.
        XCTAssertEqual(
            card.resolvedURL?.absoluteString,
            "https://samsung.com/military"
        )
    }

    func test_resolvedURL_returnsNilWhenBothMissing() {
        // Given — neither URL provided.
        let card = IdentityDiscountCard(
            discount: makeDiscount(verificationUrl: nil, url: nil),
            onOpen: { _ in }
        )

        // Then — no URL to open.
        XCTAssertNil(card.resolvedURL)
    }
}
