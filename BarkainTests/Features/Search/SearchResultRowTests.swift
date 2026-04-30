import XCTest

@testable import Barkain

// MARK: - thumbnail-coverage-L1 placeholder helper

final class SearchResultRowBrandInitialsTests: XCTestCase {

    func test_returnsTwoInitialsForMultiTokenBrand() {
        XCTAssertEqual(
            SearchResultRow.brandInitials(from: "Apple Inc"),
            "AI"
        )
        XCTAssertEqual(
            SearchResultRow.brandInitials(from: "Sony Interactive Entertainment"),
            "SI",
            "Caps at two initials even when more tokens are available"
        )
    }

    func test_splitsOnHyphensSoRustOleumYieldsRO() {
        // Hyphen is the canonical separator for "Rust-Oleum" /
        // "Coca-Cola" — the iOS hyphen-norm work in step-3o-C-followups
        // strips them for autocomplete; the placeholder should treat
        // them as token boundaries here so we get RO instead of "RU".
        XCTAssertEqual(
            SearchResultRow.brandInitials(from: "Rust-Oleum"),
            "RO"
        )
        XCTAssertEqual(
            SearchResultRow.brandInitials(from: "Coca-Cola"),
            "CC"
        )
    }

    func test_returnsTwoLeadingLettersForSingleTokenBrand() {
        XCTAssertEqual(
            SearchResultRow.brandInitials(from: "Apple"),
            "AP"
        )
        XCTAssertEqual(
            SearchResultRow.brandInitials(from: "Samsung"),
            "SA"
        )
    }

    func test_uppercasesLowercaseInput() {
        XCTAssertEqual(
            SearchResultRow.brandInitials(from: "apple"),
            "AP"
        )
        XCTAssertEqual(
            SearchResultRow.brandInitials(from: "rust-oleum"),
            "RO"
        )
    }

    func test_returnsNilForEmptyOrNilOrWhitespaceOnly() {
        XCTAssertNil(SearchResultRow.brandInitials(from: nil))
        XCTAssertNil(SearchResultRow.brandInitials(from: ""))
        XCTAssertNil(SearchResultRow.brandInitials(from: "   "))
        XCTAssertNil(SearchResultRow.brandInitials(from: "\n\t  "))
    }

    func test_returnsNilForNonAlphabeticBrand() {
        // "(generic)" + "123" + "—" — none start with a letter on any
        // token, so nothing alphabetic to take an initial from. Falling
        // back to the pawprint placeholder is the right call.
        XCTAssertNil(SearchResultRow.brandInitials(from: "(generic)"))
        XCTAssertNil(SearchResultRow.brandInitials(from: "123"))
        XCTAssertNil(SearchResultRow.brandInitials(from: "—"))
    }

    func test_skipsLeadingNonAlphaTokensInMultiTokenBrand() {
        // "3M Company" — first token starts with a digit; second token
        // starts with a letter. We want one initial ("C") rather than
        // failing — but the helper iterates tokens and only takes
        // letter-leading ones, so "3M Company" yields "C". Acceptable
        // given it's better than nothing.
        XCTAssertEqual(
            SearchResultRow.brandInitials(from: "3M Company"),
            "C"
        )
    }

    func test_acceptsUnicodeLetters() {
        // BLÅHAJ-style brand names — the helper uses `Character.isLetter`
        // which is Unicode-aware.
        XCTAssertEqual(
            SearchResultRow.brandInitials(from: "Łódź"),
            "ŁÓ"
        )
    }
}
