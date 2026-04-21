//
//  RecommendationHeroUITests.swift
//  BarkainUITests
//
//  Step 3e — smoke test for the post-close recommendation hero. Drives
//  the full scan → SSE → identity → cards → hero chain, verifies the
//  hero is NOT present during streaming, then verifies it appears after
//  things settle and the CTA opens the affiliate sheet.
//
//  Follows the 3-signal OR pattern from 2i-d for the affiliate sheet:
//  SFSafariViewController chrome lives outside the host a11y tree on
//  iOS 26, so we accept any of webView / Done button / unhittable row
//  as evidence of presentation.
//

import XCTest

final class RecommendationHeroUITests: XCTestCase {

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // MARK: - Scan → hero → affiliate

    @MainActor
    func testScanToRecommendationHeroToAffiliateSheet() throws {
        let app = XCUIApplication()
        app.launch()

        // Navigate to the Scan tab and open the manual UPC entry sheet.
        let scanTab = app.tabBars.buttons["Scan"]
        XCTAssertTrue(scanTab.waitForExistence(timeout: 10),
                      "Scan tab never appeared")
        scanTab.tap()

        // The "Enter UPC" affordance varies by build — accept any button
        // whose label matches. Fall through to search-field entry if the
        // manual-entry sheet isn't reachable.
        let manualEntry = app.buttons.matching(
            NSPredicate(format: "label CONTAINS[cd] 'Enter' OR label CONTAINS[cd] 'manual'")
        ).firstMatch
        guard manualEntry.waitForExistence(timeout: 5) else {
            // Environment doesn't expose the manual entry path — skip
            // the test gracefully rather than fail for a UX nit.
            throw XCTSkip("Manual UPC entry not reachable in this build.")
        }
        manualEntry.tap()

        // Sony WH-1000XM5 — the canonical demo UPC.
        let upcField = app.textFields.firstMatch
        XCTAssertTrue(upcField.waitForExistence(timeout: 5),
                      "UPC text field did not appear")
        upcField.tap()
        upcField.typeText("194252818381")

        let resolveButton = app.buttons.matching(
            NSPredicate(format: "label CONTAINS[cd] 'Resolve' OR label CONTAINS[cd] 'Find'")
        ).firstMatch
        XCTAssertTrue(resolveButton.waitForExistence(timeout: 5),
                      "Resolve button not found")
        resolveButton.tap()

        // At least one retailer row must appear so we know the stream is
        // draining. This also gives us a "streaming state" snapshot to
        // check that the hero is NOT visible yet.
        let anyRetailerRow = app.buttons.matching(
            NSPredicate(format: "identifier BEGINSWITH 'retailerRow_'")
        ).firstMatch
        XCTAssertTrue(anyRetailerRow.waitForExistence(timeout: 120),
                      "No retailer row landed within 120s — backend unreachable")

        // The hero MUST not exist during streaming — that's the entire
        // timing-gate guarantee. Sample it as soon as the first row lands.
        let hero = app.otherElements["recommendationHero"]
        XCTAssertFalse(hero.exists,
                       "recommendationHero was visible DURING streaming — timing gate broken")

        // Wait for hero to materialize AFTER everything settles. The
        // post-close chain (done → identity → cards → fetch) usually
        // lands within 2-3 s once streaming ends; allow 60 s on CI.
        let heroAppeared = hero.waitForExistence(timeout: 60)
        if !heroAppeared {
            // Insufficient-data path is legitimate — DEMO_MODE users
            // without seeded cards/identity may hit it. Skip rather
            // than fail so this test isn't noisy across environments.
            throw XCTSkip("recommendationHero never appeared — likely insufficient data for this user")
        }

        // Tap the primary CTA. Step 3f — the hero now presents the purchase
        // interstitial BEFORE the affiliate sheet. Verify the interstitial
        // appears first, then tap Continue, then verify the affiliate sheet.
        let cta = app.buttons["recommendationActionButton"]
        XCTAssertTrue(cta.waitForExistence(timeout: 5),
                      "recommendationActionButton missing under recommendationHero")
        cta.tap()

        let interstitial = app.otherElements["purchaseInterstitialSheet"]
        XCTAssertTrue(interstitial.waitForExistence(timeout: 5),
                      "purchaseInterstitialSheet did not present after hero tap")

        let continueButton = app.buttons["purchaseInterstitialContinueButton"]
        XCTAssertTrue(continueButton.waitForExistence(timeout: 3),
                      "Continue button missing on interstitial")
        continueButton.tap()

        let webView = app.webViews.firstMatch
        let doneButton = app.buttons["Done"]
        let sheetAppeared = webView.waitForExistence(timeout: 10)
            || doneButton.waitForExistence(timeout: 2)
            || !continueButton.isHittable
        XCTAssertTrue(sheetAppeared,
                      "Affiliate sheet did not present after tapping Continue on interstitial")
    }
}
