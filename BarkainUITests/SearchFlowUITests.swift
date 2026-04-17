//
//  SearchFlowUITests.swift
//  BarkainUITests
//
//  Step 3a — E2E smoke test for the text Search tab:
//  type query → wait for results → tap row → wait for SSE retailer row →
//  tap retailer → assert affiliate sheet presents.
//
//  Requires the backend to be running on http://127.0.0.1:8000 with at
//  least one of the validated retailer containers reachable. Mirrors the
//  2i-d BarkainUITests pattern — three-signal OR assertion for the
//  affiliate sheet because SFSafariViewController chrome lives in a
//  separate accessibility tree XCUITest cannot traverse.
//

import XCTest

final class SearchFlowUITests: XCTestCase {

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testTextSearchToAffiliateSheet() throws {
        let app = XCUIApplication()
        app.launch()

        // Switch to the Search tab. The TabView item is labeled "Search".
        let searchTab = app.tabBars.buttons["Search"]
        XCTAssertTrue(searchTab.waitForExistence(timeout: 10),
                      "Search tab bar item never appeared")
        searchTab.tap()

        // Find the search text field and type a known-good query. We use
        // "Apple AirPods 3rd Gen" because its UPC (194252818381) is the
        // seeded demo the Scanner test uses — so the backend DB fuzzy
        // match returns an immediate result without needing Gemini.
        let searchField = app.textFields["searchTextField"]
        XCTAssertTrue(searchField.waitForExistence(timeout: 5),
                      "searchTextField did not appear on the Search tab")
        searchField.tap()
        searchField.typeText("AirPods 3rd Generation")

        // Wait for at least one searchResultRow_* to appear. Debounce is
        // 300ms; backend DB fuzzy match is <50ms; allow 10s slack for
        // cold-start Gemini fallback if the DB miss-lists.
        let anyRowPredicate = NSPredicate(format: "identifier BEGINSWITH 'searchResultRow_'")
        let firstRow = app.buttons.matching(anyRowPredicate).firstMatch
        XCTAssertTrue(firstRow.waitForExistence(timeout: 15),
                      "No searchResultRow_* appeared within 15s — debounce stalled or backend unreachable")
        firstRow.tap()

        // SSE stream fills in retailers after the resolve completes — same
        // contract as the Scanner flow. Accept any validated retailer.
        let amazonRow = app.buttons["retailerRow_amazon"]
        let bestBuyRow = app.buttons["retailerRow_best_buy"]
        let walmartRow = app.buttons["retailerRow_walmart"]

        let existsPredicate = NSPredicate(format: "exists == true")
        let amazonExp = expectation(for: existsPredicate, evaluatedWith: amazonRow)
        let bestBuyExp = expectation(for: existsPredicate, evaluatedWith: bestBuyRow)
        let walmartExp = expectation(for: existsPredicate, evaluatedWith: walmartRow)
        let result = XCTWaiter().wait(for: [amazonExp, bestBuyExp, walmartExp],
                                      timeout: 90, enforceOrder: false)
        XCTAssertTrue(result == .completed || amazonRow.exists || bestBuyRow.exists || walmartRow.exists,
                      "No retailer row appeared within 90s — SSE stream stalled or backend unreachable")

        let targetRow: XCUIElement
        if amazonRow.exists { targetRow = amazonRow }
        else if bestBuyRow.exists { targetRow = bestBuyRow }
        else { targetRow = walmartRow }

        targetRow.tap()

        // Three-signal OR for affiliate sheet presentation (same as 2i-d).
        let webView = app.webViews.firstMatch
        let doneButton = app.buttons["Done"]
        let sheetAppeared = webView.waitForExistence(timeout: 10)
            || doneButton.waitForExistence(timeout: 2)
            || !targetRow.isHittable
        XCTAssertTrue(sheetAppeared,
                      "Affiliate sheet did not present after tapping \(targetRow.identifier)")
    }
}
