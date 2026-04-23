import Foundation
import Testing
@testable import Barkain

// MARK: - PortalCTADecodingTests (Step 3g-B)
//
// Locks the snake→camel mapping for `PortalCTA` and confirms the parent
// `StackedPath` decode stays backward-compatible when the optional
// `portal_ctas` field is absent (older v4-cached payloads).

@Suite("PortalCTA decoding")
struct PortalCTADecodingTests {

    private func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        // PortalCTA carries `last_verified` as ISO 8601; the production
        // APIClient decoder uses .custom with several fallbacks. .iso8601
        // covers the canonical format the backend writes.
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }

    @Test("Full PortalCTA shape decodes every field including disclosure")
    func test_portalCTA_fullShape() throws {
        let json = """
        {
            "portal_source": "rakuten",
            "display_name": "Rakuten",
            "mode": "signup_referral",
            "bonus_rate_percent": 3.5,
            "bonus_is_elevated": true,
            "cta_url": "https://www.rakuten.com/r/TEST",
            "cta_label": "Sign up for Rakuten — $50 bonus",
            "signup_promo_copy": "Get $50 when you spend $30 within 90 days",
            "last_verified": "2026-04-23T01:23:45Z",
            "disclosure_required": true
        }
        """.data(using: .utf8)!

        let cta = try makeDecoder().decode(PortalCTA.self, from: json)

        #expect(cta.portalSource == "rakuten")
        #expect(cta.mode == "signup_referral")
        #expect(cta.bonusRatePercent == 3.5)
        #expect(cta.bonusIsElevated == true)
        #expect(cta.disclosureRequired == true)
        #expect(cta.signupPromoCopy == "Get $50 when you spend $30 within 90 days")
        #expect(cta.lastVerified != nil)
        #expect(cta.id == "rakuten")  // Identifiable conformance
        #expect(cta.isSignupReferral == true)
        #expect(cta.isMemberDeeplink == false)
    }

    @Test("Minimal PortalCTA (member deeplink, no promo, no disclosure)")
    func test_portalCTA_memberDeeplinkMinimal() throws {
        let json = """
        {
            "portal_source": "befrugal",
            "display_name": "BeFrugal",
            "mode": "member_deeplink",
            "bonus_rate_percent": 2,
            "bonus_is_elevated": false,
            "cta_url": "https://www.befrugal.com/store/Amazon/",
            "cta_label": "Open BeFrugal for 2% back",
            "disclosure_required": false
        }
        """.data(using: .utf8)!

        let cta = try makeDecoder().decode(PortalCTA.self, from: json)

        #expect(cta.signupPromoCopy == nil)
        #expect(cta.lastVerified == nil)
        #expect(cta.disclosureRequired == false)
        #expect(cta.isMemberDeeplink == true)
    }

    @Test("StackedPath decodes cleanly when portal_ctas is absent (v4 payload)")
    func test_stackedPath_backwardCompatNoCTAs() throws {
        let json = """
        {
            "retailer_id": "amazon",
            "retailer_name": "Amazon",
            "base_price": 100.0,
            "final_price": 100.0,
            "effective_cost": 95.0,
            "total_savings": 5.0,
            "identity_savings": 0,
            "card_savings": 5.0,
            "card_source": "Chase Freedom Flex",
            "portal_savings": 0,
            "condition": "new"
        }
        """.data(using: .utf8)!

        let path = try makeDecoder().decode(StackedPath.self, from: json)

        #expect(path.portalCtas.isEmpty)
        #expect(path.cardSource == "Chase Freedom Flex")
    }

    @Test("StackedPath decodes a winner payload with embedded portal_ctas")
    func test_stackedPath_winnerPayloadWithCTAs() throws {
        // Mirror the wire shape M6 produces for a winner with 2 portal CTAs
        // sorted by bonus rate. Pre-formed JSON (not encoder roundtrip)
        // matches what the iOS decoder actually sees in production.
        let json = """
        {
            "retailer_id": "amazon",
            "retailer_name": "Amazon",
            "base_price": 100.0,
            "final_price": 100.0,
            "effective_cost": 95.0,
            "total_savings": 5.0,
            "identity_savings": 0,
            "card_savings": 5.0,
            "card_source": "Chase Freedom Flex",
            "portal_savings": 0,
            "portal_ctas": [
                {
                    "portal_source": "topcashback",
                    "display_name": "TopCashback",
                    "mode": "guided_only",
                    "bonus_rate_percent": 4.0,
                    "bonus_is_elevated": false,
                    "cta_url": "https://www.topcashback.com/",
                    "cta_label": "Open TopCashback first for 4% back",
                    "disclosure_required": false
                },
                {
                    "portal_source": "rakuten",
                    "display_name": "Rakuten",
                    "mode": "signup_referral",
                    "bonus_rate_percent": 1.0,
                    "bonus_is_elevated": false,
                    "cta_url": "https://www.rakuten.com/r/X",
                    "cta_label": "Sign up for Rakuten — $50 bonus",
                    "signup_promo_copy": "Get $50 when you spend $30 within 90 days",
                    "disclosure_required": true
                }
            ],
            "condition": "new"
        }
        """.data(using: .utf8)!

        let path = try makeDecoder().decode(StackedPath.self, from: json)

        #expect(path.portalCtas.count == 2)
        #expect(path.portalCtas.map(\.portalSource) == ["topcashback", "rakuten"])
        #expect(path.portalCtas[0].disclosureRequired == false)
        #expect(path.portalCtas[1].disclosureRequired == true)
        #expect(path.portalCtas[1].signupPromoCopy?.contains("$50") == true)
    }
}
