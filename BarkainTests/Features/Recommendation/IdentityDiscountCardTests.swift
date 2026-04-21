import XCTest
@testable import Barkain

@MainActor
final class IdentityDiscountCardTests: XCTestCase {

    // MARK: - Helpers

    private func makeDiscount(
        verificationUrl: String? = nil,
        url: String? = nil,
        estimatedSavings: Double? = 100,
        scope: String? = nil,
        discountValue: Double? = 30,
        discountMaxValue: Double? = nil
    ) -> EligibleDiscount {
        EligibleDiscount(
            programId: UUID(),
            retailerId: "samsung_direct",
            retailerName: "Samsung",
            programName: "Military Discount",
            eligibilityType: "military",
            discountType: "percentage",
            discountValue: discountValue,
            discountMaxValue: discountMaxValue,
            discountDetails: "30% off",
            verificationMethod: "id_me",
            verificationUrl: verificationUrl,
            url: url,
            estimatedSavings: estimatedSavings,
            scope: scope
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

    // MARK: - BE-L9: scope-aware rendering

    func test_scopeBadge_nilForProduct() {
        let card = IdentityDiscountCard(
            discount: makeDiscount(scope: nil),
            onOpen: { _ in }
        )
        XCTAssertNil(card.scopeBadge)
    }

    func test_scopeBadge_showsMembershipFee() {
        let card = IdentityDiscountCard(
            discount: makeDiscount(scope: "membership_fee"),
            onOpen: { _ in }
        )
        XCTAssertEqual(card.scopeBadge, "Membership fee")
    }

    func test_scopeBadge_showsShipping() {
        let card = IdentityDiscountCard(
            discount: makeDiscount(scope: "shipping"),
            onOpen: { _ in }
        )
        XCTAssertEqual(card.scopeBadge, "Shipping only")
    }

    func test_savingsText_membershipFee_avoidsProductPhrasing() {
        // Prime Student: 50 % off the Prime fee, NOT the product. The card
        // must never render a dollar figure or "% off" that implies product
        // savings.
        let card = IdentityDiscountCard(
            discount: makeDiscount(
                estimatedSavings: nil,
                scope: "membership_fee",
                discountValue: 50
            ),
            onOpen: { _ in }
        )
        XCTAssertEqual(card.savingsText, "50% off fee")
    }

    func test_savingsText_shipping_rendersFreeShipping() {
        let card = IdentityDiscountCard(
            discount: makeDiscount(
                estimatedSavings: nil,
                scope: "shipping",
                discountValue: nil
            ),
            onOpen: { _ in }
        )
        XCTAssertEqual(card.savingsText, "Free shipping")
    }

    func test_savingsText_productScope_unchanged() {
        // Sanity: existing product-scope path still produces dollar savings.
        let card = IdentityDiscountCard(
            discount: makeDiscount(estimatedSavings: 250, scope: nil),
            onOpen: { _ in }
        )
        XCTAssertEqual(card.savingsText, "Save $250")
    }
}
