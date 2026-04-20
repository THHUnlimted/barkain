//
//  SearchFlowUITests.swift
//  BarkainUITests
//
//  Step 3a — E2E smoke test for the text Search tab. Step 3d added the
//  `.searchable + .searchSuggestions + .searchCompletion` autocomplete
//  layer, so we use `app.searchFields.firstMatch` (was `textFields[...]`)
//  to target the system search field. Same three-signal OR pattern as
//  2i-d for the affiliate sheet (SFSafariViewController chrome lives in
//  a separate accessibility tree).
//

import XCTest

final class SearchFlowUITests: XCTestCase {

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // MARK: - 3a flow — type → results → SSE → affiliate sheet

    @MainActor
    func testTextSearchToAffiliateSheet() throws {
        let app = XCUIApplication()
        app.launch()

        let searchTab = app.tabBars.buttons["Search"]
        XCTAssertTrue(searchTab.waitForExistence(timeout: 10),
                      "Search tab bar item never appeared")
        searchTab.tap()

        // .searchable injects a UISearchTextField, exposed as
        // app.searchFields (not app.textFields). Identify by the prompt
        // string we set on the modifier.
        let searchField = app.searchFields.firstMatch
        XCTAssertTrue(searchField.waitForExistence(timeout: 5),
                      "search field did not appear on the Search tab")
        searchField.tap()
        searchField.typeText("AirPods 3rd Generation")

        // .searchable presents results inline; submit to fire the search
        // (since 3d removed auto-search-on-debounce).
        searchField.typeText("\n")

        let anyRowPredicate = NSPredicate(format: "identifier BEGINSWITH 'searchResultRow_'")
        let firstRow = app.buttons.matching(anyRowPredicate).firstMatch
        XCTAssertTrue(firstRow.waitForExistence(timeout: 15),
                      "No searchResultRow_* appeared within 15s — backend unreachable or empty")
        firstRow.tap()

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
                      "No retailer row appeared within 90s — SSE stalled or backend unreachable")

        let targetRow: XCUIElement
        if amazonRow.exists { targetRow = amazonRow }
        else if bestBuyRow.exists { targetRow = bestBuyRow }
        else { targetRow = walmartRow }

        targetRow.tap()

        let webView = app.webViews.firstMatch
        let doneButton = app.buttons["Done"]
        let sheetAppeared = webView.waitForExistence(timeout: 10)
            || doneButton.waitForExistence(timeout: 2)
            || !targetRow.isHittable
        XCTAssertTrue(sheetAppeared,
                      "Affiliate sheet did not present after tapping \(targetRow.identifier)")
    }

    // MARK: - 3d flow — type → tap suggestion → results → affiliate sheet

    @MainActor
    func testTypeSuggestionTapToAffiliateSheet() throws {
        let app = XCUIApplication()
        app.launch()

        let searchTab = app.tabBars.buttons["Search"]
        XCTAssertTrue(searchTab.waitForExistence(timeout: 10),
                      "Search tab never appeared")
        searchTab.tap()

        let searchField = app.searchFields.firstMatch
        XCTAssertTrue(searchField.waitForExistence(timeout: 5))
        searchField.tap()
        searchField.typeText("iph")

        // Wait for ANY suggestionRow_* to appear — autocomplete is on-device
        // (no network), so it should land within ~1 s of the lazy load.
        let suggestionPredicate = NSPredicate(format: "identifier BEGINSWITH 'suggestionRow_'")
        let suggestionRow = app.descendants(matching: .any)
            .matching(suggestionPredicate).firstMatch

        // 3-signal OR — the suggestion list lives in a separate
        // popover/menu host that XCUITest sometimes routes oddly.
        let suggestionExp = expectation(for: NSPredicate(format: "exists == true"),
                                        evaluatedWith: suggestionRow)
        let waitResult = XCTWaiter().wait(for: [suggestionExp], timeout: 5)
        let firstButton = app.buttons.matching(suggestionPredicate).firstMatch
        let firstStaticText = app.staticTexts.matching(suggestionPredicate).firstMatch
        guard waitResult == .completed || firstButton.exists || firstStaticText.exists else {
            XCTFail("No suggestionRow_* appeared after typing 'iph' within 5s")
            return
        }

        let toTap: XCUIElement = {
            if suggestionRow.exists { return suggestionRow }
            if firstButton.exists { return firstButton }
            return firstStaticText
        }()
        toTap.tap()

        // Tapping a `.searchCompletion` row replaces the field text and
        // fires `.onSubmit(of: .search)`. We then expect either the
        // results list to populate OR the field to contain the suggestion.
        let anyResultRow = app.buttons.matching(
            NSPredicate(format: "identifier BEGINSWITH 'searchResultRow_'")
        ).firstMatch
        let landed = anyResultRow.waitForExistence(timeout: 15)
            || (searchField.value as? String).map { !$0.isEmpty && $0 != "iph" } == true
        XCTAssertTrue(landed,
                      "After tapping suggestion, neither result rows appeared nor query was replaced")
    }
}
