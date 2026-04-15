//
//  BarkainUITests.swift
//  BarkainUITests
//
//  Step 2i-d — E2E smoke test for manual UPC entry → price comparison →
//  affiliate sheet (SFSafariViewController). Requires the backend to be
//  running on http://127.0.0.1:8000 with at least Amazon / Best Buy / Walmart
//  containers reachable through the EC2 SSH tunnel. See plan file
//  ~/.claude/plans/lexical-coalescing-lemur.md.
//

import XCTest

final class BarkainUITests: XCTestCase {

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testManualUPCEntryToAffiliateSheet() throws {
        let app = XCUIApplication()
        app.launch()

        let manualEntry = app.buttons["manualEntryButton"]
        XCTAssertTrue(manualEntry.waitForExistence(timeout: 10),
                      "manualEntryButton never appeared — is the Scan tab active?")
        manualEntry.tap()

        let upcField = app.textFields["upcTextField"]
        XCTAssertTrue(upcField.waitForExistence(timeout: 5),
                      "upcTextField did not appear in manual entry sheet")
        upcField.tap()
        upcField.typeText("194252818381") // Apple AirPods 3rd Gen — seeded demo UPC

        app.buttons["resolveButton"].tap()

        // SSE stream fills in per-retailer over ~30-60s. Amazon is typically
        // the first to land but we accept any of the three validated retailers.
        let amazonRow = app.buttons["retailerRow_amazon"]
        let bestBuyRow = app.buttons["retailerRow_best_buy"]
        let walmartRow = app.buttons["retailerRow_walmart"]

        let predicate = NSPredicate(format: "exists == true")
        let anyRow = expectation(for: predicate, evaluatedWith: amazonRow)
        let anyRow2 = expectation(for: predicate, evaluatedWith: bestBuyRow)
        let anyRow3 = expectation(for: predicate, evaluatedWith: walmartRow)
        let result = XCTWaiter().wait(for: [anyRow, anyRow2, anyRow3], timeout: 90, enforceOrder: false)
        XCTAssertTrue(result == .completed || amazonRow.exists || bestBuyRow.exists || walmartRow.exists,
                      "No retailer row appeared within 90s — SSE stream stalled or backend unreachable")

        // Pick whichever row exists, prefer Amazon (affiliate tag is the
        // strongest verification target: tag=barkain-20).
        let targetRow: XCUIElement
        if amazonRow.exists { targetRow = amazonRow }
        else if bestBuyRow.exists { targetRow = bestBuyRow }
        else { targetRow = walmartRow }

        targetRow.tap()

        // SFSafariViewController presents in a separate view service process.
        // iOS 26's SFSafari chrome (Done button, URL bar) lives in a system
        // accessibility tree that XCUITest cannot reliably traverse from the
        // host app, so we look for any of three independent signals:
        //   (1) a webview (SFSafari's WKWebView is sometimes exposed)
        //   (2) a "Done" button (labeled that way in iOS ≤ 25)
        //   (3) the original row becoming non-hittable because a modal is on top
        // The backend-side POST /affiliate/click row logged by m12 is the
        // authoritative proof the flow fired; this assertion just catches
        // a mid-tap crash or a sheet that never presents.
        let webView = app.webViews.firstMatch
        let doneButton = app.buttons["Done"]
        let sheetAppeared = webView.waitForExistence(timeout: 10)
            || doneButton.waitForExistence(timeout: 2)
            || !targetRow.isHittable
        XCTAssertTrue(sheetAppeared,
                      "Affiliate sheet did not present after tapping \(targetRow.identifier)")
    }
}
