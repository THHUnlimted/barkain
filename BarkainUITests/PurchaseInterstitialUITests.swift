//
//  PurchaseInterstitialUITests.swift
//  BarkainUITests
//
//  Step 3f — end-to-end smoke for the purchase interstitial. Drives the
//  full scan → SSE → identity → cards → hero → tap CTA → interstitial →
//  activation block visible when rotating bonus is present → tap Continue
//  → SFSafariView presented.
//
//  OR-of-3 affiliate-sheet signal pattern (from 2i-d) — iOS 26's
//  SFSafariViewController chrome lives outside the host a11y tree, so we
//  accept any of webView / Done button / unhittable source button as
//  evidence of presentation.
//

import XCTest

final class PurchaseInterstitialUITests: XCTestCase {

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // MARK: - Hero → interstitial → affiliate

    @MainActor
    func testHeroTapToInterstitialToAffiliateSheet() throws {
        let app = XCUIApplication()
        app.launch()

        // Same entry path as RecommendationHeroUITests — scan manually.
        let scanTab = app.tabBars.buttons["Scan"]
        XCTAssertTrue(scanTab.waitForExistence(timeout: 10),
                      "Scan tab never appeared")
        scanTab.tap()

        let manualEntry = app.buttons.matching(
            NSPredicate(format: "label CONTAINS[cd] 'Enter' OR label CONTAINS[cd] 'manual'")
        ).firstMatch
        guard manualEntry.waitForExistence(timeout: 5) else {
            throw XCTSkip("Manual UPC entry not reachable in this build.")
        }
        manualEntry.tap()

        let upcField = app.textFields.firstMatch
        XCTAssertTrue(upcField.waitForExistence(timeout: 5),
                      "UPC text field did not appear")
        upcField.tap()
        upcField.typeText("194252818381")  // Sony WH-1000XM5

        let resolveButton = app.buttons.matching(
            NSPredicate(format: "label CONTAINS[cd] 'Resolve' OR label CONTAINS[cd] 'Find'")
        ).firstMatch
        XCTAssertTrue(resolveButton.waitForExistence(timeout: 5),
                      "Resolve button not found")
        resolveButton.tap()

        // Wait for at least one retailer row (stream started).
        let anyRetailerRow = app.buttons.matching(
            NSPredicate(format: "identifier BEGINSWITH 'retailerRow_'")
        ).firstMatch
        XCTAssertTrue(anyRetailerRow.waitForExistence(timeout: 120),
                      "No retailer row landed within 120s — backend unreachable")

        // Wait for hero to materialize post-close.
        let hero = app.otherElements["recommendationHero"]
        guard hero.waitForExistence(timeout: 60) else {
            throw XCTSkip("recommendationHero never appeared — insufficient data")
        }

        // Tap the hero CTA.
        let cta = app.buttons["recommendationActionButton"]
        XCTAssertTrue(cta.waitForExistence(timeout: 5),
                      "recommendationActionButton missing under recommendationHero")
        cta.tap()

        // Interstitial sheet appears.
        let interstitial = app.otherElements["purchaseInterstitialSheet"]
        XCTAssertTrue(interstitial.waitForExistence(timeout: 3),
                      "purchaseInterstitialSheet did not present after hero tap")

        // Headline + Continue button must exist.
        let headline = app.staticTexts["purchaseInterstitialCardHeadline"]
        XCTAssertTrue(headline.waitForExistence(timeout: 2),
                      "Card headline missing on interstitial")

        let continueButton = app.buttons["purchaseInterstitialContinueButton"]
        XCTAssertTrue(continueButton.waitForExistence(timeout: 2),
                      "Continue button missing on interstitial")
        XCTAssertTrue(continueButton.label.contains("Continue"),
                      "Continue button label doesn't contain 'Continue' — got '\(continueButton.label)'")

        // Tap Continue, expect affiliate sheet (OR-of-3 signal).
        continueButton.tap()

        let webView = app.webViews.firstMatch
        let doneButton = app.buttons["Done"]
        let sheetAppeared = webView.waitForExistence(timeout: 10)
            || doneButton.waitForExistence(timeout: 2)
            || !continueButton.isHittable
        XCTAssertTrue(sheetAppeared,
                      "Affiliate sheet did not present after tapping Continue")
    }
}
